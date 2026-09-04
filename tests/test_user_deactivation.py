"""Regression contracts for safe tenant-scoped user removal."""
from pathlib import Path


USERS = Path("app/routers/users.py").read_text(encoding="utf8")
FRONTEND = Path("app/static/app.js").read_text(encoding="utf8")


def _delete_handler() -> str:
    return USERS.split('async def delete_user', 1)[1]


def test_delete_endpoint_is_admin_only_and_tenant_scoped():
    handler = _delete_handler()
    assert '@router.delete("/{user_id}"' in USERS
    assert 'Depends(require_roles(UserRole.admin))' in handler
    assert 'OrganizationMembership.organization_id == current.organization_id' in handler
    assert 'with_for_update()' in handler


def test_delete_rejects_self_and_last_active_administrator():
    handler = _delete_handler()
    assert 'user_id == current.id' in handler
    assert 'Нельзя удалить собственную учётную запись' in handler
    assert 'UserRole.owner, UserRole.admin' in handler
    assert 'Нельзя удалить последнего администратора организации' in handler


def test_delete_preserves_history_but_revokes_all_current_access():
    handler = _delete_handler()
    assert 'membership.is_active = False' in handler
    assert 'update(ClientUserAccess)' in handler and '.values(is_active=False)' in handler
    assert 'delete(TechnicianClientAccess)' in handler
    assert 'user.is_active = False' in handler
    assert 'await db.delete(user)' not in handler
    assert 'action="user.deactivated"' in handler


def test_deleted_user_disappears_from_active_user_list():
    assert 'OrganizationMembership.is_active.is_(True)' in USERS


def test_users_ui_confirms_destructive_action_and_hides_self_delete():
    section = FRONTEND.split('async function renderUsers', 1)[1].split('function openEditUserModal', 1)[0]
    assert 'data-delete-user' in section
    assert "u.id !== state.me?.id" in section
    assert 'function openDeleteUserModal' in FRONTEND
    assert 'Удалить пользователя?' in FRONTEND
    assert "method: 'DELETE'" in FRONTEND
    assert "button.disabled = true" in FRONTEND
    assert "toast('Пользователь удалён')" in FRONTEND
