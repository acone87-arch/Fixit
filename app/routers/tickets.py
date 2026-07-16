import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_roles
from app.database import get_db
from app.models.core import Equipment, EquipmentStatus, Ticket, UserRole
from app.schemas.equipment import PublicEquipmentOut
from app.schemas.ticket import GuestTicketCreate, TicketAssign, TicketCreateResult, TicketOut

public_router = APIRouter(prefix="/api/public/equipment", tags=["guest"])
admin_router = APIRouter(prefix="/api/tickets", tags=["tickets"])


@public_router.get("/{qr_token}", response_model=PublicEquipmentOut)
async def get_public_equipment(qr_token: uuid.UUID, db: AsyncSession = Depends(get_db)):
    equipment = await db.scalar(select(Equipment).where(Equipment.public_qr_token == qr_token))
    if not equipment:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Оборудование не найдено")
    return equipment


@public_router.post("/{qr_token}/tickets", response_model=TicketCreateResult, status_code=status.HTTP_201_CREATED)
async def create_guest_ticket(qr_token: uuid.UUID, payload: GuestTicketCreate, db: AsyncSession = Depends(get_db)):
    # Идемпотентность по ключу, который сгенерировала гостевая страница, а не по
    # заголовку — гостевая форма может быть открыта в обычном браузере без
    # контроля над HTTP-заголовками, а поле в теле запроса гарантированно дойдёт.
    existing = await db.scalar(select(Ticket).where(Ticket.idempotency_key == payload.idempotency_key))
    if existing:
        return TicketCreateResult(ticket_id=existing.id, status=existing.status, duplicate=True)

    equipment = await db.scalar(
        select(Equipment).where(Equipment.public_qr_token == qr_token).with_for_update()
    )
    if not equipment:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Оборудование не найдено")

    ticket = Ticket(
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
    _user=Depends(require_roles(UserRole.admin, UserRole.dispatcher)),
):
    rows = (await db.scalars(select(Ticket).order_by(Ticket.created_at.desc()).limit(50))).all()
    return rows


@admin_router.patch("/{ticket_id}/assign", response_model=TicketOut)
async def assign_ticket(
    ticket_id: uuid.UUID,
    payload: TicketAssign,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_roles(UserRole.admin, UserRole.dispatcher)),
):
    from app.models.core import TicketStatus, User

    ticket = await db.get(Ticket, ticket_id)
    technician = await db.get(User, payload.technician_id)
    if not ticket or not technician or technician.role != UserRole.technician:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Заявка или техник не найдены")
    ticket.assigned_technician_id = technician.id
    ticket.status = TicketStatus.assigned
    await db.commit()
    await db.refresh(ticket)
    return ticket
