import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.core import TicketSeverity, TicketStatus


class GuestTicketCreate(BaseModel):
    """Заполняется на гостевой странице после скана QR. Без авторизации —
    поэтому строго валидируем длину/формат и требуем idempotency_key от клиента,
    чтобы повторный тап/дабл-сабмит не создал две заявки."""

    severity: TicketSeverity
    symptom_tags: list[str] = Field(min_length=1, max_length=10)
    comment: str | None = Field(default=None, max_length=2000)
    reporter_name: str | None = Field(default=None, max_length=200)
    reporter_phone: str | None = Field(default=None, max_length=32)
    idempotency_key: uuid.UUID


class TicketOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    equipment_id: uuid.UUID
    severity: TicketSeverity
    symptom_tags: list[str]
    comment: str | None
    status: TicketStatus
    assigned_technician_id: uuid.UUID | None
    created_at: datetime


class TicketCreateResult(BaseModel):
    ticket_id: uuid.UUID
    status: TicketStatus
    duplicate: bool


class TicketAssign(BaseModel):
    technician_id: uuid.UUID
