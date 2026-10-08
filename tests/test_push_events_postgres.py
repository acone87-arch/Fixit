from types import SimpleNamespace
from unittest.mock import AsyncMock
import asyncio
import threading
import time

import pytest
from sqlalchemy import select
from sqlalchemy import func

from app.models.push import PushSubscription
from app.routers import push as push_router, service_requests, sync as sync_router
from app.services import push_service
from test_onboarding_postgres import auth, pg
from test_request_workflow_postgres import flow, new_request, repair_body, start, status, sync
from test_push_endpoint_security import synthetic_keys

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
    endpoint = "https://fcm.googleapis.com/fcm/send/reused-browser-endpoint"
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

    keys = synthetic_keys()
    response = await pg.http.post("/api/push/subscribe", headers=auth(pg.owner, pg.org), json={
        "endpoint": endpoint,
        "keys": keys,
    })
    assert response.status_code == 204, response.text
    async with pg.sessions() as db:
        item = await db.scalar(select(PushSubscription).where(PushSubscription.endpoint == endpoint))
        assert item.user_id == pg.owner.id
        assert item.organization_id == pg.org.id
        assert item.p256dh == keys["p256dh"]
        assert item.auth == keys["auth"]
        assert item.is_active is True


async def test_gone_push_endpoint_is_deactivated(pg, monkeypatch):
    endpoint = "https://fcm.googleapis.com/fcm/send/gone-endpoint"
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


async def test_subscription_budget_is_atomic_and_existing_device_can_rotate_keys(pg, monkeypatch):
    monkeypatch.setattr(push_router, "configured", lambda: True)
    async def subscribe(index, keys=None):
        return await pg.http.post("/api/push/subscribe", headers=auth(pg.owner, pg.org), json={
            "endpoint": f"https://fcm.googleapis.com/fcm/send/synthetic-{index}",
            "keys": keys or synthetic_keys()})
    responses = await asyncio.gather(*(subscribe(index) for index in range(15)))
    assert sum(r.status_code == 204 for r in responses) == push_service.MAX_SUBSCRIPTIONS
    assert sum(r.status_code == 429 for r in responses) == 5
    async with pg.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(PushSubscription)) == push_service.MAX_SUBSCRIPTIONS
        endpoint = await db.scalar(select(PushSubscription.endpoint).limit(1))
    headers = auth(pg.owner, pg.org)
    assert (await pg.http.post("/api/push/unsubscribe", headers=headers, json={"endpoint": endpoint})).status_code == 204
    assert not (await pg.http.get("/api/push/state", headers=headers, params={"endpoint": endpoint})).json()["subscribed"]
    rotated = synthetic_keys()
    assert (await pg.http.post("/api/push/subscribe", headers=headers, json={"endpoint": endpoint, "keys": rotated})).status_code == 204
    assert (await pg.http.get("/api/push/state", headers=headers, params={"endpoint": endpoint})).json()["subscribed"]


async def test_unsafe_registration_never_persists_and_legacy_endpoint_can_unsubscribe(pg, monkeypatch):
    monkeypatch.setattr(push_router, "configured", lambda: True)
    headers = auth(pg.owner, pg.org)
    response = await pg.http.post("/api/push/subscribe", headers=headers, json={
        "endpoint": "http://127.0.0.1/synthetic", "keys": synthetic_keys()})
    assert response.status_code == 422
    async with pg.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(PushSubscription)) == 0
        db.add(PushSubscription(user_id=pg.owner.id, organization_id=pg.org.id,
            endpoint="http://localhost/legacy-synthetic", **synthetic_keys()))
        await db.commit()
    assert (await pg.http.post("/api/push/unsubscribe", headers=headers,
        json={"endpoint": "http://localhost/legacy-synthetic"})).status_code == 204


async def test_slow_push_preserves_successful_assignment_response_and_saved_state(flow, monkeypatch):
    request_id = await new_request(flow)
    async with flow.sessions() as db:
        db.add(PushSubscription(user_id=flow.tech.id, organization_id=flow.org.id,
            endpoint="https://fcm.googleapis.com/fcm/send/synthetic-slow", **synthetic_keys()))
        await db.commit()
    release = threading.Event()
    def slow(*args):
        release.wait(2)
    monkeypatch.setattr(push_service, "configured", lambda: True)
    monkeypatch.setattr(push_service, "_send", slow)
    monkeypatch.setattr(push_service, "DELIVERY_BUDGET", 0.05)
    started = time.monotonic()
    try:
        response = await flow.http.patch(f"/api/service-requests/{request_id}/assign",
            headers=auth(flow.owner, flow.org), params={"technician_id": str(flow.tech.id)})
        assert response.status_code == 200, response.text
        assert time.monotonic() - started < 1
        saved = await flow.http.get(f"/api/service-requests/{request_id}", headers=auth(flow.owner, flow.org))
        assert saved.json()["assigned_technician_id"] == str(flow.tech.id)
        assert saved.json()["status"] == "assigned"
    finally:
        release.set()
