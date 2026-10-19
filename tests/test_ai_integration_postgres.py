"""Real HTTP/ACL/PG reservations, with only the paid provider replaced."""
import asyncio
import json
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from types import SimpleNamespace
from app.models.organization import OrganizationMembership
from app.models.core import UserRole

from app.config import settings
from app.models.ai import AIGeneration
from app.models.repair import Repair
from app.models.service_request import ServiceRequest
from app.services import ai_provider
from test_onboarding_postgres import pg, auth
from test_request_workflow_postgres import flow, new_request, start

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def ai_flow(flow, monkeypatch):
    f = flow
    for key, value in {"ai_enabled": True, "ai_repair_enabled": True, "ai_brief_enabled": True,
        "ai_organization_ids": str(f.org.id), "yandex_gpt_api_key": "synthetic-key-not-real",
        "yandex_gpt_folder_id": "synthetic-folder", "ai_prior_accounted_rub": 0}.items():
        monkeypatch.setattr(settings, key, value)
    f.calls = []
    async def provider(note, config):
        f.calls.append(note)
        raw = {"diagnostic_quotes": [], "work_quotes": [note], "comment_quotes": [], "questions": []}
        return {"usage": {"prompt_tokens": 100, "completion_tokens": 50},
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(raw)}}]}
    monkeypatch.setattr(ai_provider, "generate", provider)
    f.ai_provider = provider
    f.request_id = await new_request(f)
    await start(f, f.request_id)
    yield f


def payload(**overrides):
    return {"operation_id": str(uuid.uuid4()), "revision": "draft-1", "note": "Очистил фильтр.", **overrides}


async def generate(f, body=None, headers=None, request_id=None):
    return await f.http.post(f'/api/ai/service-requests/{request_id or f.request_id}/repair-draft',
        headers=headers or auth(f.tech, f.org), json=body or payload())


async def test_preview_idempotency_never_creates_repair(ai_flow):
    f = ai_flow
    body = payload()
    first, second = await generate(f, body), await generate(f, body)
    assert first.status_code == second.status_code == 200, (first.text, second.text)
    assert first.json()['work'] == 'Очистил фильтр.'
    assert second.json()['cached']
    assert first.json()['generation_id'] == second.json()['generation_id']
    assert len(f.calls) == 1
    assert first.headers['cache-control'] == 'no-store'
    changed = await generate(f, {**body, "note": "Промыл фильтр."})
    assert changed.status_code == 409
    async with f.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Repair)) == 0
        assert (await db.get(ServiceRequest, uuid.UUID(f.request_id))).status == 'in_progress'
        assert await db.scalar(select(func.count()).select_from(AIGeneration)) == 1


async def test_disabled_and_tenant_role_guards_do_not_call_provider(ai_flow, monkeypatch):
    f = ai_flow
    assert (await generate(f, headers=f.manager_headers)).status_code == 403
    foreign_org = SimpleNamespace(id=f.sites[3].organization_id)
    async with f.sessions() as db:
        db.add(OrganizationMembership(organization_id=foreign_org.id, user_id=f.owner.id, role=UserRole.owner))
        await db.commit()
    assert (await generate(f, headers=auth(f.owner, foreign_org))).status_code == 404
    monkeypatch.setattr(settings, 'ai_enabled', False)
    assert (await generate(f)).status_code == 503
    assert not f.calls


async def test_other_assignee_and_client_cannot_read_draft(ai_flow):
    f = ai_flow
    other_id = await new_request(f, index=1)
    assert (await generate(f, request_id=other_id)).status_code == 404
    assert (await generate(f, headers=f.manager_headers)).status_code == 403
    assert not f.calls


async def test_budget_rejects_before_transmission(ai_flow, monkeypatch):
    monkeypatch.setattr(settings, 'ai_daily_limit_rub', 0)
    result = await generate(ai_flow)
    assert result.status_code == 429
    assert not ai_flow.calls


async def test_private_contact_rejected_before_transmission(ai_flow):
    result = await generate(ai_flow, payload(note='Позвонить name@example.com'))
    assert result.status_code == 422
    assert not ai_flow.calls


async def test_timeout_retains_reserve_and_never_retries(ai_flow, monkeypatch):
    f = ai_flow
    async def timeout(note, config):
        f.calls.append(note)
        raise TimeoutError()
    monkeypatch.setattr(ai_provider, 'generate', timeout)
    body = payload()
    assert (await generate(f, body)).status_code == 502
    assert (await generate(f, body)).status_code == 409
    assert len(f.calls) == 1
    async with f.sessions() as db:
        row = await db.scalar(select(AIGeneration))
        assert row.status == 'unknown' and row.reserved_rub > 0 and row.estimated_rub is None


