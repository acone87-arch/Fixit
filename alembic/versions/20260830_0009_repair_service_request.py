"""Link canonical repairs to service requests without guessing legacy history."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260830_0009"
down_revision = "20260829_0008"
branch_labels = None
depends_on = None


def upgrade():
    # Nullable first: a Repair may predate ServiceRequest or have ambiguous
    # legacy provenance.  Those rows remain readable but intentionally unmapped.
    op.add_column("repairs", sa.Column("service_request_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_repairs_service_request",
        "repairs",
        "service_requests",
        ["service_request_id"],
        ["id"],
    )
    op.create_index("ix_repairs_service_request_id", "repairs", ["service_request_id"])

    # Deterministic priority: a matching Task is the strongest legacy link.
    # Scope and equipment agreement make the backfill safe even in a multi-
    # tenant database.  service_requests.task_id is unique, so each update maps
    # to at most one request.
    op.execute("""
        UPDATE repairs AS repair
        SET service_request_id = request.id
        FROM service_requests AS request
        WHERE repair.service_request_id IS NULL
          AND repair.task_id IS NOT NULL
          AND request.task_id = repair.task_id
          AND request.organization_id = repair.organization_id
          AND request.equipment_id = repair.equipment_id
    """)

    # Ticket is the fallback when no explicit Task relationship exists.  The
    # same tenant/equipment checks apply; ticket_id is unique on ServiceRequest.
    op.execute("""
        UPDATE repairs AS repair
        SET service_request_id = request.id
        FROM service_requests AS request
        WHERE repair.service_request_id IS NULL
          AND repair.ticket_id IS NOT NULL
          AND request.ticket_id = repair.ticket_id
          AND request.organization_id = repair.organization_id
          AND request.equipment_id = repair.equipment_id
    """)

    # PostgreSQL partial uniqueness gives the canonical workflow one repair per
    # request while allowing any number of historical NULL-linked repairs.
    op.execute("""
        CREATE UNIQUE INDEX uq_repair_service_request
        ON repairs (service_request_id)
        WHERE service_request_id IS NOT NULL
    """)


def downgrade():
    op.execute("DROP INDEX IF EXISTS uq_repair_service_request")
    op.drop_index("ix_repairs_service_request_id", table_name="repairs")
    op.drop_constraint("fk_repairs_service_request", "repairs", type_="foreignkey")
    op.drop_column("repairs", "service_request_id")
