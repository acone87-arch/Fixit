import asyncio
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.models.core import UserRole
from app.services.access_policy import ACTIVE_ASSIGNED_STATES, ensure_equipment_access, ensure_service_request_access


def run(coro):
    return asyncio.run(coro)


def technician(org, user_id=None):
    return SimpleNamespace(role=UserRole.technician, organization_id=org, id=user_id or uuid.uuid4())


class Session:
    def __init__(self, results):
        self.results = list(results)

    async def scalar(self, _query):
        return self.results.pop(0)


def test_active_assignment_states_include_waiting_approval_for_read_access():
    assert ACTIVE_ASSIGNED_STATES == {"assigned", "on_the_way", "arrived", "in_progress", "waiting_parts", "waiting_approval"}


def test_technician_can_read_only_equipment_with_active_assigned_request():
    org, tech_id, equipment_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    equipment = SimpleNamespace(id=equipment_id, organization_id=org)
    result = run(ensure_equipment_access(equipment_id, technician(org, tech_id), Session([equipment, uuid.uuid4()])))
    assert result is equipment
    with pytest.raises(HTTPException) as denied:
        run(ensure_equipment_access(equipment_id, technician(org, tech_id), Session([equipment, None])))
    assert denied.value.status_code == 403


def test_technician_cannot_read_another_technicians_service_request_or_cross_tenant_request():
    org, own_id = uuid.uuid4(), uuid.uuid4()
    request = SimpleNamespace(organization_id=org, assigned_technician_id=uuid.uuid4(), equipment_id=uuid.uuid4())
    with pytest.raises(HTTPException) as denied:
        run(ensure_service_request_access(request, technician(org, own_id), Session([])))
    assert denied.value.status_code == 404
    request.organization_id = uuid.uuid4()
    with pytest.raises(HTTPException) as cross_tenant:
        run(ensure_service_request_access(request, technician(org, own_id), Session([])))
    assert cross_tenant.value.status_code == 404
