"""Исполняемые HTTP-регрессии P0.1. БД подменена; это не PG integration."""
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from app.core.deps import get_current_user
from app.core.security import hash_password
from app.database import get_db
from app.main import app
from app.models.core import User, UserRole
from app.models.customer import ClientInvite
from app.routers import invites

PASSWORD = 'pilot-test-password'
PASSWORD_HASH = hash_password(PASSWORD)


@pytest.fixture
def scenario(monkeypatch):
    org, client_id, site_id, user_id = [uuid.uuid4() for _ in range(4)]
    # Именно конвертер ORM, который возвращает PostgreSQL enum как str.
    role = ClientInvite.__table__.c.target_role.type.result_processor(postgresql.dialect(), None)('client_site_user')
    invite = SimpleNamespace(id=uuid.uuid4(), organization_id=org, client_id=client_id,
        site_id=site_id, target_role=role, invited_email=None, status='pending',
        expires_at=datetime.now(timezone.utc) + timedelta(days=1))
    user = User(id=user_id, email='pilot@example.com', full_name='Менеджер',
        hashed_password=PASSWORD_HASH, role=UserRole.technician, is_active=True)
    membership = SimpleNamespace(role=UserRole.client_site_user, is_active=True)
    access = SimpleNamespace(client_id=client_id, site_id=site_id, is_active=True)
    db = AsyncMock()
    db.add = MagicMock()
    db.scalar.side_effect = [user, membership, access]
    db.scalars.return_value = SimpleNamespace(all=lambda: [access])
    db.get.return_value = SimpleNamespace(name='Клиент', legal_name=None, adoption_status='pilot')
    monkeypatch.setattr(invites, '_usable_invite', AsyncMock(return_value=invite))
    async def database():
        yield db
    before = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = database
    with TestClient(app, raise_server_exceptions=False) as http:
        yield SimpleNamespace(http=http, db=db, invite=invite, user=user,
                              membership=membership, access=access)
    app.dependency_overrides.clear()
    app.dependency_overrides.update(before)


def accept(s, **kwargs):
    return s.http.post('/api/join/test-token/accept', json={
        'email': s.user.email, 'password': PASSWORD, 'full_name': 'Новый менеджер', **kwargs})


def test_accept_loaded_string_role_commits_and_returns_token(scenario):
    s = scenario
    response = accept(s)
    assert response.status_code == 200, response.text
    assert response.json()['role'] == 'client_site_user'
    assert s.invite.status == 'accepted'
    s.db.commit.assert_awaited_once()
    events = [c.args[0] for c in s.db.add.call_args_list if hasattr(c.args[0], 'action')]
    assert {e.action for e in events} == {'invite.accepted', 'client.member_added'}
    assert all(e.details_json['role'] == 'client_site_user' for e in events)


def test_existing_account_wrong_password_does_not_commit(scenario):
    response = accept(scenario, password='wrong-password')
    assert response.status_code == 401
    scenario.db.commit.assert_not_awaited()


def test_invited_email_cannot_be_replaced(scenario):
    scenario.invite.invited_email = 'other@example.com'
    assert accept(scenario).status_code == 403
    scenario.db.commit.assert_not_awaited()


@pytest.mark.parametrize('disabled', ['user', 'membership', 'access'])
def test_invite_does_not_restore_disabled_access(scenario, disabled):
    getattr(scenario, disabled).is_active = False
    response = accept(scenario)
    assert response.status_code == 403, response.text
    assert not getattr(scenario, disabled).is_active
    scenario.db.commit.assert_not_awaited()


def test_invite_to_different_client_does_not_break_existing_scope(scenario):
    scenario.access.client_id = uuid.uuid4()
    response = accept(scenario)
    assert response.status_code == 409, response.text
    scenario.db.commit.assert_not_awaited()


def test_internal_staff_cannot_become_client_via_invite(scenario):
    scenario.membership.role = UserRole.dispatcher
    assert accept(scenario).status_code == 409
    scenario.db.commit.assert_not_awaited()


