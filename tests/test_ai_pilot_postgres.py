"""Read-only pilot overview: roles, scope, flags, costs and no paid calls."""
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.config import settings
from app.models.core import UserRole
from app.models.organization import OrganizationMembership
from test_ai_integration_postgres import ai_flow, pg, flow, generate
from test_onboarding_postgres import auth

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize('role', [UserRole.owner, UserRole.admin, UserRole.dispatcher])
async def test_pilot_overview_staff_scope_and_no_secrets_or_model_calls(ai_flow, role):
    f = ai_flow
    assert (await generate(f)).status_code == 200
    async with f.sessions() as db:
        member = await db.scalar(select(OrganizationMembership).where(
            OrganizationMembership.organization_id == f.org.id, OrganizationMembership.user_id == f.owner.id))
        member.role = role
        await db.commit()
    response = await f.http.get('/api/ai/pilot', headers=auth(f.owner, f.org))
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['organization'] == {'id': str(f.org.id), 'name': f.org.name}
    assert data['metrics']['calls'] == 1 and data['metrics']['cost_basis'] == 'local_estimate_not_cloud_balance'
    assert data['configuration']['monthly_limit_rub'] == '300'
    assert data['configuration']['budget_scope'] == 'shared_pilot'
    assert data['configuration']['pilot_member'] and data['capabilities']['repair_draft']
    assert response.headers['cache-control'] == 'no-store'
    assert 'synthetic-key-not-real' not in response.text and 'synthetic-folder' not in response.text
    assert 'Очистил фильтр' not in response.text
    assert len(f.calls) == 1


async def test_pilot_rejects_technician_client_anonymous_and_revoked_member(ai_flow):
    f = ai_flow
    assert (await f.http.get('/api/ai/pilot', headers=auth(f.tech, f.org))).status_code == 403
    assert (await f.http.get('/api/ai/pilot', headers=f.manager_headers)).status_code == 403
    assert (await f.http.get('/api/ai/pilot')).status_code == 401
    async with f.sessions() as db:
        member = await db.scalar(select(OrganizationMembership).where(
            OrganizationMembership.organization_id == f.org.id, OrganizationMembership.user_id == f.owner.id))
        member.is_active = False
        await db.commit()
    assert (await f.http.get('/api/ai/pilot', headers=auth(f.owner, f.org))).status_code == 401
    assert not f.calls


async def test_pilot_disabled_still_shows_past_metrics_and_foreign_org_is_empty(ai_flow, monkeypatch):
    f = ai_flow
    assert (await generate(f)).status_code == 200
    monkeypatch.setattr(settings, 'ai_enabled', False)
    data = (await f.http.get('/api/ai/pilot', headers=auth(f.owner, f.org))).json()
    assert not data['capabilities']['enabled'] and data['metrics']['calls'] == 1
    foreign_org = SimpleNamespace(id=f.sites[3].organization_id)
    async with f.sessions() as db:
        db.add(OrganizationMembership(organization_id=foreign_org.id, user_id=f.owner.id, role=UserRole.owner))
        await db.commit()
    response = await f.http.get('/api/ai/pilot', headers=auth(f.owner, foreign_org), params={'organization_id': str(f.org.id)})
    assert response.status_code == 200
    data = response.json()
    assert data['organization']['id'] == str(foreign_org.id)
    assert data['metrics']['calls'] == 0 and data['metrics']['estimated_rub'] == '0'
    assert not data['configuration']['pilot_member']
    assert str(f.org.id) not in response.text
    assert len(f.calls) == 1


async def test_pilot_client_names_do_not_leak_across_organizations(ai_flow, monkeypatch):
    f = ai_flow
    monkeypatch.setattr(settings, 'ai_client_ids', f'{f.client.id},{f.sites[3].client_id}')
    data = (await f.http.get('/api/ai/pilot', headers=auth(f.owner, f.org))).json()
    assert data['configuration']['client_scope_restricted']
    assert data['configuration']['pilot_clients'] == [f.client.name]
    assert not f.calls
