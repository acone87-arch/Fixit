"""Add explicit technician fleet access; no historical grants are inferred."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260831_0010"
down_revision = "20260830_0009"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("technician_client_access",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("technician_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("client_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "technician_id", "client_id", name="uq_technician_client_access"),
    )
    op.create_index("ix_technician_client_access_technician", "technician_client_access", ["organization_id", "technician_id"])
    op.create_index("ix_technician_client_access_client", "technician_client_access", ["organization_id", "client_id"])

def downgrade():
    op.drop_table("technician_client_access")
