import uuid
from datetime import datetime, timezone

from app.models.core import EquipmentAttachment
from app.schemas.equipment import EquipmentPhotoOut
from app.schemas.service_request import ServiceRequestOut


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
