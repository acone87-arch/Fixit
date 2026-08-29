from pathlib import Path

from app.models.core import UserRole
from app.models.customer import ClientUserAccess
from app.models.service_request import ServiceRequest


def test_client_roles_and_site_scope_are_explicitly_modelled():
    assert UserRole.client_admin.value == "client_admin"
    assert UserRole.client_site_user.value == "client_site_user"
    columns = set(ClientUserAccess.__table__.columns.keys())
    assert {"organization_id", "user_id", "client_id", "site_id", "is_active"} <= columns


def test_client_scope_is_used_for_equipment_requests_and_protected_media():
    service = Path("app/services/client_portal.py").read_text(encoding="utf8")
    requests = Path("app/routers/service_requests.py").read_text(encoding="utf8")
    repairs = Path("app/routers/repairs.py").read_text(encoding="utf8")
    equipment = Path("app/routers/equipment.py").read_text(encoding="utf8")
    assert "ensure_client_equipment" in service
    assert "elif user.role in CLIENT_ROLES" in requests
    assert "await ensure_client_equipment(repair.equipment_id, user, db)" in repairs
    assert "return await ensure_client_equipment(equipment_id, user, db)" in equipment


def test_guest_qr_surface_stays_opaque_and_never_returns_internal_history():
    tickets = Path("app/routers/tickets.py").read_text(encoding="utf8")
    assert "Equipment.public_qr_token == qr_token" in tickets
    assert "_rate_limit(request, qr_token)" in tickets
    assert "active_request" in tickets
    public_fields = set(__import__("app.schemas.equipment", fromlist=["PublicEquipmentOut"]).PublicEquipmentOut.model_fields)
    assert "history" not in public_fields and "assigned_technician_name" not in public_fields


def test_client_approval_is_targeted_not_a_replacement_for_internal_approval():
    assert "approval_target" in ServiceRequest.__table__.columns
    router = Path("app/routers/client_portal.py").read_text(encoding="utf8")
    assert 'request.approval_target != "client"' in router
    assert '"approval.approved"' in router and '"approval.rejected"' in router
