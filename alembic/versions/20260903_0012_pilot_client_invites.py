"""Add pilot adoption status and secure client join invites."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260903_0012"
down_revision = "20260902_0011"
branch_labels = None
depends_on = None

def upgrade():
    op.execute("CREATE TYPE client_adoption_status AS ENUM ('pilot', 'active')")
    op.execute("CREATE TYPE client_invite_status AS ENUM ('pending', 'accepted', 'revoked')")
    op.add_column("clients", sa.Column("adoption_status", sa.Enum("pilot", "active", name="client_adoption_status"), nullable=False, server_default="pilot"))
    op.create_table("client_invites",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("client_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("site_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sites.id", ondelete="CASCADE"), nullable=True),
        sa.Column("target_role", sa.Enum("client_admin", "client_site_user", name="user_role", create_type=False), nullable=False),
        sa.Column("invited_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("invited_email", sa.String(length=255)), sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.Enum("pending", "accepted", "revoked", name="client_invite_status"), nullable=False, server_default="pending"),
        sa.Column("accepted_at", sa.DateTime(timezone=True)), sa.Column("accepted_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("revoked_at", sa.DateTime(timezone=True)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("token_hash", name="uq_client_invites_token_hash"),
    )
    op.create_index("ix_client_invites_organization_id", "client_invites", ["organization_id"])
    op.create_index("ix_client_invites_client_id", "client_invites", ["client_id"])
    op.create_index("ix_client_invites_site_id", "client_invites", ["site_id"])
    op.create_index("ix_client_invites_org_client", "client_invites", ["organization_id", "client_id"])

def downgrade():
    op.drop_table("client_invites")
    op.drop_column("clients", "adoption_status")
    op.execute("DROP TYPE client_invite_status")
    op.execute("DROP TYPE client_adoption_status")