async def test_acl_change_during_provider_discards_result(ai_flow, monkeypatch):
    f = ai_flow
    async def provider(note, config):
        async with f.sessions() as db:
            request = await db.get(ServiceRequest, uuid.UUID(f.request_id))
            request.assigned_technician_id = f.owner.id
            await db.commit()
        return await f.ai_provider(note, config)
    monkeypatch.setattr(ai_provider, 'generate', provider)
    assert (await generate(f)).status_code == 404
    async with f.sessions() as db:
        row = await db.scalar(select(AIGeneration))
        assert row.status == 'failed' and row.result_json is None and row.estimated_rub is not None


async def test_two_identical_requests_only_generate_once(ai_flow, monkeypatch):
    f = ai_flow
    entered, release = asyncio.Event(), asyncio.Event()
    async def delayed(note, config):
        entered.set()
        await release.wait()
        return await f.ai_provider(note, config)
    monkeypatch.setattr(ai_provider, 'generate', delayed)
    body = payload()
    task = asyncio.create_task(generate(f, body))
    await asyncio.wait_for(entered.wait(), 5)
    try:
        assert (await generate(f, body)).status_code == 409
    finally:
        release.set()
    assert (await task).status_code == 200
    assert len(f.calls) == 1


async def test_concurrent_different_operations_cannot_overspend(ai_flow, monkeypatch):
    from decimal import Decimal
    f = ai_flow
    encoded = json.dumps(ai_provider.request_body('Очистил фильтр.', settings), ensure_ascii=False).encode()
    one = ((len(encoded) + 1024) * settings.ai_input_rub_per_1000 + ai_provider.MAX_OUTPUT * settings.ai_output_rub_per_1000) / 1000
    monkeypatch.setattr(settings, 'ai_daily_limit_rub', one + Decimal('0.01'))
    entered, release = asyncio.Event(), asyncio.Event()
    async def delayed(note, config):
        entered.set()
        await release.wait()
        return await f.ai_provider(note, config)
    monkeypatch.setattr(ai_provider, 'generate', delayed)
    task = asyncio.create_task(generate(f))
    await asyncio.wait_for(entered.wait(), 5)
    try:
        assert (await generate(f)).status_code == 429
    finally:
        release.set()
    assert (await task).status_code == 200
    assert len(f.calls) == 1


async def test_bad_evidence_retains_known_estimate_but_returns_no_draft(ai_flow, monkeypatch):
    async def invented(note, config):
        result = await ai_flow.ai_provider('Насос заменён.', config)
        return result
    monkeypatch.setattr(ai_provider, 'generate', invented)
    result = await generate(ai_flow)
    assert result.status_code == 502
    async with ai_flow.sessions() as db:
        row = await db.scalar(select(AIGeneration))
        assert row.estimated_rub is not None and row.result_json is None and row.status == 'failed'


async def test_brief_needs_equipment_scope_and_does_not_call_provider(ai_flow):
    f = ai_flow
    path = f'/api/ai/equipment/{f.equipment[0].id}/brief'
    # Assigned request alone does not grant the whole equipment history.
    assert (await f.http.post(path, headers=auth(f.tech, f.org))).status_code == 403
    result = await f.http.post(path, headers=auth(f.owner, f.org))
    assert result.status_code == 200, result.text
    assert result.json()['method'] == 'source_history_no_model_call'
    assert result.json()['facts'][0]['service_request_id'] == f.request_id
    assert not f.calls


async def test_feedback_and_confirmed_sync_are_distinct_and_idempotent(ai_flow):
    from test_request_workflow_postgres import repair_body, sync
    f = ai_flow
    result = (await generate(f)).json()
    gid = result['generation_id']
    path = f'/api/ai/generations/{gid}/feedback'
    for action in ['helpful', 'applied', 'applied']:
        response = await f.http.post(path, headers=auth(f.tech, f.org), json={'action': action, 'reason': 'accurate'})
        assert response.status_code == 200, response.text
    async with f.sessions() as db:
        row = await db.get(AIGeneration, uuid.UUID(gid))
        assert row.applied_at and row.rating == 'helpful' and row.repair_id is None
        applied_at = row.applied_at
        assert row.duration_ms is not None
    body = repair_body(f, f.request_id, ai_generation_id=gid)
    first, retry = await sync(f, body), await sync(f, body)
    assert first['server_id'] == retry['server_id'] and retry['resolved_as'] == 'already_synced'
    async with f.sessions() as db:
        row = await db.get(AIGeneration, uuid.UUID(gid))
        assert str(row.repair_id) == first['server_id'] and row.saved_at and row.applied_at == applied_at
    metrics = await f.http.get('/api/ai/metrics', headers=auth(f.owner, f.org))
    assert metrics.status_code == 200
    data = metrics.json()
    assert data['saved_repairs'] == data['applied'] == data['helpful'] == data['calls'] == 1
    assert data['latency_ms']['samples'] == 1
    assert 'Очистил' not in metrics.text and 'synthetic-key' not in metrics.text
    assert (await f.http.get('/api/ai/metrics', headers=auth(f.tech, f.org))).status_code == 403


