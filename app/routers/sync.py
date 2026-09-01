from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_roles
from app.database import get_db
from app.models.core import UserRole
from app.schemas.repair import SyncBatchRequest, SyncBatchResponse
from app.services.sync_service import sync_one_repair
from app.models.service_request import ServiceRequest
from app.services.push_service import notify_dispatchers
from sqlalchemy import select

router = APIRouter(prefix="/api/v1/sync", tags=["sync"])


@router.post("/repairs", response_model=SyncBatchResponse)
async def sync_repairs(
    payload: SyncBatchRequest,
    db: AsyncSession = Depends(get_db),
    technician=Depends(require_roles(UserRole.technician)),
):
    """Мобильное приложение вызывает это по одному разу на весь накопленный
    офлайн-пакет при восстановлении связи (см. п. 3.2 ТЗ — "отложенная отправка").
    Каждая запись пакета обрабатывается независимо (см. sync_one_repair): один
    неудачный элемент не блокирует остальные, а часть данных, ушедшая офлайн
    неделю назад, может успешно применяться рядом с сегодняшними записями."""
    results = [await sync_one_repair(db, technician.id, technician.organization_id, item) for item in payload.repairs]
    await db.commit()
    # Delivery is strictly best effort and happens only after canonical repair commit.
    for item, result in zip(payload.repairs, results):
        if item.service_request_id and result.resolved_as in {"applied", "applied_with_conflict"}:
            request = await db.scalar(select(ServiceRequest).where(ServiceRequest.id == item.service_request_id,
                ServiceRequest.organization_id == technician.organization_id))
            if request and request.status == "completed":
                await notify_dispatchers(db, request, f"SR-{request.number:05d}: техник завершил работу")
    return SyncBatchResponse(results=results)
