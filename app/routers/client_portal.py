import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import CurrentUser, get_current_user, require_roles
from app.database import get_db
from app.models.core import Equipment, EquipmentAttachment, EquipmentType, Task, TaskStatus, User, UserRole
from app.models.customer import Client, ClientUserAccess, Site
from app.models.repair import Repair
from app.models.service_request import ServiceRequest
from app.models.organization import OrganizationMembership
from app.routers.service_requests import client_label, serialize
from app.schemas.customer import ClientAccessCreate, ClientAccessOut, ClientAccessUpdate
from app.schemas.service_request import ServiceRequestApproval, ServiceRequestCreate, ServiceRequestDetail, ServiceRequestListItem
from app.services.client_portal import client_scope, ensure_client_equipment
from app.services.service_requests import event, next_number

router = APIRouter(prefix="/api/client-portal", tags=["client portal"])


ACCESS_MANAGERS = (UserRole.owner, UserRole.admin, UserRole.dispatcher)


def repair_for_service_request_query(organization_id: uuid.UUID, request_id: uuid.UUID):
    """Canonical document ownership query; deliberately has no equipment
    fallback because equipment can have many completed requests."""
    return select(Repair).where(
        Repair.organization_id == organization_id,
        Repair.service_request_id == request_id,
    )


async def _access_member_and_client(db, organization_id, user_id, client_id):
    member = await db.scalar(select(OrganizationMembership).where(
        OrganizationMembership.organization_id == organization_id, OrganizationMembership.user_id == user_id,
        OrganizationMembership.is_active.is_(True),
        OrganizationMembership.role.in_({UserRole.client_admin, UserRole.client_site_user}),
    ))
    client = await db.scalar(select(Client).where(Client.id == client_id, Client.organization_id == organization_id))
    if not member or not client:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь или клиент не найден")
    return member, client


async def _validate_access_scope(db, organization_id, member, client_id, site_id):
    if member.role == UserRole.client_admin:
        if site_id is not None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Администратор клиента получает доступ ко всем объектам")
        return None
    if site_id is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Выберите объект для менеджера объекта")
    site = await db.scalar(select(Site).where(
        Site.id == site_id, Site.client_id == client_id, Site.organization_id == organization_id,
    ))
    if not site:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Объект не принадлежит клиенту")
    return site


def _access_out(access, account, member, site):
    return ClientAccessOut(
        id=access.id, user_id=account.id, full_name=account.full_name, email=account.email,
        role=member.role.value, client_id=access.client_id, site_id=access.site_id,
        site_name=site.name if site else None, is_active=access.is_active,
    )


async def _access_rows(db, organization_id, client_id):
    return (await db.execute(
        select(ClientUserAccess, User, OrganizationMembership, Site)
        .join(User, User.id == ClientUserAccess.user_id)
        .join(OrganizationMembership, (OrganizationMembership.user_id == User.id) &
              (OrganizationMembership.organization_id == ClientUserAccess.organization_id))
        .outerjoin(Site, Site.id == ClientUserAccess.site_id)
        .where(ClientUserAccess.organization_id == organization_id, ClientUserAccess.client_id == client_id)
        .order_by(User.full_name, Site.name)
    )).all()


@router.get("/access", response_model=list[ClientAccessOut])
async def list_access(client_id: uuid.UUID, db: AsyncSession = Depends(get_db),
                      user: CurrentUser = Depends(require_roles(*ACCESS_MANAGERS))):
    client = await db.scalar(select(Client.id).where(Client.id == client_id, Client.organization_id == user.organization_id))
    if not client:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Клиент не найден")
    return [_access_out(*row) for row in await _access_rows(db, user.organization_id, client_id)]


@router.post("/access", response_model=ClientAccessOut, status_code=status.HTTP_201_CREATED)
async def grant_access(payload: ClientAccessCreate, db: AsyncSession = Depends(get_db),
                       user: CurrentUser = Depends(require_roles(*ACCESS_MANAGERS))):
    member, _ = await _access_member_and_client(db, user.organization_id, payload.user_id, payload.client_id)
    site = await _validate_access_scope(db, user.organization_id, member, payload.client_id, payload.site_id)
    access = ClientUserAccess(organization_id=user.organization_id, user_id=payload.user_id,
                              client_id=payload.client_id, site_id=site.id if site else None)
    db.add(access)
    try: await db.commit()
    except Exception as exc:
        await db.rollback(); raise HTTPException(status.HTTP_409_CONFLICT, "Такой доступ уже назначен") from exc
    account = await db.get(User, payload.user_id)
    return _access_out(access, account, member, site)


