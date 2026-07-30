import uuid
from io import BytesIO

import qrcode
import qrcode.image.svg
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.deps import get_current_user, require_roles
from app.database import get_db
from app.models.core import Equipment, EquipmentType, Task, Ticket, UserRole
from app.models.repair import Repair
from app.schemas.equipment import (
    EquipmentCreate,
    EquipmentOut,
    EquipmentPassport,
    EquipmentUpdate,
    EquipmentTypeCreate,
    EquipmentTypeOut,
    RepairHistoryEntry,
)

router = APIRouter(prefix="/api/equipment", tags=["equipment"])
types_router = APIRouter(prefix="/api/equipment-types", tags=["equipment"])


@types_router.get("", response_model=list[EquipmentTypeOut])
async def list_equipment_types(db: AsyncSession = Depends(get_db)):
    return (await db.scalars(select(EquipmentType).order_by(EquipmentType.name))).all()


@types_router.post("", response_model=EquipmentTypeOut, status_code=status.HTTP_201_CREATED)
async def create_equipment_type(
    payload: EquipmentTypeCreate,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_roles(UserRole.admin, UserRole.dispatcher)),
):
    eq_type = EquipmentType(name=payload.name)
    db.add(eq_type)
    await db.commit()
    await db.refresh(eq_type)
    return eq_type


@router.get("", response_model=list[EquipmentOut])
async def list_equipment(db: AsyncSession = Depends(get_db)):
    rows = (await db.scalars(select(Equipment).order_by(Equipment.updated_at.desc()))).all()
    return rows


@router.post("", response_model=EquipmentOut, status_code=status.HTTP_201_CREATED)
async def create_equipment(
    payload: EquipmentCreate,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_roles(UserRole.admin, UserRole.dispatcher)),
):
    equipment = Equipment(**payload.model_dump())
    db.add(equipment)
    try:
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Оборудование с таким серийным номером уже существует") from exc
    await db.refresh(equipment)
    return equipment


@router.get("/by-qr/{qr_token}", response_model=EquipmentPassport)
async def get_equipment_by_qr(
    qr_token: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    """Для мобильного приложения техника — в отличие от /api/public/equipment/{qr_token}
    (гостевой, без авторизации, отдаёт минимум полей), тут нужен именно внутренний id,
    чтобы дальше открыть полный паспорт и создать акт ремонта."""
    equipment = await db.scalar(select(Equipment).where(Equipment.public_qr_token == qr_token))
    if not equipment:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Оборудование не найдено")
    return await get_passport(equipment.id, db)


@router.patch("/{equipment_id}", response_model=EquipmentOut)
async def update_equipment(
    equipment_id: uuid.UUID,
    payload: EquipmentUpdate,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_roles(UserRole.admin, UserRole.dispatcher)),
):
    equipment = await db.get(Equipment, equipment_id)
    if not equipment:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Оборудование не найдено")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(equipment, field, value)
    equipment.version += 1
    await db.commit()
    await db.refresh(equipment)
    return equipment


@router.delete("/{equipment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_equipment(
    equipment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_roles(UserRole.admin, UserRole.dispatcher)),
):
    """Удаляет ошибочно заведённую единицу оборудования без сервисной истории."""
    equipment = await db.get(Equipment, equipment_id)
    if not equipment:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Оборудование не найдено")

    # Паспорт с реальными заявками/ремонтами — часть аудита. Его нельзя удалить
    # вместе с историей одной кнопкой, поэтому для ошибочной записи разрешаем
    # удаление только до начала эксплуатации.
    has_task = await db.scalar(select(Task.id).where(Task.equipment_id == equipment_id).limit(1))
    has_ticket = await db.scalar(select(Ticket.id).where(Ticket.equipment_id == equipment_id).limit(1))
    has_repair = await db.scalar(select(Repair.id).where(Repair.equipment_id == equipment_id).limit(1))
    if has_task or has_ticket or has_repair:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Нельзя удалить оборудование с нарядами, заявками или историей ремонтов",
        )

    await db.delete(equipment)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{equipment_id}/passport", response_model=EquipmentPassport)
async def get_passport(equipment_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    equipment = await db.get(Equipment, equipment_id)
    if not equipment:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Оборудование не найдено")

    from app.models.core import User
    from app.models.repair import RepairPart
    from app.models.warehouse import Part

    rows = (
        await db.execute(
            select(Repair, User.full_name)
            .join(User, User.id == Repair.technician_id)
            .where(Repair.equipment_id == equipment_id)
            .order_by(Repair.closed_at.desc())
        )
    ).all()

    history: list[RepairHistoryEntry] = []
    for repair, technician_name in rows:
        parts_rows = (
            await db.execute(
                select(Part.name, RepairPart.quantity)
                .join(RepairPart, RepairPart.part_id == Part.id)
                .where(RepairPart.repair_id == repair.id)
            )
        ).all()
        history.append(
            RepairHistoryEntry(
                repair_id=repair.id,
                closed_at=repair.closed_at,
                technician_name=technician_name,
                fault_type=repair.fault_type,
                description=repair.description,
                parts_used=[{"part_name": name, "quantity": qty} for name, qty in parts_rows],
            )
        )

    return EquipmentPassport(**EquipmentOut.model_validate(equipment).model_dump(), history=history)


@router.get("/{equipment_id}/qr", response_class=Response)
async def equipment_qr(equipment_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    equipment = await db.get(Equipment, equipment_id)
    if not equipment:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Оборудование не найдено")
    public_url = f"{settings.public_app_url.rstrip('/')}/e/{equipment.public_qr_token}"
    image = qrcode.make(public_url, image_factory=qrcode.image.svg.SvgPathImage, border=2)
    buffer = BytesIO()
    image.save(buffer)
    return Response(buffer.getvalue(), media_type="image/svg+xml")
