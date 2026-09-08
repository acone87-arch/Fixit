import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import CurrentUser
from app.models.core import Equipment, UserRole
from app.models.customer import Client, ClientUserAccess, Site


CLIENT_ROLES = {UserRole.client_admin, UserRole.client_site_user}


async def client_scope(user: CurrentUser, db: AsyncSession) -> tuple[uuid.UUID, set[uuid.UUID] | None]:
    if user.role not in CLIENT_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Доступен только представителям клиента")
    rows = (await db.scalars(select(ClientUserAccess).where(
        ClientUserAccess.organization_id == user.organization_id,
        ClientUserAccess.user_id == user.id,
        ClientUserAccess.is_active.is_(True),
    ))).all()
    if not rows:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Для пользователя не назначен клиент или объект")
    client_ids = {row.client_id for row in rows}
    if len(client_ids) != 1:
        raise HTTPException(status.HTTP_409_CONFLICT, "Выберите одну клиентскую организацию для входа")
    client_id = next(iter(client_ids))
    client = await db.scalar(select(Client).where(Client.id == client_id,
        Client.organization_id == user.organization_id, Client.is_active.is_(True)))
    if not client:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Клиент недоступен")
    if user.role == UserRole.client_admin:
        if not any(row.site_id is None for row in rows):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Не назначен доступ руководителя к клиенту")
        return client_id, None
    if any(row.site_id is None for row in rows):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Менеджеру объекта требуется явный доступ к Site")
    site_ids = set((await db.scalars(select(Site.id).where(Site.id.in_({r.site_id for r in rows}),
        Site.organization_id == user.organization_id, Site.client_id == client_id, Site.is_active.is_(True)))).all())
    if not site_ids:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Нет доступа к активным объектам")
    return client_id, site_ids


async def ensure_client_equipment(equipment_id: uuid.UUID, user: CurrentUser, db: AsyncSession) -> Equipment:
    client_id, site_ids = await client_scope(user, db)
    query = select(Equipment).join(Site, Site.id == Equipment.site_id).where(
        Equipment.id == equipment_id, Equipment.organization_id == user.organization_id,
        Site.organization_id == user.organization_id, Site.client_id == client_id,
    )
    if site_ids is not None:
        query = query.where(Equipment.site_id.in_(site_ids))
    equipment = await db.scalar(query)
    if not equipment:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Оборудование не найдено")
    return equipment