@router.patch("/access/{access_id}", response_model=ClientAccessOut)
async def update_access(access_id: uuid.UUID, payload: ClientAccessUpdate, db: AsyncSession = Depends(get_db),
                        user: CurrentUser = Depends(require_roles(*ACCESS_MANAGERS))):
    access = await db.scalar(select(ClientUserAccess).where(
        ClientUserAccess.id == access_id, ClientUserAccess.organization_id == user.organization_id,
    ))
    if not access:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Доступ не найден")
    member, _ = await _access_member_and_client(db, user.organization_id, access.user_id, access.client_id)
    if "site_id" in payload.model_fields_set:
        site = await _validate_access_scope(db, user.organization_id, member, access.client_id, payload.site_id)
        access.site_id = site.id if site else None
    if "is_active" in payload.model_fields_set:
        access.is_active = payload.is_active
    try: await db.commit()
    except Exception as exc:
        await db.rollback(); raise HTTPException(status.HTTP_409_CONFLICT, "Такой доступ уже назначен") from exc
    site = await db.get(Site, access.site_id) if access.site_id else None
    account = await db.get(User, access.user_id)
    return _access_out(access, account, member, site)


@router.delete("/access/{access_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_access(access_id: uuid.UUID, db: AsyncSession = Depends(get_db),
                        user: CurrentUser = Depends(require_roles(*ACCESS_MANAGERS))):
    access = await db.scalar(select(ClientUserAccess).where(
        ClientUserAccess.id == access_id, ClientUserAccess.organization_id == user.organization_id,
    ))
    if not access:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Доступ не найден")
    await db.delete(access)
    await db.commit()


def _list_item(request, equipment, type_name, site, client):
    return ServiceRequestListItem(
        id=request.id, number=request.number, status=request.status, priority=request.priority,
        title=request.title, description=request.description, client_name=client_label(client, site),
        site_name=site.name, equipment_name=equipment.name, equipment_type=type_name,
        manufacturer=equipment.manufacturer, model=equipment.model, serial_number=equipment.serial_number,
        assigned_technician_id=None, assigned_technician_name=None,
        created_at=request.created_at, completed_at=request.completed_at,
    )


async def _requests_query(user, db):
    client_id, site_ids = await client_scope(user, db)
    query = (select(ServiceRequest, Equipment, EquipmentType.name, Site, Client)
        .join(Equipment, Equipment.id == ServiceRequest.equipment_id)
        .outerjoin(EquipmentType, EquipmentType.id == Equipment.equipment_type_id)
        .join(Site, Site.id == Equipment.site_id).join(Client, Client.id == Site.client_id)
        .where(ServiceRequest.organization_id == user.organization_id, Site.client_id == client_id,
               Site.organization_id == user.organization_id).order_by(ServiceRequest.created_at.desc()))
    if site_ids is not None:
        query = query.where(Site.id.in_(site_ids))
    return query, client_id, site_ids


