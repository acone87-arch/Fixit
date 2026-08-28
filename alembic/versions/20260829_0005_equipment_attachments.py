"""Add a tenant-scoped primary photo for equipment."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260829_0005"
down_revision = "20260828_0004"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "equipment_attachments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("equipment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("equipment.id", ondelete="CASCADE"), nullable=False),
        sa.Column("file_url", sa.Text(), nullable=False),
        sa.Column("original_name", sa.String(255)),
        sa.Column("media_type", sa.String(100)),
        sa.Column("byte_size", sa.Integer()),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("uploaded_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.UniqueConstraint("equipment_id", name="uq_equipment_attachment_primary"),
    )
    op.create_index("ix_equipment_attachments_organization_id", "equipment_attachments", ["organization_id"])
    op.create_index("ix_equipment_attachments_equipment_id", "equipment_attachments", ["equipment_id"])


def downgrade():
    op.drop_index("ix_equipment_attachments_equipment_id", table_name="equipment_attachments")
    op.drop_index("ix_equipment_attachments_organization_id", table_name="equipment_attachments")
    op.drop_table("equipment_attachments")
