"""Make durable repair-photo uploads idempotent."""

from alembic import op
import sqlalchemy as sa


revision = "20260829_0007"
down_revision = "20260829_0006"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("repair_attachments", sa.Column("client_id", sa.String(length=120), nullable=True))
    op.create_unique_constraint(
        "uq_repair_attachment_client", "repair_attachments",
        ["organization_id", "repair_id", "client_id"],
    )


def downgrade():
    op.drop_constraint("uq_repair_attachment_client", "repair_attachments", type_="unique")
    op.drop_column("repair_attachments", "client_id")