@router.get("/dashboard")
async def dashboard(db: AsyncSession = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    query, client_id, site_ids = await _requests_query(user, db)
    requests = (await db.execute(query)).all()
    eq_query = select(Equipment).join(Site, Site.id == Equipment.site_id).where(
        Equipment.organization_id == user.organization_id, Site.client_id == client_id)
    if site_ids is not None: eq_query = eq_query.where(Site.id.in_(site_ids))
    equipment = (await db.scalars(eq_query)).all()
    active = [row[0] for row in requests if row[0].status not in {"completed", "closed", "cancelled"}]
    return {"client_name": (await db.scalar(select(Client.legal_name).where(Client.id == client_id))) or "Клиент",
            "equipment_total": len(equipment), "working": sum(item.status.value == "working" for item in equipment),
            "needs_repair": sum(item.status.value == "needs_repair" for item in equipment),
            "waiting_approval": sum(item.status == "waiting_approval" for item in active),
            "active_requests": len(active), "approval_requests": sum(item.status == "waiting_approval" and item.approval_target == "client" for item in active)}


@router.get("/equipment")
async def list_equipment(db: AsyncSession = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    client_id, site_ids = await client_scope(user, db)
    query = (select(Equipment, EquipmentType.name, Site, EquipmentAttachment)
        .join(Site, Site.id == Equipment.site_id).outerjoin(EquipmentType, EquipmentType.id == Equipment.equipment_type_id)
        .outerjoin(EquipmentAttachment, EquipmentAttachment.equipment_id == Equipment.id)
        .where(Equipment.organization_id == user.organization_id, Site.client_id == client_id).order_by(Equipment.updated_at.desc()))
    if site_ids is not None: query = query.where(Site.id.in_(site_ids))
    rows = (await db.execute(query)).all()
    return [{"id": item.id, "name": name or item.name, "manufacturer": item.manufacturer, "model": item.model,
             "serial_number": item.serial_number, "status": item.status.value, "site_name": site.name,
             "primary_photo": {"download_url": f"/api/equipment/{item.id}/photo"} if photo else None}
            for item, name, site, photo in rows]


@router.get("/requests", response_model=list[ServiceRequestListItem])
async def list_requests(db: AsyncSession = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    query, _, _ = await _requests_query(user, db)
    return [_list_item(*row) for row in (await db.execute(query)).all()]


@router.get("/requests/{request_id}", response_model=ServiceRequestDetail)
async def request_detail(request_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    query, _, _ = await _requests_query(user, db)
    row = (await db.execute(query.where(ServiceRequest.id == request_id))).first()
    if not row: raise HTTPException(status.HTTP_404_NOT_FOUND, "Заявка не найдена")
    return await serialize(db, row[0], user.organization_id)


@router.post("/requests", response_model=ServiceRequestDetail, status_code=status.HTTP_201_CREATED)
async def create_request(payload: ServiceRequestCreate, db: AsyncSession = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    equipment = await ensure_client_equipment(payload.equipment_id, user, db)
    request = ServiceRequest(organization_id=user.organization_id, number=await next_number(db, user.organization_id),
        equipment_id=equipment.id, title=payload.title, description=payload.description, priority=payload.priority, status="new")
    db.add(request); await db.flush()
    db.add(event(user.organization_id, request.id, user.id, "request.created", "Заявка создана клиентом", {"source": "client_portal"}))
    await db.commit(); await db.refresh(request)
    return await serialize(db, request, user.organization_id)


@router.patch("/requests/{request_id}/approval", response_model=ServiceRequestDetail)
async def approve_request(request_id: uuid.UUID, payload: ServiceRequestApproval, db: AsyncSession = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    query, _, _ = await _requests_query(user, db)
    row = (await db.execute(query.where(ServiceRequest.id == request_id).with_for_update())).first()
    if not row: raise HTTPException(status.HTTP_404_NOT_FOUND, "Заявка не найдена")
    request = row[0]
    if request.status != "waiting_approval" or request.approval_target != "client":
        raise HTTPException(status.HTTP_409_CONFLICT, "Заявка не ожидает согласования клиента")
    now = datetime.now(timezone.utc)
    details = {"approved_by": str(user.id), "approved_at": now.isoformat(), "comment": payload.comment, "target": "client"}
    if payload.action == "approved":
        request.status = "in_progress"
        if request.task_id:
            task = await db.scalar(select(Task).where(Task.id == request.task_id, Task.organization_id == user.organization_id))
            if task: task.status = TaskStatus.in_progress
        db.add(event(user.organization_id, request.id, user.id, "approval.approved", "Работы согласованы клиентом", details))
    else:
        if not payload.comment: raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Укажите причину отказа")
        request.status = "cancelled"; request.completed_at = now
        if request.task_id:
            task = await db.scalar(select(Task).where(Task.id == request.task_id, Task.organization_id == user.organization_id))
            if task: task.status = TaskStatus.cancelled
        db.add(event(user.organization_id, request.id, user.id, "approval.rejected", "Согласование отклонено клиентом", details))
    await db.commit(); await db.refresh(request)
    return await serialize(db, request, user.organization_id)


@router.get("/documents")
async def documents(db: AsyncSession = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    query, _, _ = await _requests_query(user, db)
    rows = (await db.execute(query.where(ServiceRequest.status.in_({"completed", "closed"})))).all()
    result = []
    for request, equipment, _, site, _ in rows:
        # A document belongs to its request, never to whichever repair for the
        # same equipment happened to finish most recently.
        repair = await db.scalar(repair_for_service_request_query(user.organization_id, request.id))
        if repair: result.append({"repair_id": repair.id, "number": request.number, "equipment_name": equipment.name, "site_name": site.name, "closed_at": repair.closed_at})
    return result
