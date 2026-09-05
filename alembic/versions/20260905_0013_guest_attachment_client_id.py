"""Make public QR problem-photo retries idempotent."""
from alembic import op
import sqlalchemy as sa


revision = "20260905_0013"
down_revision = "20260903_0012"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("service_request_attachments", sa.Column("client_id", sa.String(length=120), nullable=True))
    op.create_unique_constraint(
        "uq_request_attachment_client",
        "service_request_attachments",
        ["organization_id", "service_request_id", "client_id"],
    )


def downgrade():
    op.drop_constraint("uq_request_attachment_client", "service_request_attachments", type_="unique")
    op.drop_column("service_request_attachments", "client_id")
