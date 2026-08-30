"""Regression contract for the compact Equipment Passport service history."""
from datetime import datetime, timezone
from pathlib import Path
import uuid

from app.schemas.equipment import EquipmentServiceHistoryEntry


ROOT = Path("app")


def test_service_history_entry_is_request_owned_and_carries_compact_summary():
    entry = EquipmentServiceHistoryEntry(
        id="request:example", service_request_id=uuid.uuid4(), service_request_number=16,
        status="completed", occurred_at=datetime.now(timezone.utc), title="Не собирает воду",
        problem="Не собирает воду", work_summary="Диагностика, замена клапана",
        parts=[{"part_name": "Клапан", "quantity": 1}],
        photos=[{"id": "photo", "download_url": "/api/repairs/attachments/photo"}],
        has_service_act=True,
    )
    assert entry.service_request_number == 16
    assert entry.problem and entry.work_summary and entry.parts and entry.photos


def test_passport_groups_canonical_requests_and_keeps_events_out_of_history_positions():
    source = (ROOT / "routers" / "equipment.py").read_text(encoding="utf8")
    assert "for item in requests:" in source
    assert "id=f\"request:{item.id}\"" in source
    assert "repair_by_request" in source
    assert "repair.service_request_id" in source
    assert "cancellation_events" in source
    assert "timeline=[]" in source
    assert "request-event:" not in source


def test_passport_uses_batched_related_data_and_protected_media_references():
    source = (ROOT / "routers" / "equipment.py").read_text(encoding="utf8")
    assert "RepairPart.repair_id.in_(repair_ids)" in source
    assert "RepairAttachment.repair_id.in_(repair_ids)" in source
    assert "ServiceRequestAttachment.service_request_id.in_(request_ids)" in source
    assert '"/api/repairs/attachments/{item.id}"' in source
    assert '"/api/service-requests/attachments/{attachment.id}"' in source


def test_legacy_records_are_not_duplicated_when_mapped_to_a_canonical_request():
    source = (ROOT / "routers" / "equipment.py").read_text(encoding="utf8")
    assert "if task.id not in request_by_task" in source
    assert "if ticket.id not in request_by_ticket" in source
    assert "if repair.service_request_id or repair.task_id in request_by_task or repair.ticket_id in request_by_ticket" in source


def test_history_cards_are_whole_request_navigation_targets_with_thumbnail_urls():
    source = (ROOT / "static" / "app.js").read_text(encoding="utf8")
    assert "data-history-request" in source
    assert "navigateToServiceRequest(card.dataset.historyRequest)" in source
    assert "data-history-photo-url" in source
    assert "open-request-btn" not in source[source.index("async function openEquipmentPassport"):]
    assert "Ремонтов ещё не было." in source
