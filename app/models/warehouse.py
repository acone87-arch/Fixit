import enum
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base


class WarehouseType(str, enum.Enum):
    central = "central"
    mobile = "mobile"


class StockMovementType(str, enum.Enum):
    receipt = "receipt"
    transfer = "transfer"
    writeoff = "writeoff"


class Warehouse(Base):
    __tablename__ = "warehouses"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    type: Mapped[WarehouseType] = mapped_column(Enum(WarehouseType, name="warehouse_type"))
    name: Mapped[str] = mapped_column(String(255))
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("warehouses.id"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Part(Base):
    __tablename__ = "parts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    article: Mapped[str] = mapped_column(String(100), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    unit: Mapped[str] = mapped_column(String(20), default="шт")
    min_critical_qty: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class WarehouseStock(Base):
    __tablename__ = "warehouse_stock"
    __table_args__ = (CheckConstraint("quantity >= 0", name="chk_stock_non_negative"),)

    warehouse_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("warehouses.id"), primary_key=True)
    part_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("parts.id"), primary_key=True)
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    # Bump'ается при каждом изменении остатка. Само списание всё равно защищено
    # блокировкой строки (SELECT ... FOR UPDATE, см. services/stock_service.py) —
    # версия тут скорее для админ-панели/аудита, чем единственная линия защиты.
    version: Mapped[int] = mapped_column(default=1)
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    part: Mapped["Part"] = relationship()


class StockMovement(Base):
    __tablename__ = "stock_movements"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    type: Mapped[StockMovementType] = mapped_column(Enum(StockMovementType, name="stock_movement_type"))
    part_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("parts.id"))
    from_warehouse_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("warehouses.id"))
    to_warehouse_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("warehouses.id"))
    quantity: Mapped[int] = mapped_column(Integer)
    repair_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("repairs.id"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
