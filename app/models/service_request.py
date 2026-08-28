import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class ServiceRequest(Base):
    __tablename__ = "service_requests"
    __table_args__ = (UniqueConstraint("organization_id", "number", name="uq_service_request_org_number"), Index("ix_service_request_org_status", "organization_id", "status"))
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    ticket_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tickets.id"), unique=True)
    task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tasks.id"), unique=True)
    equipment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("equipment.id"), index=True)
    status: Mapped[str] = mapped_column(String(30), default="new")
    priority: Mapped[str] = mapped_column(String(30), default="planned")
    assigned_technician_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    completed_at: Mapped[datetime | None]


class ServiceRequestEvent(Base):
    __tablename__ = "service_request_events"
    __table_args__ = (Index("ix_service_request_event_request_created", "service_request_id", "created_at"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    service_request_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("service_requests.id", ondelete="CASCADE"))
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    event_type: Mapped[str] = mapped_column(String(60))
    message: Mapped[str] = mapped_column(Text)
    details_json: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class ServiceRequestAttachment(Base):
    """Evidence attached to a request before a Repair exists (for example, approval photos)."""

    __tablename__ = "service_request_attachments"
    __table_args__ = (Index("ix_request_attachment_request_created", "service_request_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    service_request_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("service_requests.id", ondelete="CASCADE"), index=True)
    uploaded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(30), default="other")
    file_url: Mapped[str] = mapped_column(Text)
    original_name: Mapped[str | None] = mapped_column(String(255))
    media_type: Mapped[str | None] = mapped_column(String(100))
    byte_size: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
