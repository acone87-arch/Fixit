"""Printed identities are independent of equipment passports."""
import uuid
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base

class QRLabel(Base):
    __tablename__ = "qr_labels"
    __table_args__ = (UniqueConstraint("batch_id", "number", name="uq_qr_label_batch_number"),)
    token: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    site_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sites.id"), index=True)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("equipment_inventory_batches.id"), index=True)
    number: Mapped[int | None] = mapped_column(Integer)
    equipment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("equipment.id"), index=True)
    legacy_equipment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("equipment.id"))
    bound_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    bind_key: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    bound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
