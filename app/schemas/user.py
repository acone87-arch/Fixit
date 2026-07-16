import uuid

from pydantic import BaseModel, ConfigDict, EmailStr

from app.models.core import UserRole


class UserBase(BaseModel):
    full_name: str
    email: EmailStr
    phone: str | None = None
    role: UserRole = UserRole.technician


class UserCreate(UserBase):
    password: str


class UserOut(UserBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    is_active: bool


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
