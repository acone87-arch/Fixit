import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.core.deps import CurrentUser, get_current_user, require_roles
from app.core.security import hash_password
from app.database import get_db
from app.models.core import User, UserRole
from app.models.customer import ClientInvite, ClientInviteStatus, ClientUserAccess, TechnicianClientAccess
from app.models.organization import AuditEvent, Organization, OrganizationMembership
from app.schemas.user import UserCreate, UserOut, UserUpdate
from app.services.access_changes import lock_access_changes

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("/me", response_model=UserOut)
async def read_me(user: CurrentUser = Depends(get_current_user)):
    return UserOut.model_validate(user.user).model_copy(update={"role": user.role, "organization_id": user.organization_id})


@router.get("", response_model=list[UserOut])
async def list_users(
    db: AsyncSession = Depends(get_db),
    current=Depends(require_roles(UserRole.admin, UserRole.dispatcher)),
):
    rows = (await db.execute(
        select(User, OrganizationMembership)
        .join(OrganizationMembership, OrganizationMembership.user_id == User.id)
        .where(OrganizationMembership.organization_id == current.organization_id,
               OrganizationMembership.is_active.is_(True))
        .order_by(User.full_name)
    )).all()
    return [UserOut.model_validate(user).model_copy(update={
        "role": membership.role, "organization_id": current.organization_id,
    }) for user, membership in rows]


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate,
    db: AsyncSession = Depends(get_db),
    current=Depends(require_roles(UserRole.admin, UserRole.dispatcher)),
):
    # A dispatcher may onboard only a client representative.  Creating or
    # elevating internal staff remains an administrator/owner operation.
    await lock_access_changes(db, current.organization_id, current)
    if current.role == UserRole.dispatcher and payload.role not in {UserRole.client_admin, UserRole.client_site_user}:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Диспетчер может создавать только пользователей клиента")
    existing = await db.scalar(select(User).where(func.lower(User.email) == str(payload.email).lower()))
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "Email уже зарегистрирован. Для клиента используйте приглашение и вход владельца учётной записи")
    user = User(
        full_name=payload.full_name, email=str(payload.email).lower(), phone=payload.phone,
        role=payload.role, hashed_password=hash_password(payload.password),
    )
    db.add(user)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Email уже зарегистрирован") from exc
    membership = await db.scalar(select(OrganizationMembership).where(
        OrganizationMembership.organization_id == current.organization_id,
        OrganizationMembership.user_id == user.id,
    ))
    if membership:
        raise HTTPException(status.HTTP_409_CONFLICT, "Пользователь уже состоит в организации")
    db.add(OrganizationMembership(
        organization_id=current.organization_id, user_id=user.id, role=payload.role,
    ))
    await db.commit()
    await db.refresh(user)
    return UserOut.model_validate(user).model_copy(update={"role": payload.role, "organization_id": current.organization_id})


async def _revoke_membership(db, membership, current):
    """Отзыв в одной организации не изменяет глобальную учётную запись."""
    membership.is_active = False
    await db.execute(update(ClientUserAccess).where(
        ClientUserAccess.organization_id == current.organization_id,
        ClientUserAccess.user_id == membership.user_id,
    ).values(is_active=False))
    await db.execute(delete(TechnicianClientAccess).where(
        TechnicianClientAccess.organization_id == current.organization_id,
        TechnicianClientAccess.technician_id == membership.user_id,
    ))
    await db.execute(update(ClientInvite).where(
        ClientInvite.organization_id == current.organization_id,
        ClientInvite.invited_by_user_id == membership.user_id,
        ClientInvite.status == ClientInviteStatus.pending,
    ).values(status=ClientInviteStatus.revoked, revoked_at=func.now()))


async def _ensure_can_disable(db, membership, current):
    if membership.user_id == current.id:
        raise HTTPException(status.HTTP_409_CONFLICT, "Нельзя удалить собственную учётную запись")
    elevated = (await db.scalars(select(OrganizationMembership).where(
        OrganizationMembership.organization_id == current.organization_id,
        OrganizationMembership.is_active.is_(True),
        OrganizationMembership.role.in_({UserRole.owner, UserRole.admin}),
    ).with_for_update())).all()
    if membership.is_active and membership.role in {UserRole.owner, UserRole.admin} and len(elevated) <= 1:
        raise HTTPException(status.HTTP_409_CONFLICT, "Нельзя удалить последнего администратора организации")


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: uuid.UUID,
    payload: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current=Depends(require_roles(UserRole.admin)),
):
    """Доступ управляется membership; общий профиль защищён от чужого tenant."""
    await lock_access_changes(db, current.organization_id, current)
    membership = await db.scalar(select(OrganizationMembership).where(
        OrganizationMembership.user_id == user_id,
        OrganizationMembership.organization_id == current.organization_id,
    ).with_for_update())
    if not membership:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не найден")
    user = await db.scalar(select(User).where(User.id == user_id).with_for_update())
    changes = payload.model_dump(exclude_unset=True)
    active = changes.pop("is_active", None)
    if changes and await db.scalar(select(OrganizationMembership.id).where(
        OrganizationMembership.user_id == user_id,
        OrganizationMembership.organization_id != current.organization_id,
    ).limit(1)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Общий профиль нельзя изменять из отдельной организации")
    if active is False:
        await _ensure_can_disable(db, membership, current)
        await _revoke_membership(db, membership, current)
    elif active is True:
        if not user.is_active:
            raise HTTPException(status.HTTP_409_CONFLICT, "Глобальная учётная запись отключена")
        membership.is_active = True
    for field, value in changes.items():
        if field == "full_name" and not value:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Укажите ФИО")
        setattr(user, field, value)
    await db.commit()
    await db.refresh(user)
    return UserOut.model_validate(user).model_copy(update={"role": membership.role,
        "organization_id": current.organization_id, "is_active": user.is_active and membership.is_active})


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(require_roles(UserRole.admin)),
):
    """Safely revoke a user's access without destroying operational history."""
    await lock_access_changes(db, current.organization_id, current)
    membership = await db.scalar(
        select(OrganizationMembership)
        .where(OrganizationMembership.organization_id == current.organization_id,
               OrganizationMembership.user_id == user_id,
               OrganizationMembership.is_active.is_(True))
        .with_for_update()
    )
    if not membership:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не найден")

    await _ensure_can_disable(db, membership, current)

    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не найден")

    await _revoke_membership(db, membership, current)

    db.add(AuditEvent(
        organization_id=current.organization_id,
        actor_user_id=current.id,
        action="user.deactivated",
        entity_type="user",
        entity_id=str(user_id),
        details_json={"membership_revoked": True},
    ))
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
