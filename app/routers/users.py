import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import CurrentUser, get_current_user, require_roles
from app.core.security import hash_password
from app.database import get_db
from app.models.core import User, UserRole
from app.models.organization import OrganizationMembership
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
        .where(OrganizationMembership.organization_id == current.organization_id)
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
