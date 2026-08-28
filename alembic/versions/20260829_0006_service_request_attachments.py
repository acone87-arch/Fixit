"""Persist photos attached to a ServiceRequest before a Repair exists."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260829_0006"
down_revision = "20260829_0005"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "service_request_attachments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("service_request_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("service_requests.id", ondelete="CASCADE"), nullable=False),
        sa.Column("uploaded_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("kind", sa.String(30), nullable=False, server_default="other"),
        sa.Column("file_url", sa.Text(), nullable=False),
        sa.Column("original_name", sa.String(255)),
        sa.Column("media_type", sa.String(100)),
        sa.Column("byte_size", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_service_request_attachments_organization_id", "service_request_attachments", ["organization_id"])
    op.create_index("ix_service_request_attachments_service_request_id", "service_request_attachments", ["service_request_id"])
    op.create_index("ix_request_attachment_request_created", "service_request_attachments", ["service_request_id", "created_at"])


def downgrade():
    op.drop_index("ix_request_attachment_request_created", table_name="service_request_attachments")
    op.drop_index("ix_service_request_attachments_service_request_id", table_name="service_request_attachments")
    op.drop_index("ix_service_request_attachments_organization_id", table_name="service_request_attachments")
    op.drop_table("service_request_attachments")
