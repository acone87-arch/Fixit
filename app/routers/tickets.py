import uuid
from collections import defaultdict, deque
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_roles
from app.database import get_db
from app.models.core import Equipment, EquipmentAttachment, EquipmentStatus, EquipmentType, Task, TaskPriority, TaskStatus, Ticket, User, UserRole
from app.models.organization import OrganizationMembership
from app.models.customer import Site
from app.schemas.equipment import PublicEquipmentOut
from app.schemas.ticket import GuestTicketCreate, TicketAssign, TicketCreateResult, TicketOut
from app.models.service_request import ServiceRequest, ServiceRequestAttachment
from app.services.service_requests import event, next_number

public_router = APIRouter(prefix="/api/public/equipment", tags=["guest"])
admin_router = APIRouter(prefix="/api/tickets", tags=["tickets"])


@public_router.get("/{qr_token}", response_model=PublicEquipmentOut)
async def get_public_equipment(qr_token: uuid.UUID, db: AsyncSession = Depends(get_db)):
    row = (
        await db.execute(
            select(Equipment, EquipmentType.name, Site.name, EquipmentAttachment)
            .join(EquipmentType, Equipment.equipment_type_id == EquipmentType.id)
            .join(Site, Site.id == Equipment.site_id)
            .outerjoin(EquipmentAttachment, EquipmentAttachment.equipment_id == Equipment.id)
            .where(Equipment.public_qr_token == qr_token)
        )
    ).first()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Оборудование не найдено")
    equipment, type_name, site_name, photo = row
    return PublicEquipmentOut(
        name=type_name,
        manufacturer=equipment.manufacturer,
        model=equipment.model,
        serial_number=equipment.serial_number,
        status=equipment.status,
        site_name=site_name,
        photo_url=f"/api/public/equipment/{qr_token}/photo" if photo else None,
    )


@public_router.get("/{qr_token}/photo")
async def get_public_equipment_photo(qr_token: uuid.UUID, db: AsyncSession = Depends(get_db)):
    row = (await db.execute(select(EquipmentAttachment).join(Equipment, Equipment.id == EquipmentAttachment.equipment_id).where(
        Equipment.public_qr_token == qr_token))).scalar_one_or_none()
    if not row: raise HTTPException(status.HTTP_404_NOT_FOUND, "Фото не добавлено")
    path = UPLOAD_ROOT / row.file_url
    if not path.is_file(): raise HTTPException(status.HTTP_404_NOT_FOUND, "Фото не найдено")
    from fastapi import Response
    return Response(await run_in_threadpool(path.read_bytes), media_type=row.media_type or "image/jpeg", headers={"Cache-Control": "private, max-age=300"})


@public_router.post("/{qr_token}/tickets", response_model=TicketCreateResult, status_code=status.HTTP_201_CREATED)
async def create_guest_ticket(qr_token: uuid.UUID, payload: GuestTicketCreate, request: Request, db: AsyncSession = Depends(get_db)):
    # Идемпотентность по ключу, который сгенерировала гостевая страница, а не по
    # заголовку — гостевая форма может быть открыта в обычном браузере без
    # контроля над HTTP-заголовками, а поле в теле запроса гарантированно дойдёт.
    _rate_limit(request, qr_token)
    equipment = await db.scalar(
        select(Equipment).where(Equipment.public_qr_token == qr_token).with_for_update()
    )
    if not equipment:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Оборудование не найдено")
    existing = await db.scalar(select(Ticket).where(
        Ticket.organization_id == equipment.organization_id,
        Ticket.idempotency_key == payload.idempotency_key,
    ))
    if existing:
        linked = await db.scalar(select(ServiceRequest).where(ServiceRequest.ticket_id == existing.id))
        return TicketCreateResult(ticket_id=existing.id, service_request_id=linked.id if linked else None, number=linked.number if linked else None, status=existing.status, duplicate=True, active_request=bool(linked and linked.status not in {"completed", "closed", "cancelled"}))
    active = await db.scalar(select(ServiceRequest).where(
        ServiceRequest.organization_id == equipment.organization_id, ServiceRequest.equipment_id == equipment.id,
        ServiceRequest.status.not_in({"completed", "closed", "cancelled"}),
    ).order_by(ServiceRequest.created_at.desc()))
    if active:
        return TicketCreateResult(ticket_id=active.ticket_id, service_request_id=active.id, number=active.number, status=TicketStatus.assigned if active.status == "assigned" else TicketStatus.new, duplicate=True, active_request=True)

    ticket = Ticket(
        organization_id=equipment.organization_id,
        equipment_id=equipment.id,
        severity=payload.severity,
        symptom_tags=payload.symptom_tags,
        comment=payload.comment,
        reporter_name=payload.reporter_name,
        reporter_phone=payload.reporter_phone,
        idempotency_key=payload.idempotency_key,
    )
    db.add(ticket)
    await db.flush()
    request = ServiceRequest(organization_id=equipment.organization_id, number=await next_number(db, equipment.organization_id), ticket_id=ticket.id, equipment_id=equipment.id, status="new", priority="urgent" if payload.severity.value == "not_working" else "planned", title=(payload.comment or ", ".join(payload.symptom_tags) or "Новая заявка")[:255], description=payload.comment)
    db.add(request); await db.flush()
    db.add(event(equipment.organization_id, request.id, None, "request.created", "Заявка создана через QR", {"ticket_id": str(ticket.id)}))

    # Гостевая заявка не должна тихо перезаписать более серьёзный статус
    # (например, "списано") — поднимаем в "требует ремонта" только из рабочего состояния.
    if equipment.status in (EquipmentStatus.working, EquipmentStatus.needs_repair):
        equipment.status = EquipmentStatus.needs_repair
        equipment.version += 1

    await db.commit()
    await db.refresh(ticket)
    return TicketCreateResult(ticket_id=ticket.id, service_request_id=request.id, number=request.number, status=ticket.status, duplicate=False)


