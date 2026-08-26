"""Add organizations, memberships and tenant keys to the existing Fixit schema."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260826_0001"
down_revision = None
branch_labels = None
depends_on = None

DEFAULT_ORG_ID = "00000000-0000-0000-0000-000000000001"
TENANT_TABLES = [
    "equipment_types", "equipment", "tasks", "tickets", "repairs",
    "repair_attachments", "sync_log", "sync_operations", "warehouses",
    "parts", "stock_movements",
]


def upgrade():
    op.execute("ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'owner'")
    op.create_table(
        "organizations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("default_locale", sa.String(10), nullable=False, server_default="ru-RU"),
        sa.Column("default_currency", sa.String(3), nullable=False, server_default="RUB"),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="Asia/Yekaterinburg"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("slug"),
    )
    op.execute(sa.text("INSERT INTO organizations (id, name, slug) VALUES (:id, 'Fixit Default', 'fixit-default')").bindparams(id=DEFAULT_ORG_ID))

    user_role = postgresql.ENUM(name="user_role", create_type=False)
    op.create_table(
        "organization_memberships",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", user_role, nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "user_id", name="uq_membership_org_user"),
    )
    op.create_index("ix_membership_org", "organization_memberships", ["organization_id"])
    op.create_index("ix_membership_user", "organization_memberships", ["user_id"])
    op.execute(f"""INSERT INTO organization_memberships (id, organization_id, user_id, role)
        SELECT id, '{DEFAULT_ORG_ID}', id, role FROM users""")

    for table in TENANT_TABLES:
        op.add_column(table, sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True))
        op.execute(f"UPDATE {table} SET organization_id = '{DEFAULT_ORG_ID}'")
        op.alter_column(table, "organization_id", nullable=False)
        op.create_foreign_key(f"fk_{table}_organization", table, "organizations", ["organization_id"], ["id"])
        op.create_index(f"ix_{table}_organization_id", table, ["organization_id"])

    op.execute("ALTER TABLE equipment_types DROP CONSTRAINT IF EXISTS equipment_types_name_key")
    op.execute("ALTER TABLE equipment DROP CONSTRAINT IF EXISTS equipment_serial_number_key")
    op.execute("ALTER TABLE parts DROP CONSTRAINT IF EXISTS parts_article_key")
    op.execute("ALTER TABLE tickets DROP CONSTRAINT IF EXISTS tickets_idempotency_key_key")
    op.create_unique_constraint("uq_equipment_type_org_name", "equipment_types", ["organization_id", "name"])
    op.create_unique_constraint("uq_equipment_org_serial", "equipment", ["organization_id", "serial_number"])
    op.create_unique_constraint("uq_part_org_article", "parts", ["organization_id", "article"])
    op.create_unique_constraint("uq_ticket_org_idempotency", "tickets", ["organization_id", "idempotency_key"])

    op.create_table(
        "audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("entity_type", sa.String(100), nullable=False),
        sa.Column("entity_id", sa.String(100), nullable=True),
        sa.Column("details_json", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_audit_events_org_created", "audit_events", ["organization_id", "created_at"])


def downgrade():
    op.drop_table("audit_events")
    op.drop_constraint("uq_ticket_org_idempotency", "tickets", type_="unique")
    op.drop_constraint("uq_part_org_article", "parts", type_="unique")
    op.drop_constraint("uq_equipment_org_serial", "equipment", type_="unique")
    op.drop_constraint("uq_equipment_type_org_name", "equipment_types", type_="unique")
    op.create_unique_constraint("parts_article_key", "parts", ["article"])
    op.create_unique_constraint("equipment_serial_number_key", "equipment", ["serial_number"])
    op.create_unique_constraint("equipment_types_name_key", "equipment_types", ["name"])
    op.create_unique_constraint("tickets_idempotency_key_key", "tickets", ["idempotency_key"])
    for table in reversed(TENANT_TABLES):
        op.drop_index(f"ix_{table}_organization_id", table_name=table)
        op.drop_constraint(f"fk_{table}_organization", table, type_="foreignkey")
        op.drop_column(table, "organization_id")
    op.drop_table("organization_memberships")
    op.drop_table("organizations")
