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


def test_passport_uses_a_prominent_primary_photo_with_an_in_app_viewer():
    source = (ROOT / "static" / "app.js").read_text(encoding="utf8")
    passport = source[source.index("async function openEquipmentPassport"):]
    assert 'id="passport-primary-photo"' in passport
    assert 'id="passport-open-photo"' in passport
    assert "passport-primary-photo-button" in passport
    assert "passport-photo-placeholder" in passport
    assert "openProtectedImage(`/equipment/${passport.id}/photo`" in passport
    assert "canUploadPhoto" in passport and "canDeletePhoto" in passport
    assert "const image = backdrop.querySelector('#passport-primary-photo');" in passport


def test_history_card_keeps_technician_out_of_header_and_omits_identical_problem():
    source = (ROOT / "static" / "app.js").read_text(encoding="utf8")
    assert "normalizeHistoryText(entry.problem) !== normalizeHistoryText(title)" in source
    assert 'class="equipment-history-card-head"' in source
    assert "equipment-history-technician" in source
    assert "compactTechnicianName(entry.technician_name)" in source
    assert "entry.photos.slice(0, 3)" in source
    assert "event.stopPropagation(); openProtectedImage(photoUrl" in source
    assert "!event.target.closest('[data-history-photo-url]')" in source


def test_passport_asset_versions_change_together_for_browser_cache_busting():
    index = (ROOT / "static" / "index.html").read_text(encoding="utf8")
    assert "/static/styles.css?v=20260904-4" in index
    assert "/static/app.js?v=20260904-4" in index


def test_protected_media_urls_do_not_receive_a_second_api_prefix():
    source = (ROOT / "static" / "app.js").read_text(encoding="utf8")
    assert "const url = path.startsWith('/api/') ? path : '/api' + path;" in source
    assert "fetch(url, { headers })" in source
