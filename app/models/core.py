import enum
import uuid
from datetime import datetime

from sqlalchemy import Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base


class UserRole(str, enum.Enum):
    admin = "admin"
    dispatcher = "dispatcher"
    technician = "technician"


class EquipmentStatus(str, enum.Enum):
    working = "working"
    needs_repair = "needs_repair"
    mothballed = "mothballed"
    decommissioned = "decommissioned"


class TaskPriority(str, enum.Enum):
    urgent = "urgent"
    planned = "planned"


class TaskStatus(str, enum.Enum):
    new = "new"
    assigned = "assigned"
    in_progress = "in_progress"
    closed = "closed"
    cancelled = "cancelled"


class TicketSeverity(str, enum.Enum):
    not_working = "not_working"
    partially_working = "partially_working"


class TicketStatus(str, enum.Enum):
    new = "new"
    assigned = "assigned"
    resolved = "resolved"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    full_name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255), unique=True)
    phone: Mapped[str | None] = mapped_column(String(32))
    role: Mapped[UserRole] = mapped_column(Enum(UserRole, name="user_role"), default=UserRole.technician)
    hashed_password: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class EquipmentType(Base):
    __tablename__ = "equipment_types"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)


class Equipment(Base):
    __tablename__ = "equipment"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Отдельный от id токен для публичного QR — так по ссылке нельзя подобрать/угадать
    # внутренний идентификатор и достучаться до админских выборок по id.
    public_qr_token: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True, default=uuid.uuid4)
    equipment_type_id: Mapped[int] = mapped_column(ForeignKey("equipment_types.id"))
    name: Mapped[str] = mapped_column(String(255))
    manufacturer: Mapped[str | None] = mapped_column(String(255))
    model: Mapped[str | None] = mapped_column(String(255))
    serial_number: Mapped[str] = mapped_column(String(255), unique=True)
    status: Mapped[EquipmentStatus] = mapped_column(
        Enum(EquipmentStatus, name="equipment_status"), default=EquipmentStatus.working
    )
    location: Mapped[str | None] = mapped_column(String(255))
    # Optimistic concurrency: техник при офлайн-синке присылает версию, с которой
    # начинал работу. Если она разошлась с текущей — значит, пока он был офлайн,
    # кто-то ещё поменял оборудование (например, диспетчер или другой техник).
    # Такие ремонты сохраняются, но помечаются на ручную проверку, а не тихо перезаписываются.
    version: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    equipment_type: Mapped["EquipmentType"] = relationship()
    tasks: Mapped[list["Task"]] = relationship(back_populates="equipment")
    repairs: Mapped[list["Repair"]] = relationship(back_populates="equipment")


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    equipment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("equipment.id"))
    # Заполнено, если наряд оформлен диспетчером из гостевой заявки, а не создан вручную.
    ticket_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tickets.id"))
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    priority: Mapped[TaskPriority] = mapped_column(Enum(TaskPriority, name="task_priority"), default=TaskPriority.planned)
    status: Mapped[TaskStatus] = mapped_column(Enum(TaskStatus, name="task_status"), default=TaskStatus.new)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    due_at: Mapped[datetime | None]
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    equipment: Mapped["Equipment"] = relationship(back_populates="tasks")


class Ticket(Base):
    """Заявка от гостя (клиента на объекте), созданная через публичную QR-страницу
    оборудования — без входа в систему. Отдельно от Task: Task — это внутренний
    наряд, который диспетчер создаёт и назначает сам; Ticket — сырое обращение
    "снаружи", которое диспетчер разбирает и, при необходимости, назначает технику
    напрямую (см. assigned_technician_id) либо оформляет в полноценный Task."""

    __tablename__ = "tickets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    equipment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("equipment.id"), index=True)
    severity: Mapped[TicketSeverity] = mapped_column(Enum(TicketSeverity, name="ticket_severity"))
    symptom_tags: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    comment: Mapped[str | None] = mapped_column(Text)
    reporter_name: Mapped[str | None] = mapped_column(String(200))
    reporter_phone: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[TicketStatus] = mapped_column(Enum(TicketStatus, name="ticket_status"), default=TicketStatus.new)
    assigned_technician_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    # Ключ идемпотентности на создание: гостевая страница может отправить один и тот
    # же POST дважды (двойной тап, разрыв связи прямо на объекте) — сервер должен
    # вернуть уже созданную заявку, а не наплодить дублей.
    idempotency_key: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    equipment: Mapped["Equipment"] = relationship()
