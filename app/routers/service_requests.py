import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.deps import CurrentUser, get_current_user, require_roles
from app.database import get_db
from app.models.core import Equipment, EquipmentType, Task, TaskStatus, User, UserRole
from app.models.customer import Client, Site
from app.models.repair import Repair, RepairAttachment, RepairPart
from app.models.service_request import ServiceRequest, ServiceRequestEvent
from app.models.warehouse import Part
from app.schemas.service_request import REQUEST_STATUSES, ServiceRequestApproval, ServiceRequestOut, ServiceRequestStatusUpdate
from app.services.service_requests import event

router = APIRouter(prefix="/api/service-requests", tags=["service requests"])

TECHNICIAN_TRANSITIONS = {
    "assigned": {"on_the_way"}, "on_the_way": {"arrived"}, "arrived": {"in_progress"},
    "in_progress": {"waiting_parts", "waiting_approval", "completed"},
    "waiting_parts": {"in_progress"}, "waiting_approval": set(),
}

def client_label(client: Client, site: Site) -> str:
    name = (client.legal_name or client.name or "").strip()
    return site.name if name.lower() == "импортированные клиенты" else (name or site.name)


async def serialize(db, request, org):
    row = (await db.execute(
        select(Equipment, EquipmentType.name, Site, Client, User.full_name)
        .join(EquipmentType, EquipmentType.id == Equipment.equipment_type_id)
        .join(Site, Site.id == Equipment.site_id)
        .join(Client, Client.id == Site.client_id)
        .outerjoin(User, User.id == request.assigned_technician_id)
        .where(Equipment.id == request.equipment_id, Equipment.organization_id == org, Site.organization_id == org, Client.organization_id == org)
    )).one()
    equipment, equipment_type, site, client, technician_name = row
    repair_query = select(Repair).where(Repair.organization_id == org, Repair.equipment_id == request.equipment_id)
    if request.task_id:
        repair_query = repair_query.where(Repair.task_id == request.task_id)
    elif request.ticket_id:
        repair_query = repair_query.where(Repair.ticket_id == request.ticket_id)
    repair = await db.scalar(repair_query.order_by(Repair.closed_at.desc(), Repair.created_at.desc()))
    parts = []
    if repair:
        parts = [{"part_name": name, "article": article, "quantity": qty} for name, article, qty in (await db.execute(select(Part.name, Part.article, RepairPart.quantity).join(RepairPart, RepairPart.part_id == Part.id).where(RepairPart.repair_id == repair.id))).all()]
    attachments = []
    if repair:
        attachments = [{"id": item.id, "kind": item.kind, "name": item.original_name, "media_type": item.media_type, "at": item.uploaded_at} for item in (await db.scalars(select(RepairAttachment).where(RepairAttachment.organization_id == org, RepairAttachment.repair_id == repair.id).order_by(RepairAttachment.uploaded_at))).all()]
    history = [{"at": item.created_at, "type": item.event_type, "message": item.message, "details": item.details_json} for item in (await db.scalars(select(ServiceRequestEvent).where(ServiceRequestEvent.organization_id == org, ServiceRequestEvent.service_request_id == request.id).order_by(ServiceRequestEvent.created_at))).all()]
    if not any(item["type"] == "request.created" for item in history):
        history.insert(0, {"at": request.created_at, "type": "request.created", "message": "Заявка создана", "details": {}})
    return ServiceRequestOut(id=request.id, number=request.number, ticket_id=request.ticket_id, task_id=request.task_id, equipment_id=request.equipment_id, client_name=client_label(client, site), site_name=site.name, equipment_name=equipment.name, serial_number=equipment.serial_number, description=request.description, priority=request.priority, assigned_technician_id=request.assigned_technician_id, assigned_technician_name=technician_name, status=request.status, created_at=request.created_at, completed_at=request.completed_at, repair_id=repair.id if repair else None, parts_used=parts, outcome=repair.description if repair else None, history=history, site_address=site.address, contact_name=site.contact_name or client.contact_name, contact_phone=site.contact_phone or client.contact_phone, equipment_type=equipment_type, manufacturer=equipment.manufacturer, model=equipment.model, equipment_status=equipment.status.value, equipment_version=equipment.version, attachments=attachments)

