"""Standards-based Web Push delivery, deliberately isolated from business writes."""
from __future__ import annotations

import json
import logging
import uuid
import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from functools import wraps
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.push import PushSubscription
from app.services.push_endpoint import UnsafePushEndpoint, validate_endpoint
from app.services.push_transport import CONNECT_TIMEOUT, READ_TIMEOUT, PushSession

logger = logging.getLogger(__name__)
MAX_SUBSCRIPTIONS = 10
DELIVERY_BUDGET = 2.0
# At most four outstanding sends per process, including slow DNS. No backlog.
_workers = ThreadPoolExecutor(max_workers=4, thread_name_prefix="webpush")
_slots = threading.BoundedSemaphore(4)


def best_effort(function):
    """Bound the whole fanout, including recipient lookup and cleanup errors."""
    @wraps(function)
    async def bounded(db, *args, **kwargs):
        async def invoke():
            if isinstance(db, AsyncSession):
                # Cancelled SQL/cleanup must never invalidate the caller's
                # transaction (sync batches reuse it after notifying).
                async with AsyncSession(bind=db.bind, expire_on_commit=False) as notification_db:
                    return await function(notification_db, *args, **kwargs)
            return await function(db, *args, **kwargs)
        try:
            return await asyncio.wait_for(invoke(), timeout=DELIVERY_BUDGET)
        except Exception as exc:
            logger.warning("Web Push notification failed: %s", type(exc).__name__)
    return bounded


async def _deliver(subscription, payload):
    if not _slots.acquire(blocking=False):
        return
    try:
        # Worker may finish after the HTTP request/AsyncSession closes.
        delivery = SimpleNamespace(endpoint=subscription.endpoint, p256dh=subscription.p256dh, auth=subscription.auth)
        future = _workers.submit(_send, delivery, payload)
    except Exception:
        _slots.release()
        raise
    future.add_done_callback(lambda _: _slots.release())
    await asyncio.wrap_future(future)


def configured() -> bool:
    return bool(settings.vapid_public_key and settings.vapid_private_key and settings.vapid_subject)


def safe_request_url(request_id: uuid.UUID) -> str:
    return f"/#requests/{request_id}"


def _send(subscription: PushSubscription, payload: dict) -> None:
    from pywebpush import WebPushException, webpush
    validate_endpoint(subscription.endpoint)
    try:
        webpush(
            subscription_info={"endpoint": subscription.endpoint, "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth}},
            data=json.dumps(payload, ensure_ascii=False),
            vapid_private_key=settings.vapid_private_key,
            vapid_claims={"sub": settings.vapid_subject},
            timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
            requests_session=PushSession(),
        )
    except WebPushException:
        raise


@best_effort
async def send_to_user(db: AsyncSession, *, user_id: uuid.UUID, organization_id: uuid.UUID,
                       title: str, body: str, url: str) -> None:
    """Best-effort delivery: an unavailable push gateway must never break work."""
    if not configured() or not url.startswith("/#requests/"):
        return
    subscriptions = (await db.scalars(select(PushSubscription).where(
        PushSubscription.user_id == user_id,
        PushSubscription.organization_id == organization_id,
        PushSubscription.is_active.is_(True),
    ).order_by(PushSubscription.last_seen_at.desc()).limit(MAX_SUBSCRIPTIONS))).all()
    for subscription in subscriptions:
        try:
            validate_endpoint(subscription.endpoint)
            await _deliver(subscription, {"title": title[:120], "body": body[:240], "url": url})
        except Exception as exc:  # pywebpush preserves status on response when available
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            if status_code in {404, 410} or isinstance(exc, UnsafePushEndpoint):
                subscription.is_active = False
            logger.warning("Web Push delivery failed for subscription %s: %s", subscription.id, type(exc).__name__)
    if any(not subscription.is_active for subscription in subscriptions):
        await db.commit()


@best_effort
async def notify_request_assigned(db: AsyncSession, request, equipment_name: str, client_name: str | None) -> None:
    if request.assigned_technician_id:
        await send_to_user(db, user_id=request.assigned_technician_id, organization_id=request.organization_id,
                           title="Новая заявка", body=f"{equipment_name} · {client_name or 'Объект'}",
                           url=safe_request_url(request.id))


@best_effort
async def notify_dispatchers(db: AsyncSession, request, body: str) -> None:
    from app.models.core import UserRole
    from app.models.organization import OrganizationMembership
    recipients = (await db.scalars(select(OrganizationMembership.user_id).where(
        OrganizationMembership.organization_id == request.organization_id,
        OrganizationMembership.is_active.is_(True),
        OrganizationMembership.role.in_([UserRole.owner, UserRole.admin, UserRole.dispatcher]),
    ))).all()
    for user_id in recipients:
        await send_to_user(db, user_id=user_id, organization_id=request.organization_id,
                           title="Заявка требует внимания", body=body, url=safe_request_url(request.id))


@best_effort
async def notify_client_approvers(db: AsyncSession, request, body: str) -> None:
    """Notify only client representatives whose saved scope contains the equipment site."""
    from app.models.core import Equipment, UserRole
    from app.models.customer import ClientUserAccess, Site
    from app.models.organization import OrganizationMembership
    scope = (await db.execute(select(Site.client_id, Equipment.site_id).join(
        Equipment, Equipment.site_id == Site.id,
    ).where(Equipment.id == request.equipment_id, Equipment.organization_id == request.organization_id))).first()
    if not scope:
        return
    client_id, site_id = scope
    recipients = (await db.scalars(select(ClientUserAccess.user_id).join(
        OrganizationMembership,
        (OrganizationMembership.user_id == ClientUserAccess.user_id) &
        (OrganizationMembership.organization_id == ClientUserAccess.organization_id),
    ).where(
        ClientUserAccess.organization_id == request.organization_id,
        ClientUserAccess.client_id == client_id,
        ClientUserAccess.is_active.is_(True),
        OrganizationMembership.is_active.is_(True),
        OrganizationMembership.role.in_([UserRole.client_admin, UserRole.client_site_user]),
        (ClientUserAccess.site_id.is_(None)) | (ClientUserAccess.site_id == site_id),
    ).distinct())).all()
    for user_id in recipients:
        await send_to_user(db, user_id=user_id, organization_id=request.organization_id,
                           title="Нужно согласование", body=body, url=safe_request_url(request.id))
