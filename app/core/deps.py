import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_access_token
from app.database import get_db
from app.models.core import User, UserRole

# tokenUrl only documents the login endpoint for the OpenAPI/Swagger UI;
# the actual verification happens via decode_access_token below.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


async def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
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
    user = await db.get(User, uuid.UUID(payload["sub"]))
    if not user or not user.is_active:
        raise credentials_error
    return user


def require_roles(*roles: UserRole):
    """Использование: Depends(require_roles(UserRole.admin, UserRole.dispatcher)).
    Админские REST-эндпоинты у Codex были полностью без проверки роли — здесь
    это заглушка закрыта явным guard'ом на каждом маршруте, а не общим мидлваром,
    чтобы для каждого эндпоинта было видно в сигнатуре, кому он доступен."""

    async def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Недостаточно прав для этого действия")
        return user

    return checker


async def get_technician_mobile_warehouse_id(db: AsyncSession, technician_id: uuid.UUID) -> uuid.UUID:
    from app.models.warehouse import Warehouse, WarehouseType

    warehouse_id = await db.scalar(
        select(Warehouse.id).where(
            Warehouse.owner_user_id == technician_id, Warehouse.type == WarehouseType.mobile
        )
    )
    if not warehouse_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "Мобильный склад для техника не настроен")
    return warehouse_id
