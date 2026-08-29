import uuid
from io import BytesIO
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import CurrentUser, get_current_user
from app.database import get_db
from app.models.core import Equipment, User, UserRole
from app.models.customer import Client, Site
from app.models.repair import Repair, RepairAttachment, RepairPart
from app.models.warehouse import Part
from app.models.service_request import ServiceRequest
from app.schemas.repair import RepairAttachmentOut
from app.services.service_requests import event
from app.services.client_portal import CLIENT_ROLES, ensure_client_equipment
from app.services.service_act_pdf import build_service_act

router = APIRouter(prefix="/api/repairs", tags=["repairs"])

UPLOAD_ROOT = Path("uploads")
ALLOWED_KINDS = {"before", "after", "signature", "document"}
IMAGE_KINDS = {"before", "after", "signature"}
MAX_UPLOAD_BYTES = 8 * 1024 * 1024


async def _repair_for_user(repair_id: uuid.UUID, db: AsyncSession, user: CurrentUser) -> Repair:
    repair = await db.scalar(select(Repair).where(
        Repair.id == repair_id, Repair.organization_id == user.organization_id,
    ))
    if not repair:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Акт ремонта не найден")
    if user.role in CLIENT_ROLES:
        await ensure_client_equipment(repair.equipment_id, user, db)
    if user.role == UserRole.technician and repair.technician_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Можно работать только со своими актами")
    return repair


def _attachment_out(item: RepairAttachment) -> RepairAttachmentOut:
    return RepairAttachmentOut(
        id=item.id, kind=item.kind, original_name=item.original_name, media_type=item.media_type,
        byte_size=item.byte_size, uploaded_at=item.uploaded_at,
        download_url=f"/api/repairs/attachments/{item.id}",
    )


@router.post("/{repair_id}/attachments", response_model=RepairAttachmentOut, status_code=status.HTTP_201_CREATED)
async def upload_attachment(
    repair_id: uuid.UUID,
    kind: str = Form(...),
    file: UploadFile = File(...),
    client_id: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    repair = await _repair_for_user(repair_id, db, user)
    if kind not in ALLOWED_KINDS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Неизвестный тип вложения")
    client_id = (client_id or "").strip()[:120] or None
    if client_id:
        existing = await db.scalar(select(RepairAttachment).where(
            RepairAttachment.organization_id == user.organization_id,
            RepairAttachment.repair_id == repair.id,
            RepairAttachment.client_id == client_id,
        ))
        if existing:
            return _attachment_out(existing)
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if not content or len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Файл должен быть не больше 8 МБ")
    media_type = file.content_type or "application/octet-stream"
    if kind in IMAGE_KINDS and not media_type.startswith("image/"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Для фото и подписи нужен файл изображения")

    attachment_id = uuid.uuid4()
    suffix = Path(file.filename or "upload").suffix.lower()
    if len(suffix) > 10 or not suffix.replace(".", "").isalnum():
        suffix = ""
    relative_path = Path(str(user.organization_id)) / str(repair.id) / f"{attachment_id}{suffix}"
    destination = UPLOAD_ROOT / relative_path
    await run_in_threadpool(destination.parent.mkdir, parents=True, exist_ok=True)
    await run_in_threadpool(destination.write_bytes, content)
    attachment = RepairAttachment(
        id=attachment_id, organization_id=user.organization_id, repair_id=repair.id,
        file_url=str(relative_path).replace("\\", "/"), kind=kind,
        original_name=(file.filename or "вложение")[:255], media_type=media_type[:100], byte_size=len(content),
        client_id=client_id,
    )
    db.add(attachment)
    request_query = select(ServiceRequest).where(
        ServiceRequest.organization_id == user.organization_id,
        ServiceRequest.equipment_id == repair.equipment_id,
    )
    if repair.task_id:
        request_query = request_query.where(ServiceRequest.task_id == repair.task_id)
    elif repair.ticket_id:
        request_query = request_query.where(ServiceRequest.ticket_id == repair.ticket_id)
    service_request = await db.scalar(request_query.order_by(ServiceRequest.created_at.desc()))
    if service_request:
        db.add(event(user.organization_id, service_request.id, user.id, "photos.added" if kind in IMAGE_KINDS else "document.added", "Добавлены фотографии работ" if kind in IMAGE_KINDS else "Добавлен документ", {"attachment_id": str(attachment.id), "kind": kind}))
    await db.commit()
    await db.refresh(attachment)
    return _attachment_out(attachment)


@router.get("/attachments/{attachment_id}")
async def download_attachment(
    attachment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    item = await db.scalar(select(RepairAttachment).where(
        RepairAttachment.id == attachment_id, RepairAttachment.organization_id == user.organization_id,
    ))
    if not item:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Вложение не найдено")
    await _repair_for_user(item.repair_id, db, user)
    path = UPLOAD_ROOT / item.file_url
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Файл вложения не найден")
    content = await run_in_threadpool(path.read_bytes)
    return Response(content, media_type=item.media_type or "application/octet-stream")


@router.get("/{repair_id}/act.pdf")
async def download_service_act(
    repair_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    repair = await _repair_for_user(repair_id, db, user)
    row = await db.execute(
        select(Equipment, Site, Client, User.full_name)
        .join(Site, Site.id == Equipment.site_id)
        .join(Client, Client.id == Site.client_id)
        .join(User, User.id == repair.technician_id)
        .where(Equipment.id == repair.equipment_id, Equipment.organization_id == user.organization_id)
    )
    equipment, site, client, technician_name = row.one_or_none() or (None, None, None, None)
    if not equipment or not site or not client:
        raise HTTPException(status.HTTP_409_CONFLICT, "Не хватает данных клиента или объекта для сервисного акта")
    parts = (await db.execute(
        select(Part.name, Part.article, RepairPart.quantity)
        .join(RepairPart, RepairPart.part_id == Part.id)
        .where(RepairPart.repair_id == repair.id)
    )).all()
    signature = await db.scalar(
        select(RepairAttachment).where(
            RepairAttachment.repair_id == repair.id,
            RepairAttachment.kind == "signature",
        ).order_by(RepairAttachment.uploaded_at.desc())
    )
    signature_image = None
    if signature:
        signature_path = UPLOAD_ROOT / signature.file_url
        if signature_path.is_file():
            signature_image = await run_in_threadpool(signature_path.read_bytes)
    stream = BytesIO()
    build_service_act(
        stream, organization_name=user.organization.name, repair_id=str(repair.id), client_name=client.legal_name or client.name,
        site_name=site.name, site_address=site.address, equipment_name=equipment.name,
        manufacturer=equipment.manufacturer, model=equipment.model, serial_number=equipment.serial_number,
        technician_name=technician_name or "-", fault_type=repair.fault_type, description=repair.description,
        labor_minutes=repair.labor_minutes, closed_at=repair.closed_at, client_signer_name=repair.client_signer_name,
        client_signed_at=repair.client_signed_at, signature_image=signature_image, parts=[tuple(item) for item in parts],
    )
    stream.seek(0)
    filename = f"service-act-{str(repair.id)[:8]}.pdf"
    return StreamingResponse(stream, media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Cache-Control": "private, no-store",
    })
