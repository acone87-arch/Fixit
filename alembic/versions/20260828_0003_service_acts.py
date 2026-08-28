"""Add service-act fields and attachment metadata."""

from alembic import op
import sqlalchemy as sa


revision = "20260828_0003"
down_revision = "20260826_0002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("repairs", sa.Column("labor_minutes", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("repairs", sa.Column("client_signer_name", sa.String(255), nullable=True))
    op.add_column("repairs", sa.Column("client_signed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("repair_attachments", sa.Column("kind", sa.String(30), nullable=False, server_default="document"))
    op.add_column("repair_attachments", sa.Column("original_name", sa.String(255), nullable=True))
    op.add_column("repair_attachments", sa.Column("media_type", sa.String(100), nullable=True))
    op.add_column("repair_attachments", sa.Column("byte_size", sa.Integer(), nullable=True))


def downgrade():
    op.drop_column("repair_attachments", "byte_size")
    op.drop_column("repair_attachments", "media_type")
    op.drop_column("repair_attachments", "original_name")
    op.drop_column("repair_attachments", "kind")
    op.drop_column("repairs", "client_signed_at")
    op.drop_column("repairs", "client_signer_name")
    op.drop_column("repairs", "labor_minutes")
