"""Standards-based Web Push delivery, deliberately isolated from business writes."""
from __future__ import annotations

import json
import logging
import uuid

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.push import PushSubscription

logger = logging.getLogger(__name__)


def configured() -> bool:
    return bool(settings.vapid_public_key and settings.vapid_private_key and settings.vapid_subject)


def safe_request_url(request_id: uuid.UUID) -> str:
    return f"/#requests/{request_id}"


def _send(subscription: PushSubscription, payload: dict) -> None:
    from pywebpush import WebPushException, webpush
    try:
        webpush(
            subscription_info={"endpoint": subscription.endpoint, "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth}},
            data=json.dumps(payload, ensure_ascii=False),
            vapid_private_key=settings.vapid_private_key,
            vapid_claims={"sub": settings.vapid_subject},
        )
    except WebPushException:
        raise


async def send_to_user(db: AsyncSession, *, user_id: uuid.UUID, organization_id: uuid.UUID,
                       title: str, body: str, url: str) -> None:
    """Best-effort delivery: an unavailable push gateway must never break work."""
    if not configured() or not url.startswith("/#requests/"):
        return
    subscriptions = (await db.scalars(select(PushSubscription).where(
        PushSubscription.user_id == user_id,
        PushSubscription.organization_id == organization_id,
        PushSubscription.is_active.is_(True),
    ))).all()
    for subscription in subscriptions:
        try:
            await run_in_threadpool(_send, subscription, {"title": title[:120], "body": body[:240], "url": url})
        except Exception as exc:  # pywebpush preserves status on response when available
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            if status_code in {404, 410}:
                subscription.is_active = False
                await db.commit()
            logger.warning("Web Push delivery failed for subscription %s: %s", subscription.id, type(exc).__name__)


async def notify_request_assigned(db: AsyncSession, request, equipment_name: str, client_name: str | None) -> None:
    if request.assigned_technician_id:
        await send_to_user(db, user_id=request.assigned_technician_id, organization_id=request.organization_id,
                           title="Новая заявка", body=f"{equipment_name} · {client_name or 'Объект'}",
                           url=safe_request_url(request.id))


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
