"""Add client portal scopes and configurable approval target."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260829_0008"
down_revision = "20260829_0007"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'client_admin'")
    op.execute("ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'client_site_user'")
    op.add_column("service_requests", sa.Column("approval_target", sa.String(length=20), nullable=False, server_default="internal"))
    op.create_table(
        "client_user_access",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("client_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("site_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sites.id", ondelete="CASCADE"), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "user_id", "client_id", "site_id", name="uq_client_user_access_scope"),
    )
    op.create_index("ix_client_user_access_user", "client_user_access", ["organization_id", "user_id"])
    op.create_index("ix_client_user_access_site_id", "client_user_access", ["site_id"])


def downgrade():
    op.drop_index("ix_client_user_access_site_id", table_name="client_user_access")
    op.drop_index("ix_client_user_access_user", table_name="client_user_access")
    op.drop_table("client_user_access")
    op.drop_column("service_requests", "approval_target")
