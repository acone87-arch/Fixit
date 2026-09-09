import uuid
from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, Field, field_validator

REQUEST_STATUSES = {"new", "assigned", "on_the_way", "arrived", "in_progress", "waiting_parts", "waiting_approval", "completed", "closed", "cancelled"}

class ApprovalPart(BaseModel):
    name: str = Field(max_length=255)
    quantity: int = Field(gt=0)


class ApprovalContext(BaseModel):
    diagnostic: str = Field(default="", max_length=10000)
    work: str = Field(default="", max_length=10000)
    comment: str = Field(default="", max_length=10000)
    parts: list[ApprovalPart] = Field(default_factory=list, max_length=100)
    photo_count: int = Field(default=0, ge=0, le=5)


class ServiceRequestStatusUpdate(BaseModel):
    status: str
    note: str | None = Field(default=None, max_length=1000)
    details: dict[str, Any] | None = None

    @field_validator("details")
    @classmethod
    def validate_approval(cls, value):
        if value is not None and "approval" in value:
            value = {**value, "approval": ApprovalContext.model_validate(value["approval"]).model_dump()}
        return value

class ServiceRequestApproval(BaseModel):
    action: Literal["approved", "rejected"]
    comment: str | None = Field(default=None, max_length=1000)


class ServiceRequestCreate(BaseModel):
    equipment_id: uuid.UUID
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    priority: Literal["planned", "urgent"] = "planned"
    assigned_technician_id: uuid.UUID | None = None


class ServiceRequestAttachmentOut(BaseModel):
    id: uuid.UUID
    kind: str
    original_name: str | None = None
    media_type: str | None = None
    byte_size: int | None = None
    created_at: datetime | None = None
    download_url: str

class ServiceRequestListItem(BaseModel):
    """The compact read model used by the request queue."""

    id: uuid.UUID
    number: int
    status: str
    priority: str
    title: str
    description: str | None
    client_name: str | None
    site_name: str | None
    equipment_name: str
    equipment_type: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    serial_number: str
    assigned_technician_id: uuid.UUID | None = None
    assigned_technician_name: str | None = None
    created_at: datetime
    completed_at: datetime | None = None


class ServiceRequestDetail(BaseModel):
    id: uuid.UUID; number: int; ticket_id: uuid.UUID | None; task_id: uuid.UUID | None; equipment_id: uuid.UUID
    title: str = ""
    client_name: str | None; site_name: str | None; equipment_name: str; serial_number: str
    description: str | None; priority: str; assigned_technician_id: uuid.UUID | None; assigned_technician_name: str | None
    status: str; created_at: datetime; completed_at: datetime | None; approval_target: str = "internal"; repair_id: uuid.UUID | None = None
    parts_used: list[dict] = []; outcome: str | None = None; history: list[dict] = []
    site_address: str | None = None; contact_name: str | None = None; contact_phone: str | None = None
    equipment_type: str | None = None; manufacturer: str | None = None; model: str | None = None; equipment_status: str | None = None; equipment_version: int | None = None
    attachments: list[dict] = []
    request_attachments: list[dict] = []
    primary_photo: dict | None = None
    repair_sync_status: str | None = None


# Keep imports in integrations backward-compatible while endpoints use explicit DTOs.
ServiceRequestOut = ServiceRequestDetail
