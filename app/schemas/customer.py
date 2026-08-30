import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ClientBase(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    legal_name: str | None = Field(default=None, max_length=255)
    tax_id: str | None = Field(default=None, max_length=32)
    contact_name: str | None = Field(default=None, max_length=255)
    contact_phone: str | None = Field(default=None, max_length=32)
    contact_email: EmailStr | None = None


class ClientCreate(ClientBase):
    pass


class ClientUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=255)
    legal_name: str | None = Field(default=None, max_length=255)
    tax_id: str | None = Field(default=None, max_length=32)
    contact_name: str | None = Field(default=None, max_length=255)
    contact_phone: str | None = Field(default=None, max_length=32)
    contact_email: EmailStr | None = None
    is_active: bool | None = None


class ClientOut(ClientBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    is_active: bool
    site_count: int = 0
    equipment_count: int = 0
    created_at: datetime


class SiteBase(BaseModel):
    client_id: uuid.UUID
    name: str = Field(min_length=2, max_length=255)
    address: str | None = Field(default=None, max_length=500)
    contact_name: str | None = Field(default=None, max_length=255)
    contact_phone: str | None = Field(default=None, max_length=32)
    contact_email: EmailStr | None = None


class SiteCreate(SiteBase):
    pass


class SiteUpdate(BaseModel):
    client_id: uuid.UUID | None = None
    name: str | None = Field(default=None, min_length=2, max_length=255)
    address: str | None = Field(default=None, max_length=500)
    contact_name: str | None = Field(default=None, max_length=255)
    contact_phone: str | None = Field(default=None, max_length=32)
    contact_email: EmailStr | None = None
    is_active: bool | None = None


class SiteOut(SiteBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    client_name: str = ""
    is_active: bool
    equipment_count: int = 0
    created_at: datetime


class ClientAccessCreate(BaseModel):
    """A human-readable client cabinet access assignment."""
    user_id: uuid.UUID
    client_id: uuid.UUID
    site_id: uuid.UUID | None = None


class ClientAccessUpdate(BaseModel):
    # An omitted field means "leave unchanged"; explicit null is meaningful
    # for a CLIENT_ADMIN whose scope is all sites of the client.
    site_id: uuid.UUID | None = None
    is_active: bool | None = None


class ClientAccessOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    full_name: str
    email: EmailStr
    role: str
    client_id: uuid.UUID
    site_id: uuid.UUID | None = None
    site_name: str | None = None
    is_active: bool


class TechnicianClientAccessUpdate(BaseModel):
    """Replacement set of technicians responsible for one service client."""
    technician_ids: list[uuid.UUID] = Field(default_factory=list)
