import asyncio
import uuid
from datetime import datetime, timezone
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, UploadFile

from app.models.core import EquipmentAttachment
from app.models.core import UserRole
from app.models.service_request import ServiceRequestAttachment
from app.models.repair import RepairAttachment
from app.routers import repairs as repairs_router
from app.schemas.equipment import EquipmentPhotoOut
from app.schemas.equipment import EquipmentTimelineEntry
from app.schemas.service_request import ServiceRequestAttachmentOut, ServiceRequestOut


def test_equipment_primary_photo_is_tenant_scoped_and_one_per_equipment():
    columns = EquipmentAttachment.__table__.columns
    assert {"organization_id", "equipment_id", "file_url", "original_name", "media_type", "byte_size", "uploaded_at", "uploaded_by_user_id"} <= set(columns.keys())
    assert any(constraint.name == "uq_equipment_attachment_primary" for constraint in EquipmentAttachment.__table__.constraints)


def test_service_request_read_model_accepts_actor_enriched_history_and_primary_photo():
    now = datetime.now(timezone.utc)
    request = ServiceRequestOut(
        id=uuid.uuid4(), number=11, ticket_id=None, task_id=None, equipment_id=uuid.uuid4(),
        client_name="Клиент", site_name="Объект", equipment_name="Поломоечная машина", serial_number="111",
        description="Не работает", priority="urgent", assigned_technician_id=None,
        assigned_technician_name=None, status="waiting_approval", created_at=now, completed_at=None,
        history=[{"at": now, "type": "approval.rejected", "message": "Согласование отклонено",
                  "details": {"comment": "Стоимость не согласована"},
                  "actor": {"id": uuid.uuid4(), "full_name": "Иванов Алексей", "role": "dispatcher"}}],
        primary_photo={"id": uuid.uuid4(), "download_url": "/api/equipment/x/photo"},
    )
    assert request.history[0]["actor"]["role"] == "dispatcher"
    assert request.primary_photo["download_url"].endswith("/photo")


def test_equipment_photo_contract_keeps_file_out_of_database_payload():
    photo = EquipmentPhotoOut(
        id=uuid.uuid4(), original_name="machine.jpg", media_type="image/jpeg", byte_size=512,
        uploaded_at=datetime.now(timezone.utc), download_url="/api/equipment/example/photo",
    )
    assert "file_url" not in photo.model_dump()
    assert photo.media_type.startswith("image/")


def test_service_request_attachment_is_tenant_scoped_and_has_no_base64_payload():
    columns = set(ServiceRequestAttachment.__table__.columns.keys())
    assert {"id", "organization_id", "service_request_id", "uploaded_by_user_id", "kind", "file_url", "original_name", "media_type", "byte_size", "created_at"} <= columns
    assert "data" not in columns and "base64" not in columns
    attachment = ServiceRequestAttachmentOut(
        id=uuid.uuid4(), kind="approval", original_name="evidence.jpg", media_type="image/jpeg",
        byte_size=123, created_at=datetime.now(timezone.utc),
        download_url="/api/service-requests/attachments/example",
    )
    assert attachment.download_url.startswith("/api/service-requests/attachments/")


def test_repair_attachment_has_durable_client_id_for_idempotent_photo_retry():
    columns = set(RepairAttachment.__table__.columns.keys())
    assert "client_id" in columns
    assert any(constraint.name == "uq_repair_attachment_client" for constraint in RepairAttachment.__table__.constraints)


class _AttachmentSession:
    def __init__(self, scalar_results):
        self.scalar_results = list(scalar_results)
        self.added = []
        self.commits = 0

    async def scalar(self, _statement):
        return self.scalar_results.pop(0)

    def add(self, item):
        self.added.append(item)

    async def commit(self):
        self.commits += 1

    async def refresh(self, item):
        item.uploaded_at = datetime.now(timezone.utc)


def _attachment_user(org, user_id):
    return SimpleNamespace(role=UserRole.technician, organization_id=org, id=user_id)


def _upload_file():
    return UploadFile(filename="after.jpg", file=BytesIO(b"jpeg-bytes"))


def test_assigned_technician_can_upload_completed_repair_photo_without_fleet_access_and_retry_is_idempotent(monkeypatch):
    """Regression for a completed sync followed by a separately uploaded photo.

    The test intentionally has no TechnicianClientAccess: access comes only
    from the repair/request assignment, and remains valid after completion.
    """
    org, technician_id, repair_id, request_id, equipment_id = [uuid.uuid4() for _ in range(5)]
    repair = SimpleNamespace(id=repair_id, organization_id=org, technician_id=technician_id,
                             service_request_id=request_id, equipment_id=equipment_id)
    completed_request = SimpleNamespace(id=request_id)
    session = _AttachmentSession([repair, None, completed_request])
    monkeypatch.setattr(repairs_router, "normalize_image", lambda content: (content, "image/jpeg", ".jpg"))
    async def no_threadpool(_function, *_args, **_kwargs):
        return None
    monkeypatch.setattr(repairs_router, "run_in_threadpool", no_threadpool)

    result = asyncio.run(repairs_router.upload_attachment(
        repair_id, kind="after", file=_upload_file(), client_id="queue-photo-1",
        db=session, user=_attachment_user(org, technician_id),
    ))
    saved = next(item for item in session.added if isinstance(item, RepairAttachment))
    assert result.id == saved.id and saved.client_id == "queue-photo-1"
    assert session.commits == 1

    retry = _AttachmentSession([repair, saved])
    retried = asyncio.run(repairs_router.upload_attachment(
        repair_id, kind="after", file=_upload_file(), client_id="queue-photo-1",
        db=retry, user=_attachment_user(org, technician_id),
    ))
    assert retried.id == saved.id
    assert not retry.added and retry.commits == 0

    other_technician = uuid.uuid4()
    fleetless_equipment = SimpleNamespace(id=equipment_id, organization_id=org, site_id=uuid.uuid4())
    with pytest.raises(HTTPException) as forbidden:
        asyncio.run(repairs_router.upload_attachment(
            repair_id, kind="after", file=_upload_file(), client_id="queue-photo-2",
            db=_AttachmentSession([repair, SimpleNamespace(assigned_technician_id=technician_id), fleetless_equipment, None]),
            user=_attachment_user(org, other_technician),
        ))
    assert forbidden.value.status_code == 403

    with pytest.raises(HTTPException) as cross_tenant:
        asyncio.run(repairs_router.upload_attachment(
            repair_id, kind="after", file=_upload_file(), client_id="queue-photo-3",
            db=_AttachmentSession([None]), user=_attachment_user(uuid.uuid4(), technician_id),
        ))
    assert cross_tenant.value.status_code == 404


def test_equipment_history_contract_can_return_compact_protected_repair_photos():
    entry = EquipmentTimelineEntry(
        id="repair:example", kind="repair.completed", title="Ремонт и сервисный акт",
        photos=[{"id": "attachment-id", "kind": "after", "download_url": "/api/repairs/attachments/attachment-id"}],
    )
    assert entry.photos[0]["download_url"].startswith("/api/repairs/attachments/")
