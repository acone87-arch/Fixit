import asyncio
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.models.core import UserRole
from app.services.access_policy import ACTIVE_ASSIGNED_STATES, ensure_equipment_access, ensure_repair_access, ensure_service_request_access


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


def test_technician_can_read_equipment_for_an_explicitly_assigned_service_client():
    org, tech_id, equipment_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    equipment = SimpleNamespace(id=equipment_id, organization_id=org, site_id=uuid.uuid4())
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


def test_fleet_access_does_not_change_service_request_workflow_ownership():
    org, technician_id = uuid.uuid4(), uuid.uuid4()
    own_request = SimpleNamespace(
        organization_id=org,
        assigned_technician_id=technician_id,
        equipment_id=uuid.uuid4(),
    )
    assert run(ensure_service_request_access(own_request, technician(org, technician_id), Session([]))) is own_request
    unassigned_request = SimpleNamespace(
        organization_id=org,
        assigned_technician_id=None,
        equipment_id=uuid.uuid4(),
    )
    with pytest.raises(HTTPException) as denied:
        run(ensure_service_request_access(unassigned_request, technician(org, technician_id), Session([])))
    assert denied.value.status_code == 404


def test_own_completed_repair_allows_attachment_without_fleet_access():
    org, technician_id = uuid.uuid4(), uuid.uuid4()
    repair = SimpleNamespace(
        organization_id=org, equipment_id=uuid.uuid4(), technician_id=technician_id,
        service_request_id=uuid.uuid4(),
    )
    # Regression for the offline-photo failure: before the fix this fell through
    # to ensure_equipment_access and returned 403 without TechnicianClientAccess.
    assert run(ensure_repair_access(repair, technician(org, technician_id), Session([]))) is repair


def test_assigned_completed_canonical_request_allows_its_repair_but_not_another_technician():
    org, assigned_id, other_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    repair = SimpleNamespace(
        organization_id=org, equipment_id=uuid.uuid4(), technician_id=uuid.uuid4(),
        service_request_id=uuid.uuid4(),
    )
    completed_request = SimpleNamespace(organization_id=org, assigned_technician_id=assigned_id, status="completed")
    assert run(ensure_repair_access(repair, technician(org, assigned_id), Session([completed_request]))) is repair

    equipment = SimpleNamespace(id=repair.equipment_id, organization_id=org, site_id=uuid.uuid4())
    with pytest.raises(HTTPException) as denied:
        run(ensure_repair_access(repair, technician(org, other_id), Session([completed_request, equipment, None])))
    assert denied.value.status_code == 403


def test_repair_access_never_crosses_organization_even_for_own_repair():
    org, technician_id = uuid.uuid4(), uuid.uuid4()
    repair = SimpleNamespace(
        organization_id=uuid.uuid4(), equipment_id=uuid.uuid4(), technician_id=technician_id,
        service_request_id=uuid.uuid4(),
    )
    with pytest.raises(HTTPException) as denied:
        run(ensure_repair_access(repair, technician(org, technician_id), Session([])))
    assert denied.value.status_code == 404
