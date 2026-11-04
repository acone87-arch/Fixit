"""AI estimates/reservations are separate from repairs and cloud invoices."""
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Index, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class AIGeneration(Base):
    __tablename__ = "ai_generations"
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", "operation_id", name="uq_ai_operation"),
        CheckConstraint("reserved_rub >= 0 AND (estimated_rub IS NULL OR estimated_rub >= 0)", name="ck_ai_cost_nonnegative"),
        Index("ix_ai_created", "created_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    request_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("service_requests.id"))
    operation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    context_hash: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(100))
    prompt_version: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    reserved_rub: Mapped[Decimal] = mapped_column(Numeric(16, 6))
    estimated_rub: Mapped[Decimal | None] = mapped_column(Numeric(16, 6))
    input_tokens: Mapped[int | None]
    output_tokens: Mapped[int | None]
    result_json: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    duration_ms: Mapped[int | None]
    applied_at: Mapped[datetime | None]
    rejected_at: Mapped[datetime | None]
    rating: Mapped[str | None] = mapped_column(String(20))
    rating_reason: Mapped[str | None] = mapped_column(String(30))
    repair_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("repairs.id", name="fk_ai_saved_repair"))
    saved_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    finished_at: Mapped[datetime | None]
