import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.core import UserRole


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", min_length=2, max_length=100)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("Название должно содержать минимум 2 символа")
        return value


class OrganizationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    slug: str
    default_locale: str
    default_currency: str
    timezone: str


class MembershipOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    organization_id: uuid.UUID
    user_id: uuid.UUID
    role: UserRole
    is_active: bool


class OrganizationMembershipOut(BaseModel):
    organization: OrganizationOut
    role: UserRole
