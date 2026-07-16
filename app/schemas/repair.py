import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.repair import SyncStatus


class RepairPartInput(BaseModel):
    part_id: uuid.UUID
    quantity: int


class RepairCreate(BaseModel):
    """Payload used both for online creation and for each item in an offline sync batch."""

    local_uuid: uuid.UUID
    equipment_id: uuid.UUID
    task_id: uuid.UUID | None = None
    ticket_id: uuid.UUID | None = None
    fault_type: str | None = None
    description: str
    started_at: datetime | None = None
    closed_at: datetime | None = None
    device_updated_at: datetime
    # Версия equipment, с которой техник начинал работу (взята из кэша на устройстве
    # в момент открытия карточки офлайн). Сервер сверяет её с текущей версией —
    # если кто-то поменял оборудование, пока техник был без связи, ремонт всё равно
    # сохранится, но будет помечен на ручную проверку диспетчером (sync_status=conflict),
    # а не молча перезапишет чужие изменения.
    base_equipment_version: int
    parts_used: list[RepairPartInput] = []


class RepairOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    local_uuid: uuid.UUID
    equipment_id: uuid.UUID
    technician_id: uuid.UUID
    fault_type: str | None
    description: str
    closed_at: datetime | None
    sync_status: SyncStatus


class SyncBatchRequest(BaseModel):
    """One request sent by the mobile app when connectivity is restored.
    device_id identifies the physical device for the sync_log audit trail."""

    device_id: str
    repairs: list[RepairCreate]


class SyncItemResult(BaseModel):
    local_uuid: uuid.UUID
    # server_id отсутствует, если синк этой конкретной записи не удался (например,
    # не хватило запчастей на мобильном складе) — остальные записи пакета при этом
    # всё равно обрабатываются, одна неудачная запись не должна блокировать весь синк.
    server_id: uuid.UUID | None = None
    resolved_as: str  # 'applied' | 'applied_with_conflict' | 'already_synced' | 'failed'
    error: str | None = None


class SyncBatchResponse(BaseModel):
    results: list[SyncItemResult]
