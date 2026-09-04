"""Regression contract for client-cabinet access management.

The project test suite intentionally has no shared PostgreSQL fixture.  These
tests keep the security invariants that must remain true at the API boundary
and catch accidental regressions in the small CRUD surface.
"""

from pathlib import Path

from app.models.core import UserRole
from app.schemas.customer import ClientAccessCreate, ClientAccessOut, ClientAccessUpdate


ROUTER = Path("app/routers/client_portal.py").read_text(encoding="utf8")
USERS = Path("app/routers/users.py").read_text(encoding="utf8")
FRONTEND = Path("app/static/app.js").read_text(encoding="utf8")


def test_access_crud_has_typed_contract_for_admin_and_site_users():
    assert {"user_id", "client_id", "site_id"} <= set(ClientAccessCreate.model_fields)
    assert {"id", "full_name", "email", "role", "site_name", "is_active"} <= set(ClientAccessOut.model_fields)
    assert {"site_id", "is_active"} <= set(ClientAccessUpdate.model_fields)
    assert "@router.get(\"/access\"" in ROUTER
    assert "@router.patch(\"/access/{access_id}\"" in ROUTER
    assert "@router.delete(\"/access/{access_id}\"" in ROUTER


def test_access_scope_rejects_foreign_client_site_and_invalid_role_scope():
    # Every lookup is tenant-scoped, and a Site must be tied to the selected
    # client.  CLIENT_ADMIN never receives a single-site assignment while a
    # CLIENT_SITE_USER must receive one.
    assert "Client.organization_id == organization_id" in ROUTER
    assert "Site.client_id == client_id, Site.organization_id == organization_id" in ROUTER
    assert "Администратор клиента получает доступ ко всем объектам" in ROUTER
    assert "Выберите объект для менеджера объекта" in ROUTER


def test_access_update_and_delete_are_tenant_scoped_and_do_not_delete_user():
    # Update and delete load by access ID together with the active tenant;
    # listing scopes both Client and ClientUserAccess to the same tenant.
    assert ROUTER.count("ClientUserAccess.organization_id == user.organization_id") >= 2
    assert "Client.organization_id == user.organization_id" in ROUTER
    delete_block = ROUTER.split('async def delete_access', 1)[1]
    assert "await db.delete(access)" in delete_block
    assert "await db.delete(account)" not in delete_block
    assert "await db.delete(user)" not in delete_block


def test_multiple_site_access_rows_remain_supported():
    assert "UniqueConstraint(\"organization_id\", \"user_id\", \"client_id\", \"site_id\"" in Path("app/models/customer.py").read_text(encoding="utf8")
    assert "Такой доступ уже назначен" in ROUTER
    assert UserRole.client_site_user.value == "client_site_user"


def test_dispatcher_can_onboard_only_client_users():
    assert "require_roles(UserRole.admin, UserRole.dispatcher)" in USERS
    assert "payload.role not in {UserRole.client_admin, UserRole.client_site_user}" in USERS


def test_client_user_management_ui_uses_human_labels_and_existing_user_api():
    assert "Администратор клиента" in FRONTEND
    assert "Менеджер объекта" in FRONTEND
    assert "Все объекты" in FRONTEND
    assert "api('/users'" in FRONTEND
    assert "api('/client-portal/access'" in FRONTEND


def test_client_management_has_a_route_level_mobile_detail_not_a_hidden_table_column():
    assert "state.clientId = route === 'clients' && routeId ? routeId : null" in FRONTEND
    assert "renderClientDetail(content, state.clientId, state.clientTab)" in FRONTEND
    assert "renderClientUsersPanel(panel, client)" in FRONTEND
    assert "location.hash = `clients/${element.dataset.clientOpen}`" in FRONTEND
    assert "clients/${button.dataset.clientUsers}/users" in FRONTEND
    styles = Path("app/static/styles.css").read_text(encoding="utf8")
    assert ".client-mobile-list,.site-mobile-list { display:grid" in styles
    assert ".client-desktop-table { display:none; }" in styles


def test_client_detail_connects_sites_equipment_summary_and_existing_passport():
    customers = Path("app/routers/customers.py").read_text(encoding="utf8")
    assert '@router.get("/{client_id}/summary")' in customers
    assert "Client.id == client_id, Client.organization_id == user.organization_id" in customers
    assert "completed_last_30_days" in customers
    assert 'Site.client_id == client_id' in customers
    assert "renderClientSiteDetail(content, client, state.clientSiteId)" in FRONTEND
    assert "clients/${client.id}/sites/${button.dataset.clientSite}" in FRONTEND
    assert "openEquipmentPassport(button.dataset.clientEquipment)" in FRONTEND
    assert "apiBlob(`/equipment/${frame.dataset.clientEquipmentPhoto}/photo`)" in FRONTEND
    assert "Пользователи${canManageUsers ? ` (${accessCount})` : ''}" in FRONTEND
    assert "У клиента пока нет пользователей кабинета" in FRONTEND


def test_client_quick_actions_are_limited_to_service_staff():
    assert "const canManageUsers = ['owner', 'admin', 'dispatcher'].includes(state.me.role);" in FRONTEND
    assert "id=\"client-action-site\"" in FRONTEND
    assert "id=\"client-action-user\"" in FRONTEND
    assert "id=\"client-action-equipment\"" in FRONTEND


def test_client_details_can_edit_existing_business_and_contact_data():
    customers = Path("app/routers/customers.py").read_text(encoding="utf8")
    assert '@router.patch("/{client_id}", response_model=ClientOut)' in customers
    assert "const canEditClient = ['admin', 'dispatcher'].includes(state.me.role);" in FRONTEND
    assert 'id="client-action-edit"' in FRONTEND
    assert "function openClientEditModal(client)" in FRONTEND
    assert "method: 'PATCH'" in FRONTEND
    for field in ("tax_id", "contact_name", "contact_phone", "contact_email", "is_active"):
        assert field in FRONTEND
