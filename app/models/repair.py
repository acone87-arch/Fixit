import enum
import uuid
from datetime import datetime

from sqlalchemy import Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base


class SyncStatus(str, enum.Enum):
    synced = "synced"
    pending = "pending"
    conflict = "conflict"


class Repair(Base):
    __tablename__ = "repairs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Сгенерирован на устройстве техника в offline-режиме. Ключ идемпотентности при синхронизации.
    local_uuid: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True)
    equipment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("equipment.id"))
    task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tasks.id"))
    # Заполнено, если ремонт закрывает гостевую заявку напрямую, минуя оформление в Task.
    ticket_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tickets.id"))
    technician_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    fault_type: Mapped[str | None] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text)
    started_at: Mapped[datetime | None]
    closed_at: Mapped[datetime | None]
    sync_status: Mapped[SyncStatus] = mapped_column(Enum(SyncStatus, name="sync_status"), default=SyncStatus.synced)
    # Метка времени на устройстве в момент создания/правки — основа для last-write-wins.
    device_updated_at: Mapped[datetime]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    equipment: Mapped["Equipment"] = relationship(back_populates="repairs")  # noqa: F821
    parts_used: Mapped[list["RepairPart"]] = relationship(back_populates="repair", cascade="all, delete-orphan")


class RepairPart(Base):
    __tablename__ = "repair_parts"

    repair_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("repairs.id"), primary_key=True)
    part_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("parts.id"), primary_key=True)
    quantity: Mapped[int] = mapped_column(Integer)

    repair: Mapped["Repair"] = relationship(back_populates="parts_used")


class RepairAttachment(Base):
    __tablename__ = "repair_attachments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    repair_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("repairs.id"))
    file_url: Mapped[str] = mapped_column(Text)
    uploaded_at: Mapped[datetime] = mapped_column(server_default=func.now())


class SyncLog(Base):
    __tablename__ = "sync_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[str] = mapped_column(String(255))
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    entity_type: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[uuid.UUID]
    action: Mapped[str] = mapped_column(String(50))
    resolved_as: Mapped[str | None] = mapped_column(String(50))
    synced_at: Mapped[datetime] = mapped_column(server_default=func.now())


class SyncOperation(Base):
    """Идемпотентность на уровне операции синка, а не только на уровне записи.

    repairs.local_uuid уже уникален и сам по себе не даст создать дубль-ремонт,
    но при повторной отправке того же пакета (частый случай при рваной связи —
    клиент не дождался ответа и повторил запрос) INSERT просто упадёт по
    UNIQUE-констрейнту, и клиенту прилетит ошибка вместо связного ответа.
    Эта таблица — явный лог "операция already applied", позволяющий вернуть тот
    же результат синка повторно, не трогая repairs заново."""

    __tablename__ = "sync_operations"

    operation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    repair_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("repairs.id"))
    # 'applied' — принято и применено штатно;
    # 'applied_with_conflict' — принято, но версия оборудования разошлась, нужна ручная проверка;
    # (повторная отправка того же operation_id просто возвращает уже сохранённый результат)
    resolved_as: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
