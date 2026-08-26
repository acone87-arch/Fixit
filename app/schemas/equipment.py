import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.core import EquipmentStatus, TaskPriority, TaskStatus


class EquipmentTypeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str


class EquipmentTypeCreate(BaseModel):
    name: str


class EquipmentBase(BaseModel):
    equipment_type_id: int
    site_id: uuid.UUID
    # Название больше не вводится пользователем: сервер берёт его из типа
    # оборудования, чтобы во всех разделах было единое обозначение.
    name: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    serial_number: str
    location: str | None = None


class EquipmentCreate(EquipmentBase):
    pass


class EquipmentUpdate(BaseModel):
    status: EquipmentStatus | None = None
    site_id: uuid.UUID | None = None


class EquipmentOut(EquipmentBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    public_qr_token: uuid.UUID
    status: EquipmentStatus
    version: int
    created_at: datetime


class RepairHistoryEntry(BaseModel):
    repair_id: uuid.UUID
    closed_at: datetime | None
    technician_name: str
    fault_type: str | None
    description: str
    parts_used: list[dict]


class EquipmentPassport(EquipmentOut):
    history: list[RepairHistoryEntry] = []


class PublicEquipmentOut(BaseModel):
    """То, что видит гость по QR — без внутреннего id и служебных полей."""

    name: str
    manufacturer: str | None
    model: str | None
    status: EquipmentStatus


class TaskBase(BaseModel):
    equipment_id: uuid.UUID
    assigned_to: uuid.UUID | None = None
    priority: TaskPriority = TaskPriority.planned
    title: str
    description: str | None = None
    due_at: datetime | None = None


class TaskCreate(TaskBase):
    pass


class TaskUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    priority: TaskPriority | None = None
    status: TaskStatus | None = None
    due_at: datetime | None = None
    assigned_to: uuid.UUID | None = None


class TaskOut(TaskBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    status: TaskStatus
    created_at: datetime
