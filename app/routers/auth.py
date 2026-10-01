from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.deps import CurrentUser, get_current_user
from app.core.security import create_access_token, create_password_reset_token, hash_password, hash_password_reset_token, verify_password
from app.database import get_db
from app.models.core import PasswordResetToken, User
from app.models.organization import Organization, OrganizationMembership
from app.schemas.user import LoginRequest, PasswordChangeRequest, PasswordResetComplete, PasswordResetRequest, PasswordResetRequestOut, PasswordResetState, Token
from app.services.password_mail import send_password_reset

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=Token)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    user = await db.scalar(select(User).where(func.lower(User.email) == str(payload.email).lower()))
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный email или пароль")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Учётная запись отключена")
    membership_query = (
        select(OrganizationMembership, Organization)
        .join(Organization, Organization.id == OrganizationMembership.organization_id)
        .where(
            OrganizationMembership.user_id == user.id,
            OrganizationMembership.is_active.is_(True),
            Organization.is_active.is_(True),
        )
        .order_by(OrganizationMembership.created_at)
    )
    if payload.organization_slug:
        membership_query = membership_query.where(Organization.slug == payload.organization_slug)
    row = (await db.execute(membership_query)).first()
    if not row:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Нет доступа к активной организации")
    membership, organization = row
    token = create_access_token(user.id, organization.id, membership.role.value, user.auth_version)
    return Token(access_token=token, organization_id=organization.id, role=membership.role)


def _check_new_password(password: str, confirmation: str, current_hash: str | None = None) -> None:
    if password != confirmation:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Пароли не совпадают")
    if len(password) < 10 or not any(char.isalpha() for char in password) or not any(char.isdigit() for char in password):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Новый пароль: не менее 10 символов, включая букву и цифру")
    if current_hash and verify_password(password, current_hash):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Новый пароль должен отличаться от текущего")


@router.post("/password/change", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(payload: PasswordChangeRequest, db: AsyncSession = Depends(get_db), current: CurrentUser = Depends(get_current_user)):
    user = await db.scalar(select(User).where(User.id == current.id).with_for_update())
    if not user or not verify_password(payload.current_password, user.hashed_password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Текущий пароль указан неверно")
    _check_new_password(payload.new_password, payload.confirmation, user.hashed_password)
    user.hashed_password = hash_password(payload.new_password)
    user.auth_version += 1
    await db.execute(update(PasswordResetToken).where(
        PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None),
    ).values(used_at=datetime.now(timezone.utc)))
    await db.commit()


RESET_MESSAGE = "Если такой адрес зарегистрирован, мы отправили инструкцию по восстановлению."


@router.post("/password/reset/request", response_model=PasswordResetRequestOut)
async def request_password_reset(payload: PasswordResetRequest, db: AsyncSession = Depends(get_db)):
    """Always returns the same public message to prevent account enumeration."""
    user = await db.scalar(select(User).where(func.lower(User.email) == str(payload.email).lower(), User.is_active.is_(True)))
    preview_url = None
    if user:
        recent = await db.scalar(select(func.count()).select_from(PasswordResetToken).where(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.created_at >= datetime.now(timezone.utc) - timedelta(minutes=15),
        ))
        if (recent or 0) < 3:
            raw, digest = create_password_reset_token()
            expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.password_reset_expire_minutes)
            db.add(PasswordResetToken(user_id=user.id, token_hash=digest, expires_at=expires_at))
            await db.commit()
            reset_url = f"{settings.public_app_url.rstrip('/')}/#reset-password/{raw}"
            try:
                delivered = await send_password_reset(user.email, reset_url)
            except Exception:
                # Delivery details and addresses must not leak through this endpoint.
                delivered = False
            if settings.password_reset_debug and not delivered:
                preview_url = reset_url
    return PasswordResetRequestOut(message=RESET_MESSAGE, preview_url=preview_url)


async def _active_reset(db: AsyncSession, raw_token: str, *, lock: bool = False) -> PasswordResetToken | None:
    if len(raw_token) < 32 or len(raw_token) > 200:
        return None
    query = select(PasswordResetToken).where(
        PasswordResetToken.token_hash == hash_password_reset_token(raw_token),
        PasswordResetToken.used_at.is_(None),
        PasswordResetToken.expires_at > datetime.now(timezone.utc),
    )
    if lock:
        query = query.with_for_update()
    return await db.scalar(query)


@router.get("/password/reset/validate", response_model=PasswordResetState)
async def validate_password_reset(token: str = Query(min_length=32, max_length=200), db: AsyncSession = Depends(get_db)):
    return PasswordResetState(valid=bool(await _active_reset(db, token)))


@router.post("/password/reset/complete", status_code=status.HTTP_204_NO_CONTENT)
async def complete_password_reset(payload: PasswordResetComplete, db: AsyncSession = Depends(get_db)):
    item = await _active_reset(db, payload.token, lock=True)
    if not item:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ссылка недействительна или уже использована")
    user = await db.scalar(select(User).where(User.id == item.user_id, User.is_active.is_(True)).with_for_update())
    if not user:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ссылка недействительна или уже использована")
    _check_new_password(payload.new_password, payload.confirmation, user.hashed_password)
    now = datetime.now(timezone.utc)
    user.hashed_password = hash_password(payload.new_password)
    user.auth_version += 1
    await db.execute(update(PasswordResetToken).where(
        PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None),
    ).values(used_at=now))
    await db.commit()
