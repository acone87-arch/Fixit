import uuid
from datetime import datetime, timezone
from pathlib import Path
from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.deps import CurrentUser, get_current_user, require_roles
from app.database import get_db
from app.models.core import Equipment, EquipmentAttachment, EquipmentType, Task, TaskStatus, User, UserRole
from app.models.customer import Client, Site
from app.models.organization import OrganizationMembership
from app.models.repair import Repair, RepairAttachment, RepairPart
from app.models.service_request import ServiceRequest, ServiceRequestAttachment, ServiceRequestEvent
from app.models.warehouse import Part
from app.schemas.service_request import REQUEST_STATUSES, ServiceRequestApproval, ServiceRequestAttachmentOut, ServiceRequestDetail, ServiceRequestListItem, ServiceRequestOut, ServiceRequestStatusUpdate
from app.services.service_requests import event

router = APIRouter(prefix="/api/service-requests", tags=["service requests"])
UPLOAD_ROOT = Path("uploads")
MAX_ATTACHMENT_BYTES = 8 * 1024 * 1024
REQUEST_ATTACHMENT_KINDS = {"problem", "diagnostic", "approval", "work", "other"}

TECHNICIAN_TRANSITIONS = {
    "assigned": {"on_the_way"}, "on_the_way": {"arrived"}, "arrived": {"in_progress"},
    "in_progress": {"waiting_parts", "waiting_approval", "completed"},
    "waiting_parts": {"in_progress"}, "waiting_approval": set(),
}

def client_label(client: Client, site: Site) -> str:
    name = (client.legal_name or client.name or "").strip()
    return site.name if name.lower() == "импортированные клиенты" else (name or site.name)


def attachment_out(item: ServiceRequestAttachment) -> ServiceRequestAttachmentOut:
    return ServiceRequestAttachmentOut(
        id=item.id, kind=item.kind, original_name=item.original_name, media_type=item.media_type,
        byte_size=item.byte_size, created_at=item.created_at,
        download_url=f"/api/service-requests/attachments/{item.id}",
    )


