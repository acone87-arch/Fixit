from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, verify_password
from app.database import get_db
from app.models.core import User
from app.models.organization import Organization, OrganizationMembership
from app.schemas.user import LoginRequest, Token

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=Token)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    user = await db.scalar(select(User).where(User.email == payload.email))
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
    token = create_access_token(user.id, organization.id, membership.role.value)
    return Token(access_token=token, organization_id=organization.id, role=membership.role)
