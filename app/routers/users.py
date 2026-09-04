import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import CurrentUser, get_current_user, require_roles
from app.core.security import hash_password
from app.database import get_db
from app.models.core import User, UserRole
from app.models.customer import ClientUserAccess, TechnicianClientAccess
from app.models.organization import AuditEvent, OrganizationMembership
from app.schemas.user import UserCreate, UserOut, UserUpdate

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
    if current.role == UserRole.dispatcher and payload.role not in {UserRole.client_admin, UserRole.client_site_user}:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Диспетчер может создавать только пользователей клиента")
    existing = await db.scalar(select(User).where(User.email == payload.email))
    user = existing or User(
        full_name=payload.full_name, email=payload.email, phone=payload.phone,
        role=payload.role, hashed_password=hash_password(payload.password),
    )
    if not existing:
        db.add(user)
        await db.flush()
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
    return user


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: uuid.UUID,
    payload: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current=Depends(require_roles(UserRole.admin)),
):
    """Updates a staff member's contact details and availability."""
    user = await db.scalar(select(User).join(
        OrganizationMembership, OrganizationMembership.user_id == User.id
    ).where(User.id == user_id, OrganizationMembership.organization_id == current.organization_id))
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не найден")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(user, field, value)
    await db.commit()
    await db.refresh(user)
    return user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(require_roles(UserRole.admin)),
):
    """Safely revoke a user's access without destroying operational history."""
    if user_id == current.id:
        raise HTTPException(status.HTTP_409_CONFLICT, "Нельзя удалить собственную учётную запись")

    membership = await db.scalar(
        select(OrganizationMembership)
        .where(OrganizationMembership.organization_id == current.organization_id,
               OrganizationMembership.user_id == user_id,
               OrganizationMembership.is_active.is_(True))
        .with_for_update()
    )
    if not membership:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не найден")

    elevated = (await db.scalars(
        select(OrganizationMembership)
        .where(OrganizationMembership.organization_id == current.organization_id,
               OrganizationMembership.is_active.is_(True),
               OrganizationMembership.role.in_({UserRole.owner, UserRole.admin}))
        .with_for_update()
    )).all()
    if membership.role in {UserRole.owner, UserRole.admin} and len(elevated) <= 1:
        raise HTTPException(status.HTTP_409_CONFLICT, "Нельзя удалить последнего администратора организации")

    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не найден")

    membership.is_active = False
    await db.execute(update(ClientUserAccess).where(
        ClientUserAccess.organization_id == current.organization_id,
        ClientUserAccess.user_id == user_id,
    ).values(is_active=False))
    await db.execute(delete(TechnicianClientAccess).where(
        TechnicianClientAccess.organization_id == current.organization_id,
        TechnicianClientAccess.technician_id == user_id,
    ))
    await db.flush()

    active_memberships = await db.scalar(select(func.count()).select_from(OrganizationMembership).where(
        OrganizationMembership.user_id == user_id,
        OrganizationMembership.is_active.is_(True),
    ))
    if not active_memberships:
        user.is_active = False

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
