from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.models.push import PushSubscription
from app.routers import push as push_router, service_requests, sync as sync_router
from app.services import push_service
from test_onboarding_postgres import auth, pg
from test_request_workflow_postgres import flow, new_request, repair_body, start, status, sync

pytestmark = pytest.mark.asyncio


async def test_assignment_emits_push_event(flow, monkeypatch):
    request_id = await new_request(flow)
    mocked = AsyncMock()
    monkeypatch.setattr(service_requests, "notify_request_assigned", mocked)
    response = await flow.http.patch(f"/api/service-requests/{request_id}/assign", headers=auth(flow.owner, flow.org), params={"technician_id": str(flow.tech.id)})
    assert response.status_code == 200, response.text
    mocked.assert_awaited_once()


async def test_client_approval_wait_emits_scoped_push_event(flow, monkeypatch):
    request_id = await new_request(flow)
    await start(flow, request_id)
    mocked = AsyncMock()
    monkeypatch.setattr(service_requests, "notify_client_approvers", mocked)
    response = await status(flow, request_id, "waiting_approval", details={"approval_target": "client"})
    assert response.status_code == 200, response.text
    mocked.assert_awaited_once()


async def test_completion_emits_dispatcher_push_event(flow, monkeypatch):
    request_id = await new_request(flow)
    await start(flow, request_id)
    mocked = AsyncMock()
    monkeypatch.setattr(sync_router, "notify_dispatchers", mocked)
    result = await sync(flow, repair_body(flow, request_id))
    assert result["resolved_as"] in {"applied", "applied_with_conflict"}
    mocked.assert_awaited_once()


async def test_subscribe_reassigns_browser_endpoint_to_current_account(pg, monkeypatch):
    endpoint = "https://push.invalid/reused-browser-endpoint"
    async with pg.sessions() as db:
        db.add(PushSubscription(
            user_id=pg.existing.id,
            organization_id=pg.org.id,
            endpoint=endpoint,
            p256dh="old-key",
            auth="old-auth",
        ))
        await db.commit()
    monkeypatch.setattr(push_router, "configured", lambda: True)

    response = await pg.http.post("/api/push/subscribe", headers=auth(pg.owner, pg.org), json={
        "endpoint": endpoint,
        "keys": {"p256dh": "new-key", "auth": "new-auth"},
    })
    assert response.status_code == 204, response.text
    async with pg.sessions() as db:
        item = await db.scalar(select(PushSubscription).where(PushSubscription.endpoint == endpoint))
        assert item.user_id == pg.owner.id
        assert item.organization_id == pg.org.id
        assert item.p256dh == "new-key"
        assert item.auth == "new-auth"
        assert item.is_active is True


async def test_gone_push_endpoint_is_deactivated(pg, monkeypatch):
    endpoint = "https://push.invalid/gone-endpoint"
    async with pg.sessions() as db:
        db.add(PushSubscription(
            user_id=pg.owner.id,
            organization_id=pg.org.id,
            endpoint=endpoint,
            p256dh="test-key",
            auth="test-auth",
        ))
        await db.commit()

    class GoneEndpoint(Exception):
        response = SimpleNamespace(status_code=410)

    def fail_delivery(*_args, **_kwargs):
        raise GoneEndpoint()

    monkeypatch.setattr(push_service, "configured", lambda: True)
    monkeypatch.setattr(push_service, "_send", fail_delivery)
    async with pg.sessions() as db:
        await push_service.send_to_user(
            db,
            user_id=pg.owner.id,
            organization_id=pg.org.id,
            title="Тест",
            body="Тестовая подписка, реальная отправка не выполняется",
            url="/#requests/00000000-0000-0000-0000-000000000001",
        )
    async with pg.sessions() as db:
        item = await db.scalar(select(PushSubscription).where(PushSubscription.endpoint == endpoint))
        assert item.is_active is False
