import uuid
from pathlib import Path

from app.core.deps import CurrentUser
from app.core.security import create_access_token, decode_access_token
from app.models.core import Equipment, EquipmentType, Task, Ticket, User, UserRole
from app.models.customer import Client, Site
from app.models.organization import Organization, OrganizationMembership
from app.models.repair import Repair, RepairAttachment, SyncLog, SyncOperation
from app.models.service_request import ServiceRequest, ServiceRequestEvent
from app.models.warehouse import Part, StockMovement, Warehouse
from app.schemas.service_request import REQUEST_STATUSES
from app.routers.service_requests import TECHNICIAN_TRANSITIONS


def test_access_token_is_bound_to_organization():
    user_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    payload = decode_access_token(create_access_token(user_id, organization_id, UserRole.owner.value))
    assert payload["sub"] == str(user_id)
    assert payload["org"] == str(organization_id)
    assert payload["role"] == UserRole.owner.value


def test_membership_role_is_authoritative():
    organization = Organization(id=uuid.uuid4(), name="Tenant", slug="tenant")
    user = User(id=uuid.uuid4(), full_name="Owner", email="owner@example.com",
                role=UserRole.technician, hashed_password="not-used")
    membership = OrganizationMembership(
        organization_id=organization.id, user_id=user.id, role=UserRole.owner,
    )
    current = CurrentUser(user=user, organization=organization, membership=membership)
    assert current.role == UserRole.owner
    assert current.organization_id == organization.id


def test_every_tenant_root_has_organization_key():
    tenant_models = (
        EquipmentType, Equipment, Task, Ticket, Repair, RepairAttachment,
        SyncLog, SyncOperation, ServiceRequest, ServiceRequestEvent, Warehouse, Part, StockMovement, Client, Site,
    )
    for model in tenant_models:
        assert "organization_id" in model.__table__.columns, model.__name__


def test_business_uniqueness_is_scoped_to_tenant():
    constraints = {
        constraint.name
        for model in (EquipmentType, Equipment, Part, Ticket)
        for constraint in model.__table__.constraints
    }
    assert "uq_equipment_type_org_name" in constraints
    assert "uq_equipment_org_serial" in constraints
    assert "uq_part_org_article" in constraints
    assert "uq_ticket_org_idempotency" in constraints


def test_equipment_belongs_to_service_site():
    assert "site_id" in Equipment.__table__.columns
    constraints = {
        constraint.name
        for model in (Client, Site)
        for constraint in model.__table__.constraints
    }
    assert "uq_client_org_name" in constraints
    assert "uq_site_client_name" in constraints


def test_service_request_workflow_supports_arrival_stage():
    assert {"assigned", "on_the_way", "arrived", "in_progress", "waiting_parts", "waiting_approval", "completed"} <= REQUEST_STATUSES


def test_approval_wait_requires_dispatcher_decision():
    assert "in_progress" not in TECHNICIAN_TRANSITIONS["waiting_approval"]
    assert TECHNICIAN_TRANSITIONS["waiting_parts"] == {"in_progress"}


def test_service_request_opening_uses_one_safe_modal_transition():
    source = (Path(__file__).parents[1] / "app" / "static" / "app.js").read_text(encoding="utf-8")
    assert "async function openServiceRequest(id)" in source
    assert "openServiceRequest(row.dataset.id)" in source
    assert "openServiceRequest(passport.active_request.id)" in source
    assert "closeModal();\n    if (state.me?.role === 'technician')" in source
    assert "openServiceRequestModal" not in source


def test_technician_workspace_does_not_reference_action_inside_its_initializer():
    source = (Path(__file__).parents[1] / "app" / "static" / "app.js").read_text(encoding="utf-8")
    assert "const nextAction = statusAction[request.status];" in source
    assert 'data-status="${nextAction[0]}">${nextAction[1]}' in source
    assert "const action = statusAction[request.status]" not in source
    assert "data-status=\"${action[0]}\">${action[1]}" not in source
