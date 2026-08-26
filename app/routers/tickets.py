import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_roles
from app.database import get_db
from app.models.core import Equipment, EquipmentStatus, EquipmentType, Task, TaskPriority, TaskStatus, Ticket, User, UserRole
from app.models.organization import OrganizationMembership
from app.schemas.equipment import PublicEquipmentOut
from app.schemas.ticket import GuestTicketCreate, TicketAssign, TicketCreateResult, TicketOut

public_router = APIRouter(prefix="/api/public/equipment", tags=["guest"])
admin_router = APIRouter(prefix="/api/tickets", tags=["tickets"])


@public_router.get("/{qr_token}", response_model=PublicEquipmentOut)
async def get_public_equipment(qr_token: uuid.UUID, db: AsyncSession = Depends(get_db)):
    row = (
        await db.execute(
            select(Equipment, EquipmentType.name)
            .join(EquipmentType, Equipment.equipment_type_id == EquipmentType.id)
            .where(Equipment.public_qr_token == qr_token)
        )
    ).first()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Оборудование не найдено")
    equipment, type_name = row
    return PublicEquipmentOut(
        name=type_name,
        manufacturer=equipment.manufacturer,
        model=equipment.model,
        status=equipment.status,
    )


@public_router.post("/{qr_token}/tickets", response_model=TicketCreateResult, status_code=status.HTTP_201_CREATED)
async def create_guest_ticket(qr_token: uuid.UUID, payload: GuestTicketCreate, db: AsyncSession = Depends(get_db)):
    # Идемпотентность по ключу, который сгенерировала гостевая страница, а не по
    # заголовку — гостевая форма может быть открыта в обычном браузере без
    # контроля над HTTP-заголовками, а поле в теле запроса гарантированно дойдёт.
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
        return TicketCreateResult(ticket_id=existing.id, status=existing.status, duplicate=True)

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

    # Гостевая заявка не должна тихо перезаписать более серьёзный статус
    # (например, "списано") — поднимаем в "требует ремонта" только из рабочего состояния.
    if equipment.status in (EquipmentStatus.working, EquipmentStatus.needs_repair):
        equipment.status = EquipmentStatus.needs_repair
        equipment.version += 1

    await db.commit()
    await db.refresh(ticket)
    return TicketCreateResult(ticket_id=ticket.id, status=ticket.status, duplicate=False)


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
    await db.commit()
    await db.refresh(ticket)
    return ticket
