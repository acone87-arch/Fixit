"""AI reservations and idempotent draft results; no repair schema changes."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261019_0021"
down_revision = "20261019_0020"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("ai_generations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("service_requests.id"), nullable=False),
        sa.Column("operation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("context_hash", sa.String(64), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("prompt_version", sa.String(100), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("reserved_rub", sa.Numeric(16, 6), nullable=False),
        sa.Column("estimated_rub", sa.Numeric(16, 6)),
        sa.Column("input_tokens", sa.Integer), sa.Column("output_tokens", sa.Integer),
        sa.Column("result_json", postgresql.JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("organization_id", "user_id", "operation_id", name="uq_ai_operation"),
        sa.CheckConstraint("reserved_rub >= 0 AND (estimated_rub IS NULL OR estimated_rub >= 0)", name="ck_ai_cost_nonnegative"))
    op.create_index("ix_ai_created", "ai_generations", ["created_at"])


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM ai_generations)")):
        raise RuntimeError("AI accounting exists; preserve it instead of dropping budget history")
    op.drop_table("ai_generations")
