"""Add tenant-scoped Web Push subscriptions."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260902_0011"
down_revision = "20260831_0010"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("push_subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("endpoint", sa.String(length=2048), nullable=False),
        sa.Column("p256dh", sa.String(length=255), nullable=False),
        sa.Column("auth", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("endpoint", name="uq_push_subscription_endpoint"),
    )
    op.create_index("ix_push_subscription_organization_id", "push_subscriptions", ["organization_id"])
    op.create_index("ix_push_subscription_user_id", "push_subscriptions", ["user_id"])
    op.create_index("ix_push_subscription_user_org_active", "push_subscriptions", ["user_id", "organization_id", "is_active"])


def downgrade():
    op.drop_table("push_subscriptions")
