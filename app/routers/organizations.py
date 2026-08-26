from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import CurrentUser, get_current_user, require_roles
from app.database import get_db
from app.models.core import UserRole
from app.models.organization import AuditEvent, Organization, OrganizationMembership
from app.schemas.organization import OrganizationCreate, OrganizationMembershipOut, OrganizationOut

router = APIRouter(prefix="/api/organizations", tags=["organizations"])


@router.post("", response_model=OrganizationMembershipOut, status_code=status.HTTP_201_CREATED)
async def create_organization(
    payload: OrganizationCreate,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_roles(UserRole.owner)),
):
    organization = Organization(name=payload.name.strip(), slug=payload.slug)
    try:
        db.add(organization)
        await db.flush()
        db.add(OrganizationMembership(
            organization_id=organization.id, user_id=user.id, role=UserRole.owner,
        ))
        db.add(AuditEvent(
            organization_id=organization.id,
            actor_user_id=user.id,
            action="organization.created",
            entity_type="organization",
            entity_id=str(organization.id),
            details_json={"name": organization.name, "slug": organization.slug},
        ))
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Организация с таким slug уже существует") from exc
    await db.refresh(organization)
    return OrganizationMembershipOut(organization=organization, role=UserRole.owner)


@router.get("", response_model=list[OrganizationMembershipOut])
async def list_my_organizations(
    db: AsyncSession = Depends(get_db), user: CurrentUser = Depends(get_current_user),
):
    rows = (await db.execute(
        select(Organization, OrganizationMembership.role)
        .join(OrganizationMembership, OrganizationMembership.organization_id == Organization.id)
        .where(
            OrganizationMembership.user_id == user.id,
            OrganizationMembership.is_active.is_(True),
            Organization.is_active.is_(True),
        )
        .order_by(Organization.name)
    )).all()
    return [OrganizationMembershipOut(organization=organization, role=role) for organization, role in rows]


@router.get("/current", response_model=OrganizationOut)
async def current_organization(user: CurrentUser = Depends(get_current_user)):
    return user.organization
