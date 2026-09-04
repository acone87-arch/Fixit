"""Pilot-first onboarding links.  The link is the only public capability."""
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from io import BytesIO

import qrcode
import qrcode.image.svg
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.deps import CurrentUser, get_current_user
from app.core.security import create_access_token, hash_password, verify_password
from app.database import get_db
from app.models.core import User, UserRole
from app.models.customer import Client, ClientInvite, ClientInviteStatus, ClientUserAccess, Site
from app.models.organization import AuditEvent, OrganizationMembership
from app.schemas.customer import ClientInviteCreate, ClientInviteOut, InviteAcceptRequest
from app.schemas.user import Token
from app.services.client_portal import client_scope

router = APIRouter(prefix="/api/client-portal", tags=["client invites"])
public_router = APIRouter(prefix="/api/join", tags=["client invites"])
STAFF_INVITERS = {UserRole.owner, UserRole.admin, UserRole.dispatcher}


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _join_url(token: str) -> str:
    return f"{settings.public_app_url.rstrip('/')}/join/{token}"


def _role_value(role: UserRole | str) -> str:
    """The existing PostgreSQL enum mapping returns a string on loaded invites."""
    return role.value if hasattr(role, "value") else str(role)


def _out(invite: ClientInvite, raw_token: str | None = None) -> ClientInviteOut:
    return ClientInviteOut(id=invite.id, client_id=invite.client_id, site_id=invite.site_id,
        target_role=_role_value(invite.target_role),
        invited_email=invite.invited_email, status=invite.status.value if hasattr(invite.status, "value") else str(invite.status),
        expires_at=invite.expires_at, accepted_at=invite.accepted_at, revoked_at=invite.revoked_at,
        join_url=_join_url(raw_token) if raw_token else None,
        qr_url=f"/client-portal/invites/{invite.id}/qr?token={raw_token}" if raw_token else None)


async def _can_manage_client(user: CurrentUser, client_id: uuid.UUID, db: AsyncSession) -> None:
    if user.role in STAFF_INVITERS:
        return
    if user.role == UserRole.client_admin:
        scoped_client, _ = await client_scope(user, db)
        if scoped_client == client_id:
            return
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Недостаточно прав для приглашения в эту команду")


async def _client_or_404(client_id: uuid.UUID, user: CurrentUser, db: AsyncSession) -> Client:
    client = await db.scalar(select(Client).where(Client.id == client_id, Client.organization_id == user.organization_id))
    if not client:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Клиент не найден")
    return client


async def _create_invite(client_id: uuid.UUID, payload: ClientInviteCreate, role: UserRole,
                         user: CurrentUser, db: AsyncSession) -> ClientInviteOut:
    await _can_manage_client(user, client_id, db)
    await _client_or_404(client_id, user, db)
    site_id = payload.site_id
    if role == UserRole.client_site_user:
        if not site_id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Для менеджера выберите объект")
        site = await db.scalar(select(Site).where(Site.id == site_id, Site.client_id == client_id,
            Site.organization_id == user.organization_id, Site.is_active.is_(True)))
        if not site:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Объект не принадлежит активному клиенту")
    elif site_id is not None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Руководитель получает доступ ко всем объектам")
    raw_token = secrets.token_urlsafe(32)
    invite = ClientInvite(organization_id=user.organization_id, client_id=client_id, site_id=site_id,
        target_role=role, invited_by_user_id=user.id, invited_email=str(payload.invited_email).lower() if payload.invited_email else None,
        token_hash=_digest(raw_token), expires_at=datetime.now(timezone.utc) + timedelta(days=payload.expires_in_days))
    db.add(invite)
    db.add(AuditEvent(organization_id=user.organization_id, actor_user_id=user.id, action="invite.created",
        entity_type="client_invite", entity_id=str(invite.id), details_json={"client_id": str(client_id), "site_id": str(site_id) if site_id else None, "role": role.value}))
    await db.commit(); await db.refresh(invite)
    return _out(invite, raw_token)


