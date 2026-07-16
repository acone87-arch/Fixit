from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_roles
from app.database import get_db
from app.models.core import User, UserRole
from app.schemas.repair import SyncBatchRequest, SyncBatchResponse
from app.services.sync_service import sync_one_repair

router = APIRouter(prefix="/api/v1/sync", tags=["sync"])


@router.post("/repairs", response_model=SyncBatchResponse)
async def sync_repairs(
    payload: SyncBatchRequest,
    db: AsyncSession = Depends(get_db),
    technician: User = Depends(require_roles(UserRole.technician)),
):
    """Мобильное приложение вызывает это по одному разу на весь накопленный
    офлайн-пакет при восстановлении связи (см. п. 3.2 ТЗ — "отложенная отправка").
    Каждая запись пакета обрабатывается независимо (см. sync_one_repair): один
    неудачный элемент не блокирует остальные, а часть данных, ушедшая офлайн
    неделю назад, может успешно применяться рядом с сегодняшними записями."""
    results = [await sync_one_repair(db, technician.id, item) for item in payload.repairs]
    await db.commit()
    return SyncBatchResponse(results=results)
