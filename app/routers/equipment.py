import uuid
from io import BytesIO
from pathlib import Path

import qrcode
import qrcode.image.svg
from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.deps import CurrentUser, get_current_user, require_roles
from app.database import get_db
from app.models.core import Equipment, EquipmentAttachment, EquipmentType, Task, Ticket, User, UserRole
from app.models.customer import Client, Site, TechnicianClientAccess
from app.models.repair import Repair, RepairAttachment, RepairPart
from app.models.service_request import ServiceRequest, ServiceRequestAttachment, ServiceRequestEvent
from app.models.warehouse import Part
from app.schemas.equipment import (
    EquipmentActiveRequest,
    EquipmentCreate,
    EquipmentDocumentEntry,
    EquipmentOut,
    EquipmentPhotoOut,
    EquipmentPassport,
    EquipmentTimelineEntry,
    EquipmentUpdate,
    EquipmentTypeCreate,
    EquipmentTypeOut,
    EquipmentServiceHistoryEntry,
)
from app.services.client_portal import CLIENT_ROLES, client_scope, ensure_client_equipment
from app.services.access_policy import ensure_equipment_access
from app.services.media import image_response, normalize_image

router = APIRouter(prefix="/api/equipment", tags=["equipment"])
types_router = APIRouter(prefix="/api/equipment-types", tags=["equipment"])
UPLOAD_ROOT = Path("uploads")
MAX_PHOTO_BYTES = 8 * 1024 * 1024


def _photo_out(item: EquipmentAttachment) -> EquipmentPhotoOut:
    return EquipmentPhotoOut(
        id=item.id, original_name=item.original_name, media_type=item.media_type,
        byte_size=item.byte_size, uploaded_at=item.uploaded_at,
        download_url=f"/api/equipment/{item.equipment_id}/photo",
    )


async def _equipment_for_user(equipment_id: uuid.UUID, db: AsyncSession, user: CurrentUser) -> Equipment:
    return await ensure_equipment_access(equipment_id, user, db)


@types_router.get("", response_model=list[EquipmentTypeOut])
async def list_equipment_types(db: AsyncSession = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    return (await db.scalars(select(EquipmentType).where(
        EquipmentType.organization_id == user.organization_id
    ).order_by(EquipmentType.name))).all()


@types_router.post("", response_model=EquipmentTypeOut, status_code=status.HTTP_201_CREATED)
async def create_equipment_type(
    payload: EquipmentTypeCreate,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_roles(UserRole.admin, UserRole.dispatcher)),
):
    eq_type = EquipmentType(organization_id=user.organization_id, name=payload.name)
    db.add(eq_type)
    await db.commit()
    await db.refresh(eq_type)
    return eq_type


