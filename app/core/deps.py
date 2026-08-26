import uuid
from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_access_token
from app.database import get_db
from app.models.core import User, UserRole
from app.models.organization import Organization, OrganizationMembership

# tokenUrl only documents the login endpoint for the OpenAPI/Swagger UI;
# the actual verification happens via decode_access_token below.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


@dataclass(frozen=True)
class CurrentUser:
    user: User
    organization: Organization
    membership: OrganizationMembership

    @property
    def id(self):
        return self.user.id

    @property
    def organization_id(self):
        return self.organization.id

    @property
    def role(self):
        return self.membership.role

    def __getattr__(self, name):
        return getattr(self.user, name)


async def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> CurrentUser:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Не удалось подтвердить учётные данные",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise credentials_error
    payload = decode_access_token(token)
    if not payload or "sub" not in payload:
        raise credentials_error
    user_id = uuid.UUID(payload["sub"])
    user = await db.get(User, user_id)
    if not user or not user.is_active:
        raise credentials_error
    membership_query = select(OrganizationMembership).where(
        OrganizationMembership.user_id == user_id,
        OrganizationMembership.is_active.is_(True),
    )
    if payload.get("org"):
        membership_query = membership_query.where(
            OrganizationMembership.organization_id == uuid.UUID(payload["org"])
        )
    membership = await db.scalar(membership_query.order_by(OrganizationMembership.created_at))
    if not membership:
        raise credentials_error
    organization = await db.get(Organization, membership.organization_id)
    if not organization or not organization.is_active:
        raise credentials_error
    return CurrentUser(user=user, organization=organization, membership=membership)


def require_roles(*roles: UserRole):
    """Использование: Depends(require_roles(UserRole.admin, UserRole.dispatcher)).
    Админские REST-эндпоинты у Codex были полностью без проверки роли — здесь
    это заглушка закрыта явным guard'ом на каждом маршруте, а не общим мидлваром,
    чтобы для каждого эндпоинта было видно в сигнатуре, кому он доступен."""

    async def checker(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role != UserRole.owner and user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Недостаточно прав для этого действия")
        return user

    return checker


async def get_technician_mobile_warehouse_id(
    db: AsyncSession, technician_id: uuid.UUID, organization_id: uuid.UUID
) -> uuid.UUID:
    from app.models.warehouse import Warehouse, WarehouseType

    warehouse_id = await db.scalar(
        select(Warehouse.id).where(
            Warehouse.owner_user_id == technician_id,
            Warehouse.organization_id == organization_id,
            Warehouse.type == WarehouseType.mobile,
        )
    )
    if not warehouse_id:
        # Старые учётные записи могли быть заведены до появления мобильных
        # складов. Создаём пустой склад автоматически: при списании деталей
        # проверка остатка всё равно не даст списать то, чего на нём нет.
        technician = await db.get(User, technician_id)
        if not technician:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Техник не найден")
        warehouse = Warehouse(
            organization_id=organization_id,
            type=WarehouseType.mobile,
            name=f"Мобильный склад — {technician.full_name}",
            owner_user_id=technician_id,
        )
        db.add(warehouse)
        await db.flush()
        warehouse_id = warehouse.id
    return warehouse_id
