import uuid
from datetime import datetime
from pydantic import BaseModel, Field

REQUEST_STATUSES = {"new", "assigned", "on_the_way", "in_progress", "waiting_parts", "waiting_approval", "completed", "closed", "cancelled"}

class ServiceRequestStatusUpdate(BaseModel):
    status: str
    note: str | None = Field(default=None, max_length=1000)

class ServiceRequestOut(BaseModel):
    id: uuid.UUID; number: int; ticket_id: uuid.UUID | None; task_id: uuid.UUID | None; equipment_id: uuid.UUID
    client_name: str | None; site_name: str | None; equipment_name: str; serial_number: str
    description: str | None; priority: str; assigned_technician_id: uuid.UUID | None; assigned_technician_name: str | None
    status: str; created_at: datetime; completed_at: datetime | None; repair_id: uuid.UUID | None = None
    parts_used: list[dict] = []; outcome: str | None = None; history: list[dict] = []