async def test_feedback_acl_and_strict_contract(ai_flow):
    f = ai_flow
    gid = (await generate(f)).json()['generation_id']
    path = f'/api/ai/generations/{gid}/feedback'
    assert (await f.http.post(path, headers=auth(f.owner, f.org), json={'action': 'applied'})).status_code == 404
    assert (await f.http.post(path, headers=auth(f.tech, f.org), json={'action': 'saved'})).status_code == 422
    assert (await f.http.post(path, headers=auth(f.tech, f.org), json={'action': 'helpful', 'text': 'private'})).status_code == 422
    async with f.sessions() as db:
        request = await db.get(ServiceRequest, uuid.UUID(f.request_id))
        request.assigned_technician_id = f.owner.id
        await db.commit()
    assert (await f.http.post(path, headers=auth(f.tech, f.org), json={'action': 'applied'})).status_code == 404


async def test_wrong_generation_metadata_does_not_block_repair_or_attach(ai_flow):
    from test_request_workflow_postgres import repair_body, sync
    f = ai_flow
    gid = (await generate(f)).json()['generation_id']
    second = await new_request(f, index=1)
    await start(f, second)
    body = repair_body(f, second, equipment_id=str(f.equipment[1].id),
                       base_equipment_version=f.equipment[1].version, ai_generation_id=gid)
    assert (await sync(f, body))['resolved_as'] == 'applied'
    async with f.sessions() as db:
        assert (await db.get(AIGeneration, uuid.UUID(gid))).repair_id is None


async def test_expired_text_cleanup_preserves_reserves_and_sync_provenance(ai_flow):
    from datetime import datetime, timedelta, timezone
    from app.services.ai_retention import maintain
    f = ai_flow
    gid = (await generate(f)).json()['generation_id']
    async with f.sessions() as db:
        row = await db.get(AIGeneration, uuid.UUID(gid))
        row.created_at = datetime.now(timezone.utc) - timedelta(days=91)
        row.status = 'unknown'
        row.estimated_rub = None
        await db.commit()
        reserve = row.reserved_rub
        preview = await maintain(db)
        assert preview['expired_result_bodies'] == preview['metadata_older_than_90_days'] == 1
        await db.refresh(row)
        assert row.result_json
        await maintain(db, apply=True)
        await db.refresh(row)
        assert row.result_json is None and row.reserved_rub == reserve and row.status == 'unknown'
        assert (await maintain(db, apply=True))['expired_result_bodies'] == 0


async def test_failed_repair_transaction_rolls_back_ai_link(ai_flow, monkeypatch):
    from app.services import sync_service
    from test_request_workflow_postgres import repair_body, sync
    f = ai_flow
    gid = (await generate(f)).json()['generation_id']
    original = sync_service.transition
    async def reject(*args, **kwargs):
        raise sync_service._SyncFailure('Synthetic rollback after provenance attachment')
    monkeypatch.setattr(sync_service, 'transition', reject)
    body = repair_body(f, f.request_id, ai_generation_id=gid)
    assert (await sync(f, body))['resolved_as'] == 'failed'
    async with f.sessions() as db:
        assert (await db.get(AIGeneration, uuid.UUID(gid))).repair_id is None
        assert await db.scalar(select(func.count()).select_from(Repair)) == 0
    monkeypatch.setattr(sync_service, 'transition', original)
    assert (await sync(f, body))['resolved_as'] == 'applied'
    assert len(f.calls) == 1


async def test_metrics_do_not_include_other_organizations(ai_flow):
    f = ai_flow
    assert (await generate(f)).status_code == 200
    foreign_org = SimpleNamespace(id=f.sites[3].organization_id)
    async with f.sessions() as db:
        db.add(OrganizationMembership(organization_id=foreign_org.id, user_id=f.owner.id, role=UserRole.owner))
        await db.commit()
    response = await f.http.get('/api/ai/metrics', headers=auth(f.owner, foreign_org))
    assert response.status_code == 200
    data = response.json()
    assert data['calls'] == data['saved_repairs'] == data['applied'] == 0
    assert data['estimated_rub'] == data['unresolved_reserve_rub'] == '0'
    assert data['latency_ms']['samples'] == 0
