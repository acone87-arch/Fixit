import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select, and_, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import settings
from app.core.deps import CurrentUser, get_current_user
from app.database import get_db
from app.models.core import Equipment, EquipmentType, UserRole
from app.models.customer import Site, TechnicianClientAccess
from app.models.qr_label import QRLabel
from app.models.organization import AuditEvent
from app.schemas.equipment import OptionalSerialNumber
from app.services.access_policy import ensure_equipment_access, STAFF_ROLES
from app.services.client_portal import client_scope, CLIENT_ROLES
from app.services.equipment_label_pdf import EquipmentLabel, build_single_label_pdf

router = APIRouter(prefix="/api/qr-labels", tags=["qr-labels"])

async def accessible_sites(user, db):
    query = select(Site.id).where(Site.organization_id == user.organization_id)
    if user.role == UserRole.technician:
        query = query.where(Site.client_id.in_(select(TechnicianClientAccess.client_id).where(
            TechnicianClientAccess.organization_id == user.organization_id,
            TechnicianClientAccess.technician_id == user.id)))
    elif user.role in CLIENT_ROLES:
        client_id, site_ids = await client_scope(user, db)
        query = query.where(Site.client_id == client_id)
        if site_ids is not None: query = query.where(Site.id.in_(site_ids))
    elif user.role not in STAFF_ROLES:
        raise HTTPException(403, "Нет доступа к маркировке")
    return query

async def get_label(token, user, db, lock=False):
    query = select(QRLabel).where(QRLabel.token == token, QRLabel.organization_id == user.organization_id)
    if lock: query = query.with_for_update()
    label = await db.scalar(query)
    if not label: raise HTTPException(404, "Наклейка не найдена")
    if label.equipment_id:
        await ensure_equipment_access(label.equipment_id, user, db)
    elif label.site_id not in (await db.scalars(await accessible_sites(user, db))).all():
        raise HTTPException(403, "Нет доступа к объекту этой наклейки")
    return label

async def label_out(label, db):
    equipment = await db.get(Equipment, label.equipment_id) if label.equipment_id else None
    site = await db.get(Site, equipment.site_id if equipment else label.site_id)
    return {"token": label.token, "site_id": site.id, "site_name": site.name,
        "batch_id": label.batch_id, "number": label.number,
        "status": "bound" if equipment else "free", "equipment_id": label.equipment_id,
        "equipment_name": (" ".join(filter(None, [equipment.manufacturer, equipment.model])) or equipment.name) if equipment else None,
        "location_details": equipment.location_details if equipment else None,
        "created_at": label.created_at, "bound_at": label.bound_at,
        "can_bind": True}