@router.get("", response_model=list[EquipmentOut])
async def list_equipment(client_id: uuid.UUID | None = None, site_id: uuid.UUID | None = None, db: AsyncSession = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    statement = (select(Equipment, EquipmentType.name, EquipmentAttachment)
        .join(EquipmentType, Equipment.equipment_type_id == EquipmentType.id)
        .outerjoin(EquipmentAttachment, (EquipmentAttachment.equipment_id == Equipment.id) & (EquipmentAttachment.organization_id == user.organization_id))
        .where(Equipment.organization_id == user.organization_id)
        .order_by(Equipment.updated_at.desc()))
    # Keep legacy internal list fast, but never expose another client's units
    # when this generic endpoint is used by a client representative.
    if user.role in CLIENT_ROLES:
        client_id, site_ids = await client_scope(user, db)
        statement = (select(Equipment, EquipmentType.name, EquipmentAttachment)
            .join(EquipmentType, Equipment.equipment_type_id == EquipmentType.id)
            .join(Site, Site.id == Equipment.site_id)
            .outerjoin(EquipmentAttachment, (EquipmentAttachment.equipment_id == Equipment.id) & (EquipmentAttachment.organization_id == user.organization_id))
            .where(Equipment.organization_id == user.organization_id, Site.client_id == client_id)
            .order_by(Equipment.updated_at.desc()))
        if site_ids is not None: statement = statement.where(Site.id.in_(site_ids))
    elif user.role == UserRole.technician:
        statement = statement.join(Site, Site.id == Equipment.site_id).where(Site.client_id.in_(select(TechnicianClientAccess.client_id).where(
            TechnicianClientAccess.organization_id == user.organization_id,
            TechnicianClientAccess.technician_id == user.id,
        )))
    if client_id:
        statement = statement.where(Equipment.site_id.in_(select(Site.id).where(
            Site.client_id == client_id, Site.organization_id == user.organization_id
        )))
    if site_id:
        statement = statement.where(Equipment.site_id == site_id)
    rows = (await db.execute(statement)).all()
    # Для старых записей сохраняем историческое поле name в БД, но наружу
    # всегда отдаём тип: все клиенты показывают единое обозначение техники.
    return [EquipmentOut.model_validate(equipment).model_copy(update={
        "name": type_name,
        "primary_photo": _photo_out(photo) if photo else None,
    }) for equipment, type_name, photo in rows]


@router.post("", response_model=EquipmentOut, status_code=status.HTTP_201_CREATED)
async def create_equipment(
    payload: EquipmentCreate,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    if user.role not in {UserRole.owner, UserRole.admin, UserRole.dispatcher, UserRole.client_site_user}:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Недостаточно прав для добавления оборудования")
    equipment_type = await db.scalar(select(EquipmentType).where(
        EquipmentType.id == payload.equipment_type_id,
        EquipmentType.organization_id == user.organization_id,
    ))
    if not equipment_type:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Тип оборудования не найден")
    site = await db.scalar(select(Site).where(
        Site.id == payload.site_id,
        Site.organization_id == user.organization_id,
        Site.is_active.is_(True),
    ))
    if not site:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Активный объект обслуживания не найден")
    if user.role == UserRole.client_site_user:
        scoped_client_id, allowed_site_ids = await client_scope(user, db)
        if site.client_id != scoped_client_id or allowed_site_ids is None or site.id not in allowed_site_ids:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Можно добавлять оборудование только на свой объект")
    # Не принимаем произвольное название из клиента: тип — единственное
    # название единицы оборудования во всех экранах.
    equipment = Equipment(
        **payload.model_dump(exclude={"name", "location"}),
        name=equipment_type.name,
        location=site.name,
        organization_id=user.organization_id,
    )
    db.add(equipment)
    try:
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Оборудование с таким серийным номером уже существует") from exc
    await db.refresh(equipment)
    return equipment


@router.post("/{equipment_id}/photo", response_model=EquipmentPhotoOut, status_code=status.HTTP_201_CREATED)
async def upload_equipment_photo(
    equipment_id: uuid.UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    if user.role not in {UserRole.owner, UserRole.admin, UserRole.dispatcher, UserRole.technician, UserRole.client_site_user}:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Недостаточно прав для фото оборудования")
    equipment = await _equipment_for_user(equipment_id, db, user)
    content = await file.read(MAX_PHOTO_BYTES + 1)
    if not content or len(content) > MAX_PHOTO_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Фото должно быть не больше 8 МБ")
    content, media_type, suffix = normalize_image(content)
    attachment = await db.scalar(select(EquipmentAttachment).where(
        EquipmentAttachment.equipment_id == equipment.id,
        EquipmentAttachment.organization_id == user.organization_id,
    ).with_for_update())
    attachment_id = attachment.id if attachment else uuid.uuid4()
    relative_path = Path(str(user.organization_id)) / "equipment" / str(equipment.id) / f"{attachment_id}{suffix}"
    destination = UPLOAD_ROOT / relative_path
    await run_in_threadpool(destination.parent.mkdir, parents=True, exist_ok=True)
    previous_path = UPLOAD_ROOT / attachment.file_url if attachment else None
    await run_in_threadpool(destination.write_bytes, content)
    if attachment:
        attachment.file_url = str(relative_path).replace("\\", "/")
        attachment.original_name = (file.filename or "фото оборудования")[:255]
        attachment.media_type = media_type[:100]
        attachment.byte_size = len(content)
        attachment.uploaded_by_user_id = user.id
    else:
        attachment = EquipmentAttachment(
            id=attachment_id, organization_id=user.organization_id, equipment_id=equipment.id,
            file_url=str(relative_path).replace("\\", "/"),
            original_name=(file.filename or "фото оборудования")[:255], media_type=media_type[:100],
            byte_size=len(content), uploaded_by_user_id=user.id,
        )
        db.add(attachment)
    await db.commit()
    await db.refresh(attachment)
    if previous_path and previous_path != destination and previous_path.is_file():
        await run_in_threadpool(previous_path.unlink)
    return _photo_out(attachment)


@router.get("/{equipment_id}/photo")
async def download_equipment_photo(
    equipment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    await _equipment_for_user(equipment_id, db, user)
    attachment = await db.scalar(select(EquipmentAttachment).where(
        EquipmentAttachment.equipment_id == equipment_id,
        EquipmentAttachment.organization_id == user.organization_id,
    ))
    if not attachment:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Фотография оборудования не добавлена")
    path = UPLOAD_ROOT / attachment.file_url
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Файл фотографии не найден")
    return image_response(await run_in_threadpool(path.read_bytes), attachment.media_type)


@router.delete("/{equipment_id}/photo", status_code=status.HTTP_204_NO_CONTENT)
async def delete_equipment_photo(
    equipment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_roles(UserRole.admin, UserRole.dispatcher)),
):
    await _equipment_for_user(equipment_id, db, user)
    attachment = await db.scalar(select(EquipmentAttachment).where(
        EquipmentAttachment.equipment_id == equipment_id,
        EquipmentAttachment.organization_id == user.organization_id,
    ))
    if not attachment:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Фотография оборудования не добавлена")
    path = UPLOAD_ROOT / attachment.file_url
    await db.delete(attachment)
    await db.commit()
    if path.is_file():
        await run_in_threadpool(path.unlink)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/by-qr/{qr_token}")
async def get_equipment_by_qr(
    qr_token: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """QR identifies equipment; it never elevates a technician without fleet access."""
    equipment = await db.scalar(select(Equipment).where(
        Equipment.public_qr_token == qr_token, Equipment.organization_id == user.organization_id
    ))
    if not equipment:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Оборудование не найдено")
    if user.role != UserRole.technician:
        return await get_passport(equipment.id, db, user)
    try:
        await ensure_equipment_access(equipment.id, user, db)
    except HTTPException as exc:
        if exc.status_code != status.HTTP_403_FORBIDDEN:
            raise
        return {"id": equipment.id, "name": equipment.name, "manufacturer": equipment.manufacturer,
                "model": equipment.model, "serial_number": equipment.serial_number,
                "status": equipment.status.value, "passport_allowed": False}
    return {"id": equipment.id, "passport_allowed": True}


@router.patch("/{equipment_id}", response_model=EquipmentOut)
async def update_equipment(
    equipment_id: uuid.UUID,
    payload: EquipmentUpdate,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    if user.role not in {UserRole.owner, UserRole.admin, UserRole.dispatcher, UserRole.client_site_user}:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Недостаточно прав для изменения оборудования")
    equipment = await _equipment_for_user(equipment_id, db, user) if user.role == UserRole.client_site_user else await db.scalar(select(Equipment).where(Equipment.id == equipment_id, Equipment.organization_id == user.organization_id))
    if not equipment: raise HTTPException(status.HTTP_404_NOT_FOUND, "Оборудование не найдено")
    changes = payload.model_dump(exclude_unset=True)
    if user.role == UserRole.client_site_user and changes.get("site_id"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Менеджер объекта не может переносить оборудование")
    if changes.get("site_id"):
        site = await db.scalar(select(Site).where(
            Site.id == changes["site_id"],
            Site.organization_id == user.organization_id,
            Site.is_active.is_(True),
        ))
        if not site:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Активный объект обслуживания не найден")
        equipment.location = site.name
    for field, value in changes.items():
        setattr(equipment, field, value)
    equipment.version += 1
    await db.commit()
    await db.refresh(equipment)
    return equipment


@router.delete("/{equipment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_equipment(
    equipment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_roles(UserRole.admin, UserRole.dispatcher)),
):
    """Удаляет ошибочно заведённую единицу оборудования без сервисной истории."""
    equipment = await db.scalar(select(Equipment).where(
        Equipment.id == equipment_id, Equipment.organization_id == user.organization_id
    ))
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
async def get_passport(equipment_id: uuid.UUID, db: AsyncSession = Depends(get_db),
                       user: CurrentUser = Depends(get_current_user)):
    await _equipment_for_user(equipment_id, db, user)
    equipment_row = (await db.execute(
        select(Equipment, EquipmentType.name, Site, Client, EquipmentAttachment)
        .join(EquipmentType, EquipmentType.id == Equipment.equipment_type_id)
        .join(Site, Site.id == Equipment.site_id)
        .join(Client, Client.id == Site.client_id)
        .outerjoin(EquipmentAttachment, (EquipmentAttachment.equipment_id == Equipment.id) & (EquipmentAttachment.organization_id == user.organization_id))
        .where(
            Equipment.id == equipment_id,
            Equipment.organization_id == user.organization_id,
            Site.organization_id == user.organization_id,
            Client.organization_id == user.organization_id,
        )
    )).one_or_none()
    if not equipment_row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Оборудование не найдено")
    equipment, equipment_type_name, site, client, primary_photo = equipment_row

    repair_rows = (await db.execute(
        select(Repair, User.full_name)
        .outerjoin(User, User.id == Repair.technician_id)
        .where(Repair.equipment_id == equipment_id, Repair.organization_id == user.organization_id)
        .order_by(Repair.closed_at.desc(), Repair.created_at.desc())
    )).all()
    repair_ids = [repair.id for repair, _ in repair_rows]
    parts_by_repair: dict[uuid.UUID, list[dict]] = {repair_id: [] for repair_id in repair_ids}
    if repair_ids:
        parts_rows = (await db.execute(
            select(RepairPart.repair_id, Part.name, Part.article, RepairPart.quantity)
            .join(Part, Part.id == RepairPart.part_id)
            .where(RepairPart.repair_id.in_(repair_ids))
        )).all()
        for repair_id, part_name, article, quantity in parts_rows:
            parts_by_repair[repair_id].append({"part_name": part_name, "article": article, "quantity": quantity})
    attachments_by_repair: dict[uuid.UUID, list[RepairAttachment]] = {repair_id: [] for repair_id in repair_ids}
    if repair_ids:
        attachments = (await db.scalars(select(RepairAttachment).where(
            RepairAttachment.organization_id == user.organization_id,
            RepairAttachment.repair_id.in_(repair_ids),
        ).order_by(RepairAttachment.uploaded_at.desc()))).all()
        for attachment in attachments:
            attachments_by_repair.setdefault(attachment.repair_id, []).append(attachment)

    requests = (await db.scalars(select(ServiceRequest).where(
        ServiceRequest.organization_id == user.organization_id,
        ServiceRequest.equipment_id == equipment_id,
    ).order_by(ServiceRequest.created_at.desc()))).all()
    request_ids = [item.id for item in requests]
    cancellation_events: list[ServiceRequestEvent] = []
    if request_ids:
        cancellation_events = (await db.scalars(select(ServiceRequestEvent).where(
            ServiceRequestEvent.organization_id == user.organization_id,
            ServiceRequestEvent.service_request_id.in_(request_ids),
            ServiceRequestEvent.event_type.in_({"request.cancelled", "approval.rejected"}),
        ).order_by(ServiceRequestEvent.created_at.desc()))).all()
    request_attachments_by_request: dict[uuid.UUID, list[ServiceRequestAttachment]] = {item.id: [] for item in requests}
    if request_ids:
        request_attachments = (await db.scalars(select(ServiceRequestAttachment).where(
            ServiceRequestAttachment.organization_id == user.organization_id,
            ServiceRequestAttachment.service_request_id.in_(request_ids),
        ).order_by(ServiceRequestAttachment.created_at.desc()))).all()
        for attachment in request_attachments:
            request_attachments_by_request.setdefault(attachment.service_request_id, []).append(attachment)
    technician_ids = {item.assigned_technician_id for item in requests if item.assigned_technician_id}
    technician_ids.update(repair.technician_id for repair, _ in repair_rows if repair.technician_id)
    technicians = {}
    if technician_ids:
        technicians = {person.id: person.full_name for person in (await db.scalars(
            select(User).where(User.id.in_(technician_ids), User.is_active.is_(True))
        )).all()}

    request_by_id = {item.id: item for item in requests}
    request_by_task = {item.task_id: item for item in requests if item.task_id}
    request_by_ticket = {item.ticket_id: item for item in requests if item.ticket_id}
    repair_by_request = {repair.service_request_id: (repair, technician_name) for repair, technician_name in repair_rows if repair.service_request_id}
    cancellation_reason_by_request = {}
    for item in cancellation_events:
        cancellation_reason_by_request.setdefault(item.service_request_id, (item.details_json or {}).get("reason") or (item.details_json or {}).get("comment") or item.message)

    def repair_photos(repair: Repair) -> list[dict]:
        return [{"id": str(item.id), "kind": item.kind, "media_type": item.media_type,
                 "download_url": f"/api/repairs/attachments/{item.id}"}
                for item in attachments_by_repair.get(repair.id, [])
                if item.kind in {"before", "after"} and (item.media_type or "").startswith("image/")]

    def request_photos(item: ServiceRequest) -> list[dict]:
        return [{"id": str(attachment.id), "kind": attachment.kind, "media_type": attachment.media_type,
                 "download_url": f"/api/service-requests/attachments/{attachment.id}"}
                for attachment in request_attachments_by_request.get(item.id, [])
                if (attachment.media_type or "").startswith("image/")]

    # Canonical entries are request-owned. Events contribute only a short
    # cancellation reason and can never create another history position.
    history: list[EquipmentServiceHistoryEntry] = []
    for item in requests:
        repair_pair = repair_by_request.get(item.id)
        repair, repair_technician = repair_pair if repair_pair else (None, None)
        photos = (repair_photos(repair) if repair else []) + request_photos(item)
        history.append(EquipmentServiceHistoryEntry(
            id=f"request:{item.id}", service_request_id=item.id, service_request_number=item.number,
            status=item.status, occurred_at=item.completed_at or (repair.closed_at if repair else None) or item.created_at,
            completed_at=item.completed_at or (repair.closed_at if repair else None), title=item.title,
            problem=item.description or item.title, work_summary=repair.description if repair else None,
            cancellation_reason=cancellation_reason_by_request.get(item.id) if item.status == "cancelled" else None,
            technician_name=technicians.get(item.assigned_technician_id) or repair_technician,
            parts=parts_by_repair.get(repair.id, []) if repair else [], photos=photos[:3],
            has_service_act=repair is not None,
        ))
    legacy_tasks = (await db.scalars(select(Task).where(
        Task.organization_id == user.organization_id, Task.equipment_id == equipment_id,
    ))).all()
    for task in legacy_tasks:
        if task.id not in request_by_task:
            history.append(EquipmentServiceHistoryEntry(id=f"task:{task.id}", status="legacy",
                occurred_at=task.created_at, title=task.title, problem=task.description, legacy=True))
    legacy_tickets = (await db.scalars(select(Ticket).where(
        Ticket.organization_id == user.organization_id, Ticket.equipment_id == equipment_id,
    ))).all()
    for ticket in legacy_tickets:
        if ticket.id not in request_by_ticket:
            history.append(EquipmentServiceHistoryEntry(id=f"ticket:{ticket.id}", status="legacy",
                occurred_at=ticket.created_at, title="Обращение через QR",
                problem=ticket.comment or ", ".join(ticket.symptom_tags or []), legacy=True))
    # A legacy repair is retained only if no canonical request claims it.
    for repair, technician_name in repair_rows:
        if repair.service_request_id or repair.task_id in request_by_task or repair.ticket_id in request_by_ticket:
            continue
        history.append(EquipmentServiceHistoryEntry(id=f"repair:{repair.id}", status="legacy",
            occurred_at=repair.closed_at or repair.created_at, completed_at=repair.closed_at,
            title=repair.fault_type or "Исторический ремонт", work_summary=repair.description,
            technician_name=technician_name, parts=parts_by_repair.get(repair.id, []),
            photos=repair_photos(repair)[:3], has_service_act=True, legacy=True))
    history.sort(key=lambda item: str(item.occurred_at or ""), reverse=True)

    documents: list[EquipmentDocumentEntry] = []
    for repair, _ in repair_rows:
        documents.append(EquipmentDocumentEntry(
            id=f"act:{repair.id}", kind="service_act", title="Сервисный акт PDF",
            created_at=repair.closed_at or repair.created_at, repair_id=repair.id, media_type="application/pdf",
        ))
        for attachment in attachments_by_repair.get(repair.id, []):
            documents.append(EquipmentDocumentEntry(
                id=f"attachment:{attachment.id}", kind=attachment.kind,
                title=attachment.original_name or "Вложение к сервисному акту",
                created_at=attachment.uploaded_at, repair_id=repair.id, attachment_id=attachment.id,
                media_type=attachment.media_type,
            ))
    documents.sort(key=lambda item: str(item.created_at or ""), reverse=True)
    active_request_model = next((item for item in requests if item.status not in {"completed", "closed", "cancelled"}), None)
    active_request = EquipmentActiveRequest(
        id=active_request_model.id, number=active_request_model.number, status=active_request_model.status,
        priority=active_request_model.priority, title=active_request_model.title,
        description=active_request_model.description,
        assigned_technician_name=technicians.get(active_request_model.assigned_technician_id),
        created_at=active_request_model.created_at,
    ) if active_request_model else None

    data = EquipmentOut.model_validate(equipment).model_dump()
    data["name"] = equipment_type_name or equipment.name
    data["primary_photo"] = _photo_out(primary_photo) if primary_photo else None
    return EquipmentPassport(
        **data, client_name=client.legal_name or client.name, site_name=site.name, site_address=site.address,
        active_request=active_request, timeline=[], documents=documents, history=history,
    )


@router.get("/{equipment_id}/qr", response_class=Response)
async def equipment_qr(equipment_id: uuid.UUID, db: AsyncSession = Depends(get_db),
                       user: CurrentUser = Depends(get_current_user)):
    equipment = await _equipment_for_user(equipment_id, db, user)
    public_url = f"{settings.public_app_url.rstrip('/')}/e/{equipment.public_qr_token}"
    image = qrcode.make(public_url, image_factory=qrcode.image.svg.SvgPathImage, border=2)
    buffer = BytesIO()
    image.save(buffer)
    return Response(buffer.getvalue(), media_type="image/svg+xml")
