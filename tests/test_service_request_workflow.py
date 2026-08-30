import asyncio
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.models.core import UserRole
from app.services.service_request_workflow import ACTIVE, LEGACY, TERMINAL, WAITING, decide_approval, transition


def actor(role, organization_id, user_id=None):
    return SimpleNamespace(id=user_id or uuid.uuid4(), organization_id=organization_id, role=role)


def request(state="new", organization_id=None, technician_id=None, approval_target="internal"):
    return SimpleNamespace(id=uuid.uuid4(), organization_id=organization_id or uuid.uuid4(), status=state,
                           equipment_id=uuid.uuid4(), assigned_technician_id=technician_id,
                           approval_target=approval_target, task_id=None, completed_at=None)


class Session:
    def __init__(self, technician=None):
        self.technician = technician
        self.events = []

    async def scalar(self, _query):
        return self.technician

    def add(self, item):
        self.events.append(item)


def run(coro):
    return asyncio.run(coro)


def test_state_classification_is_canonical_and_closed_is_legacy_only():
    assert ACTIVE == {"new", "assigned", "on_the_way", "arrived", "in_progress"}
    assert WAITING == {"waiting_parts", "waiting_approval"}
    assert TERMINAL == {"completed", "cancelled"}
    assert LEGACY == {"closed"}


def test_dispatcher_assigns_only_new_request_and_emits_one_semantic_event():
    org, technician_id = uuid.uuid4(), uuid.uuid4()
    item, db = request(organization_id=org), Session(SimpleNamespace(id=technician_id))
    run(transition(db, item, actor(UserRole.dispatcher, org), "assigned", technician_id=technician_id))
    assert (item.status, item.assigned_technician_id) == ("assigned", technician_id)
    assert [event.event_type for event in db.events] == ["technician.assigned"]
    with pytest.raises(HTTPException) as error:
        run(transition(db, item, actor(UserRole.technician, org, technician_id), "in_progress"))
    assert error.value.status_code == 409


def test_assigned_technician_must_follow_order_and_can_resume_parts_only():
    org, technician_id = uuid.uuid4(), uuid.uuid4()
    item, db = request("assigned", org, technician_id), Session()
    tech = actor(UserRole.technician, org, technician_id)
    for target in ("on_the_way", "in_progress", "waiting_parts", "in_progress"):
        run(transition(db, item, tech, target))
    assert item.status == "in_progress"
    assert [entry.event_type for entry in db.events] == ["technician.on_the_way", "work.started", "request.waiting_parts", "work.resumed"]
    with pytest.raises(HTTPException):
        run(transition(db, item, actor(UserRole.technician, org), "waiting_parts"))


def test_arrived_is_readable_legacy_state_but_new_flow_cannot_create_it():
    org, technician_id = uuid.uuid4(), uuid.uuid4()
    tech = actor(UserRole.technician, org, technician_id)
    fresh, db = request("on_the_way", org, technician_id), Session()
    with pytest.raises(HTTPException) as error:
        run(transition(db, fresh, tech, "arrived"))
    assert error.value.status_code == 409
    legacy, db = request("arrived", org, technician_id), Session()
    run(transition(db, legacy, tech, "in_progress"))
    assert legacy.status == "in_progress"


def test_approval_ownership_and_rejection_are_enforced():
    org, technician_id = uuid.uuid4(), uuid.uuid4()
    tech = actor(UserRole.technician, org, technician_id)
    item, db = request("in_progress", org, technician_id), Session()
    run(transition(db, item, tech, "waiting_approval", approval_target="internal"))
    with pytest.raises(HTTPException):
        run(decide_approval(db, item, actor(UserRole.client_admin, org), True, None))
    run(decide_approval(db, item, actor(UserRole.dispatcher, org), True, None))
    assert item.status == "in_progress"
    item.status, item.approval_target = "waiting_approval", "client"
    with pytest.raises(HTTPException):
        run(decide_approval(db, item, actor(UserRole.dispatcher, org), True, None))
    run(decide_approval(db, item, actor(UserRole.client_site_user, org), False, "Не согласовано"))
    assert item.status == "cancelled"
    assert db.events[-1].event_type == "approval.rejected"


def test_completion_requires_sync_repair_and_terminal_requests_do_not_reopen():
    org, technician_id = uuid.uuid4(), uuid.uuid4()
    item, db = request("in_progress", org, technician_id), Session()
    tech = actor(UserRole.technician, org, technician_id)
    with pytest.raises(HTTPException):
        run(transition(db, item, tech, "completed"))
    repair_id = uuid.uuid4()
    run(transition(db, item, tech, "completed", completion_repair_id=repair_id))
    assert item.status == "completed" and db.events[-1].event_type == "repair.completed"
    with pytest.raises(HTTPException):
        run(transition(db, item, tech, "on_the_way"))


def test_cancellation_requires_dispatcher_reason_and_not_approval_queue():
    org = uuid.uuid4()
    item, db = request("new", org), Session()
    dispatcher = actor(UserRole.dispatcher, org)
    with pytest.raises(HTTPException):
        run(transition(db, item, dispatcher, "cancelled"))
    run(transition(db, item, dispatcher, "cancelled", reason="Дубликат"))
    assert item.status == "cancelled" and db.events[-1].event_type == "request.cancelled"


def test_stale_and_cross_tenant_transitions_fail_after_an_incompatible_change():
    org, technician_id = uuid.uuid4(), uuid.uuid4()
    item, db = request("assigned", org, technician_id), Session()
    run(transition(db, item, actor(UserRole.dispatcher, org), "cancelled", reason="Отменено диспетчером"))
    with pytest.raises(HTTPException) as stale:
        run(transition(db, item, actor(UserRole.technician, org, technician_id), "on_the_way"))
    assert stale.value.status_code == 409
    other = request("new", org)
    with pytest.raises(HTTPException) as tenant:
        run(transition(db, other, actor(UserRole.dispatcher, uuid.uuid4()), "cancelled", reason="Нет доступа"))
    assert tenant.value.status_code == 404