def test_service_technicians_route_receives_db_and_current_user(scenario):
    s = scenario
    technician_id = uuid.uuid4()
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=s.user.id, organization_id=s.invite.organization_id, role=UserRole.owner)
    s.db.scalar.side_effect = [SimpleNamespace(id=s.invite.client_id)]
    s.db.scalars.side_effect = [SimpleNamespace(all=lambda: [technician_id]),
                               SimpleNamespace(all=lambda: [])]
    response = s.http.put(f'/api/clients/{s.invite.client_id}/technicians',
                         json={'technician_ids': [str(technician_id)]})
    assert response.status_code == 200, response.text
    assert response.json()['technician_ids'] == [str(technician_id)]
    s.db.commit.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize('invalid', [None, 'expired', 'reused', 'revoked', 'organization',
    'client', 'site', 'foreign_site', 'wrong_role', 'inviter', 'inviter_membership'])
async def test_invite_capability_lifecycle(invalid):
    from fastapi import HTTPException
    from app.models.customer import Client, Site
    from app.models.organization import Organization
    org_id, client_id, site_id, inviter_id = [uuid.uuid4() for _ in range(4)]
    invitation = SimpleNamespace(organization_id=org_id, client_id=client_id, site_id=site_id,
        invited_by_user_id=inviter_id, status='pending', target_role='client_site_user',
        expires_at=datetime.now(timezone.utc) + timedelta(days=1))
    organization = SimpleNamespace(id=org_id, is_active=True)
    client = SimpleNamespace(id=client_id, organization_id=org_id, is_active=True)
    site = SimpleNamespace(id=site_id, organization_id=org_id, client_id=client_id, is_active=True)
    inviter = SimpleNamespace(id=inviter_id, is_active=True)
    membership = SimpleNamespace(role=UserRole.owner, is_active=True)
    if invalid in {'reused', 'revoked'}: invitation.status = 'accepted' if invalid == 'reused' else 'revoked'
    if invalid == 'expired': invitation.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    if invalid == 'wrong_role': invitation.target_role = 'owner'
    if invalid == 'foreign_site': site.client_id = uuid.uuid4()
    objects = {'organization': organization, 'client': client, 'site': site, 'inviter': inviter}
    if invalid in objects: objects[invalid].is_active = False
    db = AsyncMock()
    db.scalar.side_effect = [invitation, None if invalid == 'inviter_membership' else membership]
    mapping = {Organization: organization, Client: client, Site: site, User: inviter}
    db.get.side_effect = lambda model, key: mapping[model]
    if invalid:
        with pytest.raises(HTTPException) as error:
            await invites._usable_invite('token', db, lock=True)
        assert error.value.status_code == 404
    else:
        assert await invites._usable_invite('token', db, lock=True) is invitation


def test_new_user_is_created_with_server_invite_role(scenario):
    s = scenario
    s.db.scalar.side_effect = [None, None, None]
    s.db.scalars.return_value = SimpleNamespace(all=lambda: [])
    async def flush():
        for call in s.db.add.call_args_list:
            if isinstance(call.args[0], User):
                call.args[0].id = uuid.uuid4()
    s.db.flush.side_effect = flush
    response = accept(s, role='owner', site_id=str(uuid.uuid4()))
    assert response.status_code == 200, response.text
    assert response.json()['role'] == 'client_site_user'
    s.db.commit.assert_awaited_once()


def test_director_promotes_same_client_and_records_role(scenario):
    s = scenario
    s.invite.target_role = 'client_admin'
    s.invite.site_id = None
    s.db.scalar.side_effect = [s.user, s.membership, None]
    response = accept(s)
    assert response.status_code == 200, response.text
    assert response.json()['role'] == 'client_admin'
    assert s.membership.role == UserRole.client_admin
    assert s.db.get.return_value.adoption_status == 'active'
