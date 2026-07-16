import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.warehouse import StockMovementType, WarehouseType


class PartBase(BaseModel):
    article: str
    name: str
    unit: str = "шт"
    min_critical_qty: int = 0


class PartCreate(PartBase):
    pass


class PartOut(PartBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID


class WarehouseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    type: WarehouseType
    name: str
    owner_user_id: uuid.UUID | None
    parent_id: uuid.UUID | None


class StockItem(BaseModel):
    part_id: uuid.UUID
    article: str
    name: str
    quantity: int
    min_critical_qty: int
    is_critical: bool


class StockMovementCreate(BaseModel):
    type: StockMovementType
    part_id: uuid.UUID
    from_warehouse_id: uuid.UUID | None = None
    to_warehouse_id: uuid.UUID | None = None
    quantity: int


class StockMovementOut(StockMovementCreate):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    created_at: datetime
