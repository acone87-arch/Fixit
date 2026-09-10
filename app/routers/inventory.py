"""Initial inventory uses real Equipment rows, with stable printed QR identities."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.deps import CurrentUser, get_current_user, require_roles
from app.database import get_db
from app.models.core import Equipment, EquipmentInventoryBatch, EquipmentType, UserRole
from app.models.customer import Site
from app.schemas.equipment import EquipmentBatchCreate, EquipmentBatchOut, EquipmentInventoryComplete, EquipmentOut
from app.services.access_policy import ensure_equipment_access
from app.services.inventory_pdf import build_inventory_pdf

router = APIRouter(prefix='/api/equipment-inventory', tags=['equipment'])


async def batch_out(batch, db):
    completed = await db.scalar(select(func.count()).select_from(Equipment).where(
        Equipment.inventory_batch_id == batch.id, Equipment.inventory_pending.is_(False)))
    return EquipmentBatchOut(id=batch.id, site_id=batch.site_id, quantity=batch.quantity,
        completed=completed, created_at=batch.created_at, pdf_url=f'/api/equipment-inventory/batches/{batch.id}/pdf')


@router.post('/batches', response_model=EquipmentBatchOut, status_code=201)
async def create_batch(payload: EquipmentBatchCreate, db: AsyncSession = Depends(get_db),
                       user: CurrentUser = Depends(require_roles(UserRole.admin))):
    # A site lock serializes retries without relying on an in-process mutex.
    site = await db.scalar(select(Site).where(Site.id == payload.site_id,
        Site.organization_id == user.organization_id, Site.is_active.is_(True)).with_for_update())
    if not site:
        raise HTTPException(404, 'Активный объект не найден')
    batch = await db.get(EquipmentInventoryBatch, payload.idempotency_key)
    if batch:
        if (batch.organization_id, batch.site_id, batch.quantity) != (user.organization_id, site.id, payload.quantity):
            raise HTTPException(409, 'Ключ уже использован для другой партии')
        return await batch_out(batch, db)
    batch = EquipmentInventoryBatch(id=payload.idempotency_key, organization_id=user.organization_id,
        site_id=site.id, quantity=payload.quantity, created_by_user_id=user.id)
    db.add(batch)
    try:
        await db.flush()
        db.add_all([Equipment(organization_id=user.organization_id, site_id=site.id,
            name=f'Оборудование №{number}', equipment_type_id=None, serial_number=None,
            inventory_pending=True, inventory_batch_id=batch.id, inventory_number=number,
            location=site.name) for number in range(1, payload.quantity + 1)])
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(409, 'Партия уже создаётся. Повторите запрос с тем же ключом') from exc
    await db.refresh(batch)
    return await batch_out(batch, db)


@router.get('/batches', response_model=list[EquipmentBatchOut])
async def list_batches(site_id: uuid.UUID | None = None, db: AsyncSession = Depends(get_db),
                       user: CurrentUser = Depends(require_roles(UserRole.admin))):
    statement = select(EquipmentInventoryBatch).where(EquipmentInventoryBatch.organization_id == user.organization_id)
    if site_id:
        statement = statement.where(EquipmentInventoryBatch.site_id == site_id)
    batches = (await db.scalars(statement.order_by(EquipmentInventoryBatch.created_at.desc()))).all()
    return [await batch_out(batch, db) for batch in batches]


@router.get('/batches/{batch_id}/pdf')
async def batch_pdf(batch_id: uuid.UUID, db: AsyncSession = Depends(get_db),
                    user: CurrentUser = Depends(require_roles(UserRole.admin))):
    batch = await db.scalar(select(EquipmentInventoryBatch).where(EquipmentInventoryBatch.id == batch_id,
        EquipmentInventoryBatch.organization_id == user.organization_id))
    if not batch:
        raise HTTPException(404, 'Партия не найдена')
    site = await db.get(Site, batch.site_id)
    rows = (await db.scalars(select(Equipment).where(Equipment.inventory_batch_id == batch.id)
        .order_by(Equipment.inventory_number))).all()
    content = await run_in_threadpool(build_inventory_pdf, site.name, str(batch.id),
        [(row.inventory_number, str(row.public_qr_token)) for row in rows], settings.public_app_url.rstrip('/'))
    return Response(content, media_type='application/pdf', headers={
        'Content-Disposition': f'attachment; filename="fixit-qr-{batch.id}.pdf"', 'Cache-Control': 'no-store'})


@router.post('/{equipment_id}/complete', response_model=EquipmentOut)
async def complete_inventory(equipment_id: uuid.UUID, payload: EquipmentInventoryComplete,
                             db: AsyncSession = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    if user.role not in {UserRole.owner, UserRole.admin, UserRole.technician}:
        raise HTTPException(403, 'Заполнять карточку может администратор или назначенный техник')
    equipment = await ensure_equipment_access(equipment_id, user, db)
    await db.refresh(equipment, with_for_update=True)
    await ensure_equipment_access(equipment_id, user, db)
    values = payload.model_dump(exclude={'expected_version'})
    if not equipment.inventory_pending:
        # Lost response retry is a no-op, never an implicit edit by a technician.
        if all(getattr(equipment, key) == value for key, value in values.items()):
            return equipment
        raise HTTPException(409, 'Карточка уже заполнена. Изменения доступны администратору')
    if equipment.version != payload.expected_version:
        raise HTTPException(409, 'Карточка изменилась. Откройте её заново')
    kind = await db.scalar(select(EquipmentType).where(EquipmentType.id == payload.equipment_type_id,
        EquipmentType.organization_id == user.organization_id))
    if not kind:
        raise HTTPException(422, 'Тип оборудования не найден')
    for key, value in values.items():
        setattr(equipment, key, value)
    equipment.name = kind.name
    equipment.inventory_pending = False
    equipment.version += 1
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(409, 'Оборудование с таким серийным номером уже существует') from exc
    await db.refresh(equipment)
    return equipment
