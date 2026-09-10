import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.core import EquipmentStatus, TaskPriority, TaskStatus


class EquipmentTypeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str


class EquipmentTypeCreate(BaseModel):
    name: str


class EquipmentBase(BaseModel):
    equipment_type_id: int | None
    site_id: uuid.UUID
    # Название больше не вводится пользователем: сервер берёт его из типа
    # оборудования, чтобы во всех разделах было единое обозначение.
    name: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    serial_number: str | None
    location: str | None = None


class EquipmentCreate(EquipmentBase):
    equipment_type_id: int
    serial_number: str = Field(min_length=1, max_length=255)


class EquipmentUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    status: EquipmentStatus | None = None
    site_id: uuid.UUID | None = None
    equipment_type_id: int | None = None
    manufacturer: str | None = Field(default=None, max_length=255)
    model: str | None = Field(default=None, max_length=255)
    serial_number: str | None = Field(default=None, min_length=1, max_length=255)
    location: str | None = Field(default=None, max_length=255)
    expected_version: int | None = Field(default=None, ge=1)


class EquipmentInventoryComplete(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    equipment_type_id: int
    manufacturer: str | None = Field(default=None, max_length=255)
    model: str | None = Field(default=None, max_length=255)
    serial_number: str = Field(min_length=1, max_length=255)
    location: str | None = Field(default=None, max_length=255)
    expected_version: int = Field(ge=1)


class EquipmentBatchCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    site_id: uuid.UUID
    quantity: int = Field(ge=1, le=500)
    idempotency_key: uuid.UUID


class EquipmentBatchOut(BaseModel):
    id: uuid.UUID
    site_id: uuid.UUID
    quantity: int
    completed: int
    pdf_url: str
    created_at: datetime


class EquipmentOut(EquipmentBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    public_qr_token: uuid.UUID
    status: EquipmentStatus
    version: int
    created_at: datetime
    inventory_pending: bool = False
    inventory_batch_id: uuid.UUID | None = None
    inventory_number: int | None = None
    primary_photo: "EquipmentPhotoOut | None" = None


class EquipmentPhotoOut(BaseModel):
    id: uuid.UUID
    original_name: str | None = None
    media_type: str | None = None
    byte_size: int | None = None
    uploaded_at: datetime | None = None
    download_url: str


class EquipmentServiceHistoryEntry(BaseModel):
    """One compact passport record, normally owned by one ServiceRequest."""

    id: str
    service_request_id: uuid.UUID | None = None
    service_request_number: int | None = None
    status: str
    occurred_at: datetime | None = None
    completed_at: datetime | None = None
    title: str
    problem: str | None = None
    work_summary: str | None = None
    cancellation_reason: str | None = None
    technician_name: str | None = None
    parts: list[dict] = []
    photos: list[dict] = []
    has_service_act: bool = False
    legacy: bool = False


class EquipmentActiveRequest(BaseModel):
    id: uuid.UUID
    number: int
    status: str
    priority: str
    title: str
    description: str | None = None
    assigned_technician_name: str | None = None
    created_at: datetime


class EquipmentTimelineEntry(BaseModel):
    id: str
    kind: str
    occurred_at: datetime | None = None
    title: str
    description: str | None = None
    request_id: uuid.UUID | None = None
    request_number: int | None = None
    repair_id: uuid.UUID | None = None
    task_id: uuid.UUID | None = None
    parts_used: list[dict] = []
    photos: list[dict] = []
    has_service_act: bool = False


class EquipmentDocumentEntry(BaseModel):
    id: str
    kind: str
    title: str
    created_at: datetime | None = None
    repair_id: uuid.UUID | None = None
    attachment_id: uuid.UUID | None = None
    media_type: str | None = None


class EquipmentPassport(EquipmentOut):
    client_name: str | None = None
    site_name: str | None = None
    site_address: str | None = None
    active_request: EquipmentActiveRequest | None = None
    timeline: list[EquipmentTimelineEntry] = []
    documents: list[EquipmentDocumentEntry] = []
    # A request appears once here; ServiceRequestEvent remains available only
    # on the request detail timeline.
    history: list[EquipmentServiceHistoryEntry] = []


class PublicEquipmentOut(BaseModel):
    """То, что видит гость по QR — без внутреннего id и служебных полей."""

    name: str
    manufacturer: str | None
    model: str | None
    serial_number: str | None
    inventory_pending: bool = False
    status: EquipmentStatus
    site_name: str | None = None
    photo_url: str | None = None


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
