"""Pilot observations and confirmed canonical repair provenance."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261019_0022"
down_revision = "20261019_0021"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("ai_generations", sa.Column("duration_ms", sa.Integer))
    for name in ("applied_at", "rejected_at", "saved_at"):
        op.add_column("ai_generations", sa.Column(name, sa.DateTime(timezone=True)))
    op.add_column("ai_generations", sa.Column("rating", sa.String(20)))
    op.add_column("ai_generations", sa.Column("rating_reason", sa.String(30)))
    op.add_column("ai_generations", sa.Column("repair_id", postgresql.UUID(as_uuid=True)))
    op.create_foreign_key("fk_ai_saved_repair", "ai_generations", "repairs", ["repair_id"], ["id"])


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM ai_generations WHERE duration_ms IS NOT NULL OR applied_at IS NOT NULL OR rejected_at IS NOT NULL OR rating IS NOT NULL OR repair_id IS NOT NULL)")):
        raise RuntimeError("AI pilot observations exist; preserve them instead of dropping feedback")
    op.drop_constraint("fk_ai_saved_repair", "ai_generations", type_="foreignkey")
    for name in ("duration_ms", "applied_at", "rejected_at", "saved_at", "rating", "rating_reason", "repair_id"):
        op.drop_column("ai_generations", name)