async def request_for_user(request_id: uuid.UUID, db: AsyncSession, user: CurrentUser) -> ServiceRequest:
    request = await db.scalar(select(ServiceRequest).where(
        ServiceRequest.id == request_id,
        ServiceRequest.organization_id == user.organization_id,
    ))
    if not request or (user.role == UserRole.technician and request.assigned_technician_id != user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Заявка не найдена")
    return request


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
    primary_photo = await db.scalar(select(EquipmentAttachment).where(
        EquipmentAttachment.equipment_id == equipment.id,
        EquipmentAttachment.organization_id == org,
    ))
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
    request_attachments = [attachment_out(item).model_dump() for item in (await db.scalars(select(ServiceRequestAttachment).where(
        ServiceRequestAttachment.organization_id == org,
        ServiceRequestAttachment.service_request_id == request.id,
    ).order_by(ServiceRequestAttachment.created_at))).all()]
    events = (await db.scalars(select(ServiceRequestEvent).where(
        ServiceRequestEvent.organization_id == org,
        ServiceRequestEvent.service_request_id == request.id,
    ).order_by(ServiceRequestEvent.created_at))).all()
    actor_ids = {item.actor_user_id for item in events if item.actor_user_id}
    actor_map = {}
    if actor_ids:
        actor_rows = (await db.execute(
            select(User.id, User.full_name, OrganizationMembership.role)
            .outerjoin(OrganizationMembership, (OrganizationMembership.user_id == User.id) & (OrganizationMembership.organization_id == org))
            .where(User.id.in_(actor_ids))
        )).all()
        actor_map = {
            actor_id: {"id": actor_id, "full_name": full_name, "role": role.value if role else None}
            for actor_id, full_name, role in actor_rows
        }
    history = [{"at": item.created_at, "type": item.event_type, "message": item.message,
                "details": item.details_json or {}, "actor": actor_map.get(item.actor_user_id)} for item in events]
    if not any(item["type"] == "request.created" for item in history):
        history.insert(0, {"at": request.created_at, "type": "request.created", "message": "Заявка создана", "details": {}, "actor": None})
    photo_out = {"id": primary_photo.id, "original_name": primary_photo.original_name, "media_type": primary_photo.media_type, "byte_size": primary_photo.byte_size, "uploaded_at": primary_photo.uploaded_at, "download_url": f"/api/equipment/{equipment.id}/photo"} if primary_photo else None
    return ServiceRequestDetail(id=request.id, number=request.number, ticket_id=request.ticket_id, task_id=request.task_id, equipment_id=request.equipment_id, title=request.title, client_name=client_label(client, site), site_name=site.name, equipment_name=equipment.name, serial_number=equipment.serial_number, description=request.description, priority=request.priority, assigned_technician_id=request.assigned_technician_id, assigned_technician_name=technician_name, status=request.status, created_at=request.created_at, completed_at=request.completed_at, repair_id=repair.id if repair else None, parts_used=parts, outcome=repair.description if repair else None, history=history, site_address=site.address, contact_name=site.contact_name or client.contact_name, contact_phone=site.contact_phone or client.contact_phone, equipment_type=equipment_type, manufacturer=equipment.manufacturer, model=equipment.model, equipment_status=equipment.status.value, equipment_version=equipment.version, attachments=attachments, request_attachments=request_attachments, primary_photo=photo_out)


@router.post("/{request_id}/attachments", response_model=ServiceRequestAttachmentOut, status_code=status.HTTP_201_CREATED)
async def upload_request_attachment(
    request_id: uuid.UUID,
    kind: str = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    request = await request_for_user(request_id, db, user)
    if kind not in REQUEST_ATTACHMENT_KINDS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Неизвестный тип вложения")
    content = await file.read(MAX_ATTACHMENT_BYTES + 1)
    media_type = file.content_type or ""
    if not content or len(content) > MAX_ATTACHMENT_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Файл должен быть не больше 8 МБ")
    if not media_type.startswith("image/"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Для заявки можно загрузить только изображение")
    attachment_id = uuid.uuid4()
    suffix = Path(file.filename or "attachment").suffix.lower()
    if len(suffix) > 10 or not suffix.replace(".", "").isalnum():
        suffix = ""
    relative_path = Path(str(user.organization_id)) / "service-requests" / str(request.id) / f"{attachment_id}{suffix}"
    destination = UPLOAD_ROOT / relative_path
    await run_in_threadpool(destination.parent.mkdir, parents=True, exist_ok=True)
    await run_in_threadpool(destination.write_bytes, content)
    attachment = ServiceRequestAttachment(
        id=attachment_id, organization_id=user.organization_id, service_request_id=request.id,
        uploaded_by_user_id=user.id, kind=kind, file_url=str(relative_path).replace("\\", "/"),
        original_name=(file.filename or "фото заявки")[:255], media_type=media_type[:100], byte_size=len(content),
    )
    db.add(attachment)
    await db.commit()
    await db.refresh(attachment)
    return attachment_out(attachment)


@router.get("/{request_id}/attachments", response_model=list[ServiceRequestAttachmentOut])
async def list_request_attachments(request_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    await request_for_user(request_id, db, user)
    items = (await db.scalars(select(ServiceRequestAttachment).where(
        ServiceRequestAttachment.organization_id == user.organization_id,
        ServiceRequestAttachment.service_request_id == request_id,
    ).order_by(ServiceRequestAttachment.created_at))).all()
    return [attachment_out(item) for item in items]


@router.get("/attachments/{attachment_id}")
async def download_request_attachment(attachment_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    attachment = await db.scalar(select(ServiceRequestAttachment).where(
        ServiceRequestAttachment.id == attachment_id,
        ServiceRequestAttachment.organization_id == user.organization_id,
    ))
    if not attachment:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Вложение заявки не найдено")
    await request_for_user(attachment.service_request_id, db, user)
    path = UPLOAD_ROOT / attachment.file_url
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Файл вложения не найден")
    return Response(await run_in_threadpool(path.read_bytes), media_type=attachment.media_type or "image/jpeg")

@router.get("", response_model=list[ServiceRequestListItem])
async def list_requests(db: AsyncSession = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    # The queue deliberately has no repair, attachment, or event data.  Detail is
    # fetched only after a user opens a particular request.
    query = (
        select(ServiceRequest, Equipment, EquipmentType.name, Site, Client, User.full_name)
        .join(Equipment, Equipment.id == ServiceRequest.equipment_id)
        .outerjoin(EquipmentType, EquipmentType.id == Equipment.equipment_type_id)
        .join(Site, Site.id == Equipment.site_id)
        .join(Client, Client.id == Site.client_id)
        .outerjoin(User, User.id == ServiceRequest.assigned_technician_id)
        .where(
            ServiceRequest.organization_id == user.organization_id,
            Equipment.organization_id == user.organization_id,
            Site.organization_id == user.organization_id,
            Client.organization_id == user.organization_id,
        )
        .order_by(ServiceRequest.created_at.desc())
    )
    if user.role == UserRole.technician:
        query = query.where(ServiceRequest.assigned_technician_id == user.id)
    rows = (await db.execute(query)).all()
    return [
        ServiceRequestListItem(
            id=request.id, number=request.number, status=request.status, priority=request.priority,
            title=request.title, description=request.description, client_name=client_label(client, site),
            site_name=site.name, equipment_name=equipment.name, equipment_type=equipment_type,
            manufacturer=equipment.manufacturer, model=equipment.model, serial_number=equipment.serial_number,
            assigned_technician_id=request.assigned_technician_id, assigned_technician_name=technician_name,
            created_at=request.created_at, completed_at=request.completed_at,
        )
        for request, equipment, equipment_type, site, client, technician_name in rows
    ]

@router.get("/{request_id}", response_model=ServiceRequestDetail)
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
