import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import CurrentUser, get_current_user, require_roles
from app.database import get_db
from app.models.core import Equipment, UserRole
from app.models.customer import Client, Site
from app.models.organization import AuditEvent
from app.schemas.customer import ClientCreate, ClientOut, ClientUpdate, SiteCreate, SiteOut, SiteUpdate

router = APIRouter(prefix="/api/clients", tags=["clients"])
sites_router = APIRouter(prefix="/api/sites", tags=["sites"])


def _audit(user: CurrentUser, action: str, entity_type: str, entity_id: uuid.UUID, details: dict) -> AuditEvent:
    serializable_details = {
        key: str(value) if isinstance(value, uuid.UUID) else value
        for key, value in details.items()
    }
    return AuditEvent(
        organization_id=user.organization_id,
        actor_user_id=user.id,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id),
        details_json=serializable_details,
    )


async def _commit_or_conflict(db: AsyncSession, detail: str) -> None:
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail) from exc


@router.get("", response_model=list[ClientOut])
async def list_clients(
    db: AsyncSession = Depends(get_db), user: CurrentUser = Depends(get_current_user),
):
    rows = (await db.execute(
        select(
            Client,
            func.count(func.distinct(Site.id)).label("site_count"),
            func.count(func.distinct(Equipment.id)).label("equipment_count"),
        )
        .outerjoin(Site, Site.client_id == Client.id)
        .outerjoin(Equipment, Equipment.site_id == Site.id)
        .where(Client.organization_id == user.organization_id)
        .group_by(Client.id)
        .order_by(Client.name)
    )).all()
    return [ClientOut.model_validate(client).model_copy(update={
        "site_count": site_count, "equipment_count": equipment_count,
    }) for client, site_count, equipment_count in rows]


@router.post("", response_model=ClientOut, status_code=status.HTTP_201_CREATED)
async def create_client(
    payload: ClientCreate,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_roles(UserRole.admin, UserRole.dispatcher)),
):
    client = Client(id=uuid.uuid4(), organization_id=user.organization_id, **payload.model_dump())
    db.add(client)
    db.add(_audit(user, "client.created", "client", client.id, {"name": client.name}))
    await _commit_or_conflict(db, "Клиент с таким названием или ИНН уже существует")
    await db.refresh(client)
    return ClientOut.model_validate(client)


@router.patch("/{client_id}", response_model=ClientOut)
async def update_client(
    client_id: uuid.UUID,
    payload: ClientUpdate,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_roles(UserRole.admin, UserRole.dispatcher)),
):
    client = await db.scalar(select(Client).where(
        Client.id == client_id, Client.organization_id == user.organization_id,
    ))
    if not client:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Клиент не найден")
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(client, field, value)
    db.add(_audit(user, "client.updated", "client", client.id, changes))
    await _commit_or_conflict(db, "Клиент с таким названием или ИНН уже существует")
    await db.refresh(client)
    return ClientOut.model_validate(client)


@router.delete("/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_client(
    client_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_roles(UserRole.admin)),
):
    client = await db.scalar(select(Client).where(
        Client.id == client_id, Client.organization_id == user.organization_id,
    ))
    if not client:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Клиент не найден")
    if await db.scalar(select(Site.id).where(Site.client_id == client.id).limit(1)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Сначала удалите или перенесите объекты клиента")
    await db.delete(client)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@sites_router.get("", response_model=list[SiteOut])
async def list_sites(
    client_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    query = (
        select(Site, Client.name, func.count(Equipment.id).label("equipment_count"))
        .join(Client, Client.id == Site.client_id)
        .outerjoin(Equipment, Equipment.site_id == Site.id)
        .where(Site.organization_id == user.organization_id)
        .group_by(Site.id, Client.name)
        .order_by(Client.name, Site.name)
    )
    if client_id:
        query = query.where(Site.client_id == client_id)
    rows = (await db.execute(query)).all()
    return [SiteOut.model_validate(site).model_copy(update={
        "client_name": client_name, "equipment_count": equipment_count,
    }) for site, client_name, equipment_count in rows]


@sites_router.post("", response_model=SiteOut, status_code=status.HTTP_201_CREATED)
async def create_site(
    payload: SiteCreate,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_roles(UserRole.admin, UserRole.dispatcher)),
):
    client = await db.scalar(select(Client).where(
        Client.id == payload.client_id, Client.organization_id == user.organization_id,
        Client.is_active.is_(True),
    ))
    if not client:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Активный клиент не найден")
    site = Site(id=uuid.uuid4(), organization_id=user.organization_id, **payload.model_dump())
    db.add(site)
    db.add(_audit(user, "site.created", "site", site.id, {
        "name": site.name, "client_id": str(site.client_id),
    }))
    await _commit_or_conflict(db, "Объект с таким названием уже существует у клиента")
    await db.refresh(site)
    return SiteOut.model_validate(site).model_copy(update={"client_name": client.name})


@sites_router.patch("/{site_id}", response_model=SiteOut)
async def update_site(
    site_id: uuid.UUID,
    payload: SiteUpdate,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_roles(UserRole.admin, UserRole.dispatcher)),
):
    site = await db.scalar(select(Site).where(
        Site.id == site_id, Site.organization_id == user.organization_id,
    ))
    if not site:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Объект не найден")
    changes = payload.model_dump(exclude_unset=True)
    target_client_id = changes.get("client_id", site.client_id)
    client = await db.scalar(select(Client).where(
        Client.id == target_client_id, Client.organization_id == user.organization_id,
    ))
    if not client:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Клиент не найден")
    for field, value in changes.items():
        setattr(site, field, value)
    if "name" in changes:
        await db.execute(
            Equipment.__table__.update()
            .where(Equipment.site_id == site.id)
            .values(location=site.name)
        )
    db.add(_audit(user, "site.updated", "site", site.id, changes))
    await _commit_or_conflict(db, "Объект с таким названием уже существует у клиента")
    await db.refresh(site)
    return SiteOut.model_validate(site).model_copy(update={"client_name": client.name})


@sites_router.delete("/{site_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_site(
    site_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_roles(UserRole.admin)),
):
    site = await db.scalar(select(Site).where(
        Site.id == site_id, Site.organization_id == user.organization_id,
    ))
    if not site:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Объект не найден")
    if await db.scalar(select(Equipment.id).where(Equipment.site_id == site.id).limit(1)):
        raise HTTPException(status.HTTP_409_CONFLICT, "На объекте есть оборудование — сначала перенесите его")
    await db.delete(site)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
