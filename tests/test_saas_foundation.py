import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.core.deps import CurrentUser
from app.core.security import create_access_token, decode_access_token
from app.models.core import Equipment, EquipmentAttachment, EquipmentType, Task, Ticket, User, UserRole
from app.models.customer import Client, Site
from app.models.organization import Organization, OrganizationMembership
from app.models.repair import Repair, RepairAttachment, SyncLog, SyncOperation
from app.models.service_request import ServiceRequest, ServiceRequestAttachment, ServiceRequestEvent
from app.models.warehouse import Part, StockMovement, Warehouse
from app.schemas.service_request import REQUEST_STATUSES, ServiceRequestListItem
from app.services.service_request_workflow import TRANSITIONS


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
        EquipmentType, Equipment, EquipmentAttachment, Task, Ticket, Repair, RepairAttachment,
        SyncLog, SyncOperation, ServiceRequest, ServiceRequestAttachment, ServiceRequestEvent, Warehouse, Part, StockMovement, Client, Site,
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
    assert TRANSITIONS["waiting_approval"] == {"in_progress", "cancelled"}
    assert TRANSITIONS["waiting_parts"] == {"in_progress", "cancelled"}


def test_service_request_opening_uses_one_safe_modal_transition():
    source = (Path(__file__).parents[1] / "app" / "static" / "app.js").read_text(encoding="utf-8")
    assert "async function openServiceRequest(id)" in source
    assert "navigateToServiceRequest(row.dataset.id)" in source
    assert "navigateToServiceRequest(passport.active_request.id)" in source
    assert "closeModal();\n    if (state.me?.role === 'technician')" in source
    assert "openServiceRequestModal" not in source


def test_technician_workspace_does_not_reference_action_inside_its_initializer():
    source = (Path(__file__).parents[1] / "app" / "static" / "app.js").read_text(encoding="utf-8")
    assert "const nextAction = statusAction[request.status];" in source
    assert 'data-status="${nextAction[0]}">${nextAction[1]}' in source
    assert "const action = statusAction[request.status]" not in source
    assert "data-status=\"${action[0]}\">${action[1]}" not in source


def test_service_request_list_has_a_compact_read_model_without_detail_payloads():
    item = ServiceRequestListItem(
        id=uuid.uuid4(), number=1, status="assigned", priority="planned", title="Не работает",
        description="Не включается", client_name="Клиент", site_name="Объект",
        equipment_name="Nilfisk SC450", equipment_type="Поломоечная машина",
        manufacturer="Nilfisk", model="SC450", serial_number="111",
        assigned_technician_id=None, assigned_technician_name=None,
        created_at=datetime.now(timezone.utc),
    )
    assert {"history", "attachments", "request_attachments", "parts_used", "outcome", "repair_id"}.isdisjoint(item.model_dump())


def test_service_request_list_executes_one_joined_query_not_detail_serializer_per_row():
    source = (Path(__file__).parents[1] / "app" / "routers" / "service_requests.py").read_text(encoding="utf-8")
    list_section = source.split("async def list_requests", 1)[1].split('@router.get("/{request_id}"', 1)[0]
    assert "await serialize" not in list_section
    assert list_section.count("await db.execute(query)") == 1
    assert "select(ServiceRequest, Equipment, EquipmentType.name, Site, Client, User.full_name)" in list_section
    assert "Repair" not in list_section
    assert "ServiceRequestEvent" not in list_section


def test_staff_service_request_detail_is_a_route_screen_with_back_navigation():
    source = (Path(__file__).parents[1] / "app" / "static" / "app.js").read_text(encoding="utf-8")
    detail_section = source.split("function renderServiceRequestDetail", 1)[1].split("async function openTechnicianRequestWorkspace", 1)[0]
    assert "content.innerHTML" in detail_section
    assert "service-request-screen" in detail_section
    assert "request-detail-back" in detail_section
    assert "location.hash = 'requests'" in detail_section
    assert "openModal(" not in detail_section


def test_request_photo_lightbox_and_approval_dialog_do_not_replace_detail_screen():
    source = (Path(__file__).parents[1] / "app" / "static" / "app.js").read_text(encoding="utf-8")
    image_section = source.split("async function openProtectedImage", 1)[1].split("function openApprovalDialog", 1)[0]
    dialog_section = source.split("function openApprovalDialog", 1)[1].split("async function uploadEquipmentPhoto", 1)[0]
    assert "image-lightbox" in image_section and "openModal(" not in image_section
    assert "activeImageLightbox" in image_section and "URL.revokeObjectURL" in source
    assert "pulse-dialog-backdrop" in dialog_section
    assert "prompt(" not in dialog_section
    assert "await openServiceRequest(item.id);" in source


def test_task_is_hidden_from_pulse_navigation_while_service_request_creation_stays_available():
    source = (Path(__file__).parents[1] / "app" / "static" / "app.js").read_text(encoding="utf-8")
    navigation = source.split("const NAV =", 1)[1].split("function renderNav", 1)[0]
    assert "'tasks', 'Наряды'" not in navigation
    assert "'tasks', 'Мои наряды'" not in navigation
    assert "api('/service-requests', { method: 'POST'" in source
    assert "location.hash = 'requests'" in source


def test_pulse_uses_shared_offline_repair_queue_and_legacy_tech_redirects():
    root = Path(__file__).parents[1]
    source = (root / "app" / "static" / "app.js").read_text(encoding="utf-8")
    engine = (root / "app" / "static" / "offline" / "engine.js").read_text(encoding="utf-8")
    main = (root / "app" / "main.py").read_text(encoding="utf-8")
    assert "FixitOffline.enqueueRepair" in source
    assert "FixitOffline.sync" in source
    assert "pendingRepairs" in engine and "pendingAttachments" in engine
    assert "fixit-tech-db" in engine
    assert "fixit-sync-repairs" in engine
    assert 'RedirectResponse(url="/#requests", status_code=307)' in main


def test_technician_workspace_renders_saved_repair_images_as_thumbnails():
    source = (Path(__file__).parents[1] / "app" / "static" / "app.js").read_text(encoding="utf-8")
    assert "tech-request-saved-photo-grid" in source
    assert "data-repair-photo" in source
    assert "apiBlob(`/repairs/attachments/${attachment.id}`)" in source
    assert "openProtectedImage(`/repairs/attachments/${attachment.id}`" in source