@router.get("", response_model=list[ServiceRequestOut])
async def list_requests(db: AsyncSession = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    query = select(ServiceRequest).where(ServiceRequest.organization_id == user.organization_id).order_by(ServiceRequest.created_at.desc())
    if user.role == UserRole.technician: query = query.where(ServiceRequest.assigned_technician_id == user.id)
    return [await serialize(db, item, user.organization_id) for item in (await db.scalars(query)).all()]

@router.get("/{request_id}", response_model=ServiceRequestOut)
async def get_request(request_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    request = await db.scalar(select(ServiceRequest).where(ServiceRequest.id == request_id, ServiceRequest.organization_id == user.organization_id))
    if not request or (user.role == UserRole.technician and request.assigned_technician_id != user.id): raise HTTPException(404, "Заявка не найдена")
    return await serialize(db, request, user.organization_id)

@router.patch("/{request_id}/status", response_model=ServiceRequestOut)
async def update_status(request_id: uuid.UUID, payload: ServiceRequestStatusUpdate, db: AsyncSession = Depends(get_db), user: CurrentUser = Depends(require_roles(UserRole.dispatcher, UserRole.technician))):
    if payload.status not in REQUEST_STATUSES: raise HTTPException(422, "Неизвестный статус заявки")
    request = await db.scalar(select(ServiceRequest).where(ServiceRequest.id == request_id, ServiceRequest.organization_id == user.organization_id).with_for_update())
    if not request or (user.role == UserRole.technician and request.assigned_technician_id != user.id): raise HTTPException(404, "Заявка не найдена")
    previous = request.status
    if user.role == UserRole.technician and payload.status not in TECHNICIAN_TRANSITIONS.get(previous, set()):
        raise HTTPException(409, "Этот переход недоступен на текущем этапе заявки")
    if user.role != UserRole.technician and previous == "waiting_approval" and payload.status in {"in_progress", "cancelled"}:
        raise HTTPException(409, "Используйте действие согласования для этой заявки")
    request.status = payload.status
    if payload.status in {"completed", "closed", "cancelled"}: request.completed_at = datetime.now(timezone.utc)
    if request.task_id and payload.status == "in_progress":
        task = await db.scalar(select(Task).where(Task.id == request.task_id, Task.organization_id == user.organization_id))
        if task: task.status = TaskStatus.in_progress
    event_messages = {"on_the_way": "Мастер выехал", "arrived": "Мастер прибыл на объект", "in_progress": "Работа начата", "waiting_parts": "Ожидание запчастей", "waiting_approval": "Ожидание согласования", "completed": "Работы завершены"}
    event_types = {"on_the_way": "technician.on_the_way", "arrived": "technician.arrived", "in_progress": "work.started", "waiting_parts": "request.waiting_parts", "waiting_approval": "request.waiting_approval", "completed": "repair.completed"}
    details = {"from": previous, "to": payload.status, "transitioned_at": datetime.now(timezone.utc).isoformat()}
    if payload.details:
        details.update(payload.details)
    db.add(event(user.organization_id, request.id, user.id, event_types.get(payload.status, "status.changed"), payload.note or event_messages.get(payload.status, f"Статус: {previous} → {payload.status}"), details))
    await db.commit(); await db.refresh(request)
    return await serialize(db, request, user.organization_id)

@router.patch("/{request_id}/approval", response_model=ServiceRequestOut)
async def decide_approval(request_id: uuid.UUID, payload: ServiceRequestApproval, db: AsyncSession = Depends(get_db), user: CurrentUser = Depends(require_roles(UserRole.admin, UserRole.dispatcher))):
    request = await db.scalar(select(ServiceRequest).where(ServiceRequest.id == request_id, ServiceRequest.organization_id == user.organization_id).with_for_update())
    if not request:
        raise HTTPException(404, "Заявка не найдена")
    if request.status != "waiting_approval":
        raise HTTPException(409, "Заявка не ожидает согласования")
    approved_at = datetime.now(timezone.utc)
    details = {"approved_by": str(user.id), "approved_at": approved_at.isoformat(), "comment": payload.comment}
    if payload.action == "approved":
        request.status = "in_progress"
        if request.task_id:
            task = await db.scalar(select(Task).where(Task.id == request.task_id, Task.organization_id == user.organization_id))
            if task: task.status = TaskStatus.in_progress
        db.add(event(user.organization_id, request.id, user.id, "approval.approved", "Работы согласованы, заявка возвращена мастеру", details))
    else:
        request.status = "cancelled"
        request.completed_at = approved_at
        if request.task_id:
            task = await db.scalar(select(Task).where(Task.id == request.task_id, Task.organization_id == user.organization_id))
            if task: task.status = TaskStatus.cancelled
        db.add(event(user.organization_id, request.id, user.id, "approval.rejected", payload.comment or "Согласование отклонено", details))
    await db.commit(); await db.refresh(request)
    return await serialize(db, request, user.organization_id)