@router.get("")
async def list_labels(site_id: uuid.UUID | None = None, db: AsyncSession = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    sites = await accessible_sites(user, db)
    if site_id: sites = sites.where(Site.id == site_id)
    accessible_equipment = select(Equipment.id).where(Equipment.organization_id == user.organization_id,
        Equipment.site_id.in_(sites))
    query = select(QRLabel).where(QRLabel.organization_id == user.organization_id,
        or_(and_(QRLabel.equipment_id.is_(None), QRLabel.site_id.in_(sites)),
            QRLabel.equipment_id.in_(accessible_equipment)))
    labels = (await db.scalars(query.order_by(QRLabel.created_at.desc(), QRLabel.number))).all()
    return [await label_out(label, db) for label in labels]

class LabelPrintSelection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    tokens: list[uuid.UUID] = Field(min_length=1, max_length=500)
    free_only: bool = False

@router.post("/print/pdf")
async def print_selected_labels(payload: LabelPrintSelection, db: AsyncSession = Depends(get_db),
                                user: CurrentUser = Depends(get_current_user)):
    from app.services.inventory_pdf import build_equipment_sheet_pdf
    # Lock in a stable order. A label cannot be bound halfway through preparing
    # a free-only sheet. Preserve the user's order in the finished document.
    tokens = list(dict.fromkeys(payload.tokens))
    selected = {}
    for token in sorted(tokens):
        label = await get_label(token, user, db, lock=True)
        if payload.free_only and label.equipment_id is not None:
            raise HTTPException(409, 'Одна из выбранных наклеек уже привязана. Обновите список и выберите свободные заново')
        selected[token] = label
    labels = []
    for token in tokens:
        label = selected[token]
        item = await label_out(label, db)
        labels.append(EquipmentLabel(token=str(token), site_name=item['site_name'],
            equipment_name=item['equipment_name'], inventory_number=label.number,
            batch_id=str(label.batch_id) if label.batch_id else None))
    content = await run_in_threadpool(build_equipment_sheet_pdf, labels,
        settings.public_app_url.rstrip('/'),
        subtitle='Свободные QR-наклейки' if payload.free_only else 'Выбранные QR-наклейки')
    return Response(content, media_type='application/pdf', headers={
        'Cache-Control': 'no-store', 'Content-Disposition': 'inline; filename="fixit-qr-selected.pdf"',
        'X-Label-Count': str(len(labels)), 'X-Page-Count': str((len(labels) + 7) // 8)})


@router.get("/{token}")
async def resolve_label(token: uuid.UUID, db: AsyncSession = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    label = await get_label(token, user, db)
    result = await label_out(label, db)
    result['can_bind'] = user.role in STAFF_ROLES | {UserRole.technician, UserRole.client_site_user}
    return result

@router.get("/{token}/pdf")
async def label_pdf(token: uuid.UUID, db: AsyncSession = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    label = await get_label(token, user, db)
    item = await label_out(label, db)
    content = await run_in_threadpool(build_single_label_pdf, EquipmentLabel(
        token=str(label.token), site_name=item['site_name'], equipment_name=item['equipment_name'],
        inventory_number=label.number, batch_id=str(label.batch_id) if label.batch_id else None), settings.public_app_url.rstrip('/'))
    return Response(content, media_type='application/pdf', headers={'Cache-Control':'no-store',
        'Content-Disposition': f'attachment; filename="fixit-label-{label.token}.pdf"'})

class NewLabelEquipment(OptionalSerialNumber):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    equipment_type_id: int
    manufacturer: str | None = Field(default=None, max_length=255)
    model: str | None = Field(default=None, max_length=255)
    location_details: str | None = Field(default=None, max_length=500)

class BindLabel(BaseModel):
    model_config = ConfigDict(extra='forbid')
    idempotency_key: uuid.UUID
    equipment_id: uuid.UUID | None = None
    new_equipment: NewLabelEquipment | None = None
    @model_validator(mode='after')
    def exactly_one_target(self):
        if (self.equipment_id is None) == (self.new_equipment is None):
            raise ValueError('Выберите оборудование или заполните новую карточку')
        return self

@router.post("/{token}/bind")
async def bind_label(token: uuid.UUID, payload: BindLabel, db: AsyncSession = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    if user.role not in STAFF_ROLES | {UserRole.technician, UserRole.client_site_user}:
        raise HTTPException(403, 'Нет права привязывать наклейки')
    label = await get_label(token, user, db, lock=True)
    if label.equipment_id:
        if label.equipment_id == payload.equipment_id:
            return await label_out(label, db)
        if label.bind_key == payload.idempotency_key and payload.new_equipment:
            equipment = await db.get(Equipment, label.equipment_id)
            if all(getattr(equipment, key) == value for key, value in payload.new_equipment.model_dump().items()):
                return await label_out(label, db)
            raise HTTPException(409, 'Ключ привязки уже использован с другими данными')
        raise HTTPException(409, 'Наклейка уже привязана. Откройте её паспорт; переназначение недоступно')
    site = await db.get(Site, label.site_id)
    if not site.is_active: raise HTTPException(409, 'Объект неактивен')
    if payload.equipment_id:
        equipment = await ensure_equipment_access(payload.equipment_id, user, db)
        await db.refresh(equipment, with_for_update=True)
        await ensure_equipment_access(equipment.id, user, db)
        if equipment.site_id != label.site_id: raise HTTPException(409, 'Выберите оборудование с объекта наклейки')
        if equipment.inventory_pending: raise HTTPException(409, 'Выберите заполненную карточку оборудования')
    else:
        values = payload.new_equipment.model_dump()
        kind = await db.scalar(select(EquipmentType).where(EquipmentType.id == values['equipment_type_id'],
            EquipmentType.organization_id == user.organization_id))
        if not kind: raise HTTPException(422, 'Тип оборудования не найден')
        equipment = Equipment(**values, organization_id=user.organization_id, site_id=site.id,
            name=kind.name, location=site.name, inventory_pending=False)
        # A fresh label may also be the new machine's canonical public URL.
        # Migrated empty legacy rows still reserve their token, so keep an alias there.
        if not label.legacy_equipment_id:
            equipment.public_qr_token = label.token
        db.add(equipment)
        try: await db.flush()
        except IntegrityError as exc:
            await db.rollback()
            raise HTTPException(409, 'Оборудование с таким серийным номером уже существует. Выберите его из списка') from exc
    label.equipment_id = equipment.id
    label.bind_key = payload.idempotency_key
    label.bound_by_user_id = user.id
    label.bound_at = datetime.now(timezone.utc)
    db.add(AuditEvent(organization_id=user.organization_id, actor_user_id=user.id,
        action="qr_label.bound", entity_type="qr_label", entity_id=str(label.token),
        details_json={"equipment_id": str(equipment.id), "site_id": str(site.id),
                      "created_equipment": payload.new_equipment is not None}))
    await db.commit()
    return await label_out(label, db)