@router.post("/clients/{client_id}/invites/site-manager", response_model=ClientInviteOut, status_code=status.HTTP_201_CREATED)
async def create_site_manager_invite(client_id: uuid.UUID, payload: ClientInviteCreate, db: AsyncSession = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    return await _create_invite(client_id, payload, UserRole.client_site_user, user, db)


@router.post("/clients/{client_id}/invites/director", response_model=ClientInviteOut, status_code=status.HTTP_201_CREATED)
async def create_director_invite(client_id: uuid.UUID, payload: ClientInviteCreate, db: AsyncSession = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    return await _create_invite(client_id, payload, UserRole.client_admin, user, db)


@router.get("/clients/{client_id}/invites", response_model=list[ClientInviteOut])
async def list_invites(client_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    await _can_manage_client(user, client_id, db)
    return [_out(item) for item in (await db.scalars(select(ClientInvite).where(ClientInvite.organization_id == user.organization_id, ClientInvite.client_id == client_id).order_by(ClientInvite.created_at.desc()))).all()]


@router.post("/invites/{invite_id}/revoke", response_model=ClientInviteOut)
async def revoke_invite(invite_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    invite = await db.scalar(select(ClientInvite).where(ClientInvite.id == invite_id, ClientInvite.organization_id == user.organization_id).with_for_update())
    if not invite: raise HTTPException(status.HTTP_404_NOT_FOUND, "Приглашение не найдено")
    await _can_manage_client(user, invite.client_id, db)
    if invite.status == ClientInviteStatus.pending:
        invite.status = ClientInviteStatus.revoked; invite.revoked_at = datetime.now(timezone.utc)
        db.add(AuditEvent(organization_id=user.organization_id, actor_user_id=user.id, action="invite.revoked", entity_type="client_invite", entity_id=str(invite.id), details_json={"client_id": str(invite.client_id)}))
        await db.commit(); await db.refresh(invite)
    return _out(invite)


@router.get("/invites/{invite_id}/qr", response_class=Response)
async def invite_qr(invite_id: uuid.UUID, token: str, db: AsyncSession = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    # The caller supplies the just-created raw capability; only its hash is in
    # the database, so revocation and persistence never expose it again.
    invite = await db.scalar(select(ClientInvite).where(ClientInvite.id == invite_id, ClientInvite.organization_id == user.organization_id))
    if not invite: raise HTTPException(status.HTTP_404_NOT_FOUND, "Приглашение не найдено")
    await _can_manage_client(user, invite.client_id, db)
    if not secrets.compare_digest(invite.token_hash, _digest(token)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Приглашение не найдено")
    image = qrcode.make(_join_url(token), image_factory=qrcode.image.svg.SvgPathImage, border=2)
    buffer = BytesIO(); image.save(buffer)
    return Response(buffer.getvalue(), media_type="image/svg+xml", headers={"Cache-Control": "no-store"})


async def _usable_invite(token: str, db: AsyncSession, lock: bool = False) -> ClientInvite:
    query = select(ClientInvite).where(ClientInvite.token_hash == _digest(token))
    if lock: query = query.with_for_update()
    invite = await db.scalar(query)
    now = datetime.now(timezone.utc)
    if not invite or invite.status != ClientInviteStatus.pending or invite.expires_at <= now:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Приглашение недействительно, отозвано или истекло")
    return invite


@public_router.get("/{token}")
async def inspect_invite(token: str, db: AsyncSession = Depends(get_db)):
    invite = await _usable_invite(token, db)
    client = await db.get(Client, invite.client_id)
    site = await db.get(Site, invite.site_id) if invite.site_id else None
    return {"client_name": client.legal_name or client.name, "site_name": site.name if site else None,
        "client_id": invite.client_id, "role": _role_value(invite.target_role), "expires_at": invite.expires_at, "requires_existing_login": bool(invite.invited_email)}


@public_router.post("/{token}/accept", response_model=Token)
async def accept_invite(token: str, payload: InviteAcceptRequest, db: AsyncSession = Depends(get_db)):
    invite = await _usable_invite(token, db, lock=True)
    email = str(payload.email).lower()
    if invite.invited_email and invite.invited_email.lower() != email:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Этот invite выпущен для другого email")
    user = await db.scalar(select(User).where(func.lower(User.email) == email))
    if user:
        if not verify_password(payload.password, user.hashed_password):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный пароль существующей учётной записи")
    else:
        if not payload.full_name:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Укажите ФИО для регистрации")
        user = User(full_name=payload.full_name, email=email, phone=payload.phone, role=UserRole.technician, hashed_password=hash_password(payload.password))
        db.add(user); await db.flush()
    membership = await db.scalar(select(OrganizationMembership).where(OrganizationMembership.organization_id == invite.organization_id, OrganizationMembership.user_id == user.id))
    if membership and membership.role not in {UserRole.client_admin, UserRole.client_site_user}:
        raise HTTPException(status.HTTP_409_CONFLICT, "Учётная запись уже является внутренним сотрудником этой организации")
    if not membership:
        membership = OrganizationMembership(organization_id=invite.organization_id, user_id=user.id, role=invite.target_role, is_active=True); db.add(membership)
    elif membership.role != invite.target_role:
        if membership.role == UserRole.client_site_user and invite.target_role == UserRole.client_admin:
            # Promotion is possible only through a server-issued director invite
            # for this existing client; the form can never select it.
            membership.role = UserRole.client_admin; membership.is_active = True
        else:
            raise HTTPException(status.HTTP_409_CONFLICT, "Для этой учётной записи уже назначена другая роль клиента")
    else:
        membership.is_active = True
    access_site_id = None if invite.target_role == UserRole.client_admin else invite.site_id
    access = await db.scalar(select(ClientUserAccess).where(ClientUserAccess.organization_id == invite.organization_id, ClientUserAccess.user_id == user.id, ClientUserAccess.client_id == invite.client_id, ClientUserAccess.site_id == access_site_id))
    if not access:
        db.add(ClientUserAccess(organization_id=invite.organization_id, user_id=user.id, client_id=invite.client_id, site_id=access_site_id, is_active=True))
    else:
        access.is_active = True
    invite.status = ClientInviteStatus.accepted; invite.accepted_at = datetime.now(timezone.utc); invite.accepted_by_user_id = user.id
    client = await db.get(Client, invite.client_id)
    if invite.target_role == UserRole.client_admin:
        client.adoption_status = "active"
    db.add(AuditEvent(organization_id=invite.organization_id, actor_user_id=user.id, action="invite.accepted", entity_type="client_invite", entity_id=str(invite.id), details_json={"client_id": str(invite.client_id), "role": invite.target_role.value}))
    db.add(AuditEvent(organization_id=invite.organization_id, actor_user_id=user.id, action="client.member_added", entity_type="client", entity_id=str(invite.client_id), details_json={"role": invite.target_role.value, "site_id": str(access_site_id) if access_site_id else None}))
    if invite.target_role == UserRole.client_admin:
        db.add(AuditEvent(organization_id=invite.organization_id, actor_user_id=user.id, action="client.promoted_to_active", entity_type="client", entity_id=str(invite.client_id), details_json={"reason": "director_joined"}))
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback(); raise HTTPException(status.HTTP_409_CONFLICT, "Приглашение уже принято") from exc
    return Token(access_token=create_access_token(user.id, invite.organization_id, invite.target_role.value), organization_id=invite.organization_id, role=invite.target_role)
