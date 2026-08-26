"""Add tenant-scoped clients and service sites."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260826_0002"
down_revision = "20260826_0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "clients",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("legal_name", sa.String(255), nullable=True),
        sa.Column("tax_id", sa.String(32), nullable=True),
        sa.Column("contact_name", sa.String(255), nullable=True),
        sa.Column("contact_phone", sa.String(32), nullable=True),
        sa.Column("contact_email", sa.String(255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "name", name="uq_client_org_name"),
        sa.UniqueConstraint("organization_id", "tax_id", name="uq_client_org_tax_id"),
    )
    op.create_index("ix_clients_organization_id", "clients", ["organization_id"])

    op.create_table(
        "sites",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("client_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("clients.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("address", sa.String(500), nullable=True),
        sa.Column("contact_name", sa.String(255), nullable=True),
        sa.Column("contact_phone", sa.String(32), nullable=True),
        sa.Column("contact_email", sa.String(255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "client_id", "name", name="uq_site_client_name"),
    )
    op.create_index("ix_sites_organization_id", "sites", ["organization_id"])
    op.create_index("ix_sites_client_id", "sites", ["client_id"])
    op.create_index("ix_sites_org_client", "sites", ["organization_id", "client_id"])

    # Current free-text locations are retained as first-class sites under one
    # imported client per organization, so no existing equipment is orphaned.
    op.execute("""
        INSERT INTO clients (id, organization_id, name)
        SELECT md5(e.organization_id::text || ':imported-client')::uuid,
               e.organization_id,
               'Импортированные клиенты'
        FROM equipment e
        GROUP BY e.organization_id
    """)
    op.execute("""
        WITH locations AS (
            SELECT DISTINCT
                organization_id,
                COALESCE(NULLIF(btrim(location), ''), 'Без объекта') AS site_name
            FROM equipment
        )
        INSERT INTO sites (id, organization_id, client_id, name, address)
        SELECT md5(organization_id::text || ':site:' || site_name)::uuid,
               organization_id,
               md5(organization_id::text || ':imported-client')::uuid,
               site_name,
               CASE WHEN site_name = 'Без объекта' THEN NULL ELSE site_name END
        FROM locations
    """)

    op.add_column("equipment", sa.Column("site_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.execute("""
        UPDATE equipment e
        SET site_id = md5(
            e.organization_id::text || ':site:' ||
            COALESCE(NULLIF(btrim(e.location), ''), 'Без объекта')
        )::uuid
    """)
    op.alter_column("equipment", "site_id", nullable=False)
    op.create_foreign_key("fk_equipment_site", "equipment", "sites", ["site_id"], ["id"])
    op.create_index("ix_equipment_site_id", "equipment", ["site_id"])


def downgrade():
    op.drop_index("ix_equipment_site_id", table_name="equipment")
    op.drop_constraint("fk_equipment_site", "equipment", type_="foreignkey")
    op.drop_column("equipment", "site_id")
    op.drop_table("sites")
    op.drop_table("clients")
