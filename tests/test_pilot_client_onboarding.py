"""Security contracts for pilot-first client onboarding.

Database integration is deployed through Alembic; these focused regression
tests keep the API boundary and scope invariants visible without a local PG.
"""
from pathlib import Path

from app.models.customer import ClientInvite, ClientUserAccess


INVITES = Path("app/routers/invites.py").read_text(encoding="utf8")
EQUIPMENT = Path("app/routers/equipment.py").read_text(encoding="utf8")
PORTAL = Path("app/services/client_portal.py").read_text(encoding="utf8")
FRONTEND = Path("app/static/app.js").read_text(encoding="utf8")


def test_invite_persists_only_hash_and_authoritative_scope():
    columns = set(ClientInvite.__table__.columns.keys())
    assert {"organization_id", "client_id", "site_id", "target_role", "invited_by_user_id", "token_hash", "expires_at", "accepted_at", "revoked_at", "status"} <= columns
    assert "secrets.token_urlsafe(32)" in INVITES
    assert "hashlib.sha256" in INVITES
    assert "role: UserRole" in INVITES
    assert "target_role=role" in INVITES


def test_acceptance_validates_expiry_email_and_existing_identity_atomically():
    assert "with_for_update()" in INVITES
    assert "invite.expires_at <= now" in INVITES
    assert "invite.invited_email.lower() != email" in INVITES
    assert "func.lower(User.email) == email" in INVITES
    assert "existing" not in ClientInvite.__table__.columns
    assert "await db.commit()" in INVITES
    assert "ClientUserAccess(" in INVITES


def test_invite_role_site_binding_cannot_be_tampered_from_join_form():
    assert "InviteAcceptRequest" in INVITES
    accept = INVITES.split("async def accept_invite", 1)[1]
    assert "payload.site_id" not in accept and "payload.role" not in accept and "payload.client_id" not in accept
    assert "access_site_id = None if invite.target_role" in accept


def test_site_manager_equipment_write_is_scoped_to_its_allowed_site():
    assert "UserRole.client_site_user" in EQUIPMENT
    assert "allowed_site_ids is None or site.id not in allowed_site_ids" in EQUIPMENT
    assert "Можно добавлять оборудование только на свой объект" in EQUIPMENT
    assert "Менеджер объекта не может переносить оборудование" in EQUIPMENT
    assert "equipment = await _equipment_for_user(equipment_id, db, user)" in EQUIPMENT


def test_client_scope_keeps_manager_out_of_other_sites_and_clients():
    assert "if site_ids is not None" in PORTAL
    assert "Site.client_id == client_id" in PORTAL
    assert "ClientUserAccess.is_active.is_(True)" in PORTAL


def test_director_join_activates_existing_client_without_creating_another():
    accept = INVITES.split("async def accept_invite", 1)[1]
    assert "client.adoption_status = \"active\"" in accept
    assert "Client(" not in accept
    assert '"client.promoted_to_active"' in accept
    assert '"client.member_added"' in accept


def test_existing_pwa_onboarding_and_deep_link_are_reused():
    assert "maybeStartPwaOnboarding" in FRONTEND
    assert "fixit-join-route" in FRONTEND
    assert "showJoinScreen" in FRONTEND
    assert "clients/${invite.client_id}/users" in FRONTEND
    assert "'equipment'" in FRONTEND


def test_invite_qr_is_generated_from_opaque_capability_not_internal_ids():
    assert "secrets.compare_digest(invite.token_hash, _digest(token))" in INVITES
    assert "qrcode.make(_join_url(token)" in INVITES


def test_invite_modal_keeps_optional_email_separate_from_generated_join_url():
    modal = FRONTEND.split("async function openClientInviteModal", 1)[1]
    assert 'emailInput.value = \'\'' in modal
    assert 'const invited_email = emailInput.value.trim()' in modal
    assert 'if (invited_email && !emailInput.checkValidity())' in modal
    assert 'invited_email: invited_email || null' in modal
    assert 'label>Ссылка-приглашение</label><input value="${esc(invite.join_url)}" readonly id="invite-url"' in modal
    assert modal.index('!emailInput.checkValidity()') < modal.index('await api(`/client-portal/clients/${client.id}/invites/${kind}`')
