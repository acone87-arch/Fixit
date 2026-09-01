from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.deps import CurrentUser, get_current_user
from app.database import get_db
from app.models.push import PushSubscription
from app.schemas.push import PushStateOut, PushSubscriptionIn, PushUnsubscribeIn
from app.services.push_service import configured

router = APIRouter(prefix="/api/push", tags=["push"])


def _keys(payload: PushSubscriptionIn) -> tuple[str, str]:
    p256dh, auth = payload.keys.get("p256dh"), payload.keys.get("auth")
    if not p256dh or not auth:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Некорректная push subscription")
    return p256dh, auth


@router.get("/public-key")
async def public_key(user: CurrentUser = Depends(get_current_user)):
    if not settings.vapid_public_key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Push пока не настроен")
    return {"public_key": settings.vapid_public_key}


@router.get("/state", response_model=PushStateOut)
async def subscription_state(db: AsyncSession = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    subscribed = await db.scalar(select(PushSubscription.id).where(PushSubscription.user_id == user.id,
        PushSubscription.organization_id == user.organization_id, PushSubscription.is_active.is_(True)))
    return PushStateOut(supported=True, configured=configured(), subscribed=bool(subscribed))


@router.post("/subscribe", status_code=status.HTTP_204_NO_CONTENT)
async def subscribe(payload: PushSubscriptionIn, db: AsyncSession = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    if not configured():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Push пока не настроен")
    p256dh, auth = _keys(payload)
    item = await db.scalar(select(PushSubscription).where(PushSubscription.endpoint == payload.endpoint))
    if item and (item.user_id != user.id or item.organization_id != user.organization_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "Устройство связано с другой учётной записью")
    if not item:
        item = PushSubscription(user_id=user.id, organization_id=user.organization_id, endpoint=payload.endpoint, p256dh=p256dh, auth=auth)
        db.add(item)
    else:
        item.p256dh, item.auth, item.is_active, item.last_seen_at = p256dh, auth, True, datetime.now(timezone.utc)
    await db.commit()


@router.post("/unsubscribe", status_code=status.HTTP_204_NO_CONTENT)
async def unsubscribe(payload: PushUnsubscribeIn, db: AsyncSession = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    item = await db.scalar(select(PushSubscription).where(PushSubscription.endpoint == payload.endpoint,
        PushSubscription.user_id == user.id, PushSubscription.organization_id == user.organization_id))
    if item:
        item.is_active = False
        await db.commit()
