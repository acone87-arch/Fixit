"""Regression checks for Fixit 2.0 Issue #4 lifecycle consolidation."""
from pathlib import Path


ROOT = Path("app")


def source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf8")


def test_task_api_is_historical_read_only_and_cannot_change_requests():
    tasks = source("routers/tasks.py")
    assert '@router.get("", response_model=list[TaskOut], deprecated=True)' in tasks
    assert "@router.post" not in tasks
    assert "@router.patch" not in tasks
    assert "@router.delete" not in tasks
    assert "from app.models.service_request" not in tasks


def test_dispatcher_creation_is_canonical_service_request_only():
    requests = source("routers/service_requests.py")
    create_handler = requests.split("async def create_service_request", 1)[1].split("@router.post(\"/{request_id}/attachments\"", 1)[0]
    assert "ServiceRequest(" in create_handler
    assert "Task(" not in create_handler
    assert "task_id=" not in create_handler


def test_guest_qr_creates_linked_request_without_task_and_keeps_idempotency():
    tickets = source("routers/tickets.py")
    guest_handler = tickets.split("async def create_guest_ticket", 1)[1].split("@public_router.post(\"/{qr_token}/requests", 1)[0]
    assert "idempotency_key == payload.idempotency_key" in guest_handler
    assert "ServiceRequest(" in guest_handler
    assert "ticket_id=ticket.id" in guest_handler
    assert "Task(" not in guest_handler


def test_ticket_is_intake_only_not_an_operational_assignment_api():
    tickets = source("routers/tickets.py")
    assert '@admin_router.get("", response_model=list[TicketOut], deprecated=True)' in tickets
    assert "@admin_router.patch" not in tickets
    assert "async def assign_ticket" not in tickets


def test_task_never_mirrors_service_request_workflow():
    workflow = source("services/service_request_workflow.py")
    assert "Task" not in workflow
    assert "task_id" not in workflow


def test_pulse_offline_completion_emits_only_service_request_id():
    pulse = source("static/app.js")
    payload_line = next(line for line in pulse.splitlines() if "const payload = { local_uuid: completionLocalUuid" in line)
    assert "service_request_id: request.id" in payload_line
    assert "task_id:" not in payload_line
    assert "ticket_id:" not in payload_line
    assert "/tasks" not in pulse


def test_legacy_sync_is_accepted_but_cannot_change_task_or_ticket_status():
    sync = source("services/sync_service.py")
    assert "if payload.task_id:" in sync
    assert "task.status =" not in sync
    assert "ticket.status =" not in sync
    assert "transition(db, service_request, sync_actor, \"completed\"" in sync


def test_tech_is_redirect_only_and_legacy_passport_history_stays_available():
    main = source("main.py")
    equipment = source("routers/equipment.py")
    assert "return RedirectResponse(url=\"/#requests\", status_code=307)" in main
    assert 'app.mount("/tech"' not in main
    assert "legacy_tasks" in equipment
    assert "legacy_tickets" in equipment