@public_router.post("/{qr_token}/requests/{request_id}/attachments", status_code=status.HTTP_201_CREATED)
async def upload_guest_problem_photo(qr_token: uuid.UUID, request_id: uuid.UUID, request: Request, file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    _rate_limit(request, qr_token)
    service_request = await db.scalar(select(ServiceRequest).join(Equipment, Equipment.id == ServiceRequest.equipment_id).where(
        ServiceRequest.id == request_id, Equipment.public_qr_token == qr_token))
    if not service_request: raise HTTPException(status.HTTP_404_NOT_FOUND, "Заявка не найдена")
    count = await db.scalar(select(func.count(ServiceRequestAttachment.id)).where(ServiceRequestAttachment.service_request_id == request_id))
    if count >= 3: raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Можно добавить не более трёх фотографий")
    content = await file.read(MAX_GUEST_PHOTO_BYTES + 1); media_type = file.content_type or ""
    if not content or len(content) > MAX_GUEST_PHOTO_BYTES or not media_type.startswith("image/"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Нужна фотография до 6 МБ")
    attachment_id = uuid.uuid4(); suffix = Path(file.filename or "photo.jpg").suffix.lower()
    if len(suffix) > 10 or not suffix.replace('.', '').isalnum(): suffix = ".jpg"
    relative = Path(str(service_request.organization_id)) / "service-requests" / str(request_id) / f"{attachment_id}{suffix}"
    destination = UPLOAD_ROOT / relative; await run_in_threadpool(destination.parent.mkdir, parents=True, exist_ok=True); await run_in_threadpool(destination.write_bytes, content)
    db.add(ServiceRequestAttachment(id=attachment_id, organization_id=service_request.organization_id, service_request_id=request_id, uploaded_by_user_id=None, kind="problem", file_url=str(relative).replace('\\', '/'), original_name=(file.filename or "Фото проблемы")[:255], media_type=media_type[:100], byte_size=len(content)))
    await db.commit()
    return {"id": str(attachment_id)}


@admin_router.get("", response_model=list[TicketOut])
async def list_tickets(
    db: AsyncSession = Depends(get_db),
    user=Depends(require_roles(UserRole.admin, UserRole.dispatcher)),
):
    rows = (await db.scalars(select(Ticket).where(
        Ticket.organization_id == user.organization_id
    ).order_by(Ticket.created_at.desc()).limit(50))).all()
    return rows


@admin_router.patch("/{ticket_id}/assign", response_model=TicketOut)
async def assign_ticket(
    ticket_id: uuid.UUID,
    payload: TicketAssign,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles(UserRole.admin, UserRole.dispatcher)),
):
    from app.models.core import TicketSeverity, TicketStatus

    ticket = await db.scalar(select(Ticket).where(
        Ticket.id == ticket_id, Ticket.organization_id == user.organization_id
    ))
    technician = await db.scalar(select(User).join(
        OrganizationMembership, OrganizationMembership.user_id == User.id
    ).where(
        User.id == payload.technician_id,
        OrganizationMembership.organization_id == user.organization_id,
        OrganizationMembership.role == UserRole.technician,
        OrganizationMembership.is_active.is_(True),
    ))
    if not ticket or not technician:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Заявка или техник не найдены")
    if not technician.is_active:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Нельзя назначить неактивного техника")

    problem = (ticket.comment or '').strip() or ", ".join(ticket.symptom_tags) or "Не указано"
    task_description = ticket.comment or problem
    task = await db.scalar(select(Task).where(Task.ticket_id == ticket.id))
    request = await db.scalar(select(ServiceRequest).where(ServiceRequest.ticket_id == ticket.id))
    if task:
        task.assigned_to = technician.id
        task.status = TaskStatus.assigned
        # У уже созданного наряда также обновляем текст гостевой проблемы,
        # чтобы техник всегда видел актуальное описание при переназначении.
        task.title = f"Гостевая заявка: {problem}"
        task.description = task_description
    else:
        task = Task(
            organization_id=user.organization_id,
            ticket_id=ticket.id,
            equipment_id=ticket.equipment_id,
            assigned_to=technician.id,
            priority=(TaskPriority.urgent if ticket.severity == TicketSeverity.not_working else TaskPriority.planned),
            status=TaskStatus.assigned,
            title=f"Гостевая заявка: {problem}",
            description=task_description,
            created_by=user.id,
        )
        db.add(task)

    ticket.assigned_technician_id = technician.id
    ticket.status = TicketStatus.assigned
    if request:
        request.task_id = task.id
        request.assigned_technician_id = technician.id
        request.status = "assigned"
        request.priority = task.priority.value
        db.add(event(user.organization_id, request.id, user.id, "technician.assigned", f"Назначен мастер: {technician.full_name}", {"technician_id": str(technician.id)}))
    await db.commit()
    await db.refresh(ticket)
    return ticket
UPLOAD_ROOT = Path("uploads")
MAX_GUEST_PHOTO_BYTES = 6 * 1024 * 1024
_guest_attempts: dict[str, deque[float]] = defaultdict(deque)


def _rate_limit(request: Request, token: uuid.UUID):
    from time import monotonic
    key = f"{request.client.host if request.client else 'unknown'}:{token}"
    now = monotonic(); attempts = _guest_attempts[key]
    while attempts and now - attempts[0] > 60: attempts.popleft()
    if len(attempts) >= 8:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Слишком много попыток. Повторите через минуту.")
    attempts.append(now)
