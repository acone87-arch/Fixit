"""Create the exact Fixit schema that existed immediately before SaaS.

The source of truth for this historical baseline is Git commit
77b37fc4f29eb6f568335815001848500aee39d3, the parent of the commit that
introduced 20260826_0001.  Keep this migration independent of current ORM
metadata: later models contain SaaS and pilot fields that do not belong here.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260825_0000"
down_revision = None
branch_labels = None
depends_on = None


ENUMS = (
    ("user_role", ("admin", "dispatcher", "technician")),
    ("equipment_status", ("working", "needs_repair", "mothballed", "decommissioned")),
    ("task_priority", ("urgent", "planned")),
    ("task_status", ("new", "assigned", "in_progress", "closed", "cancelled")),
    ("ticket_severity", ("not_working", "partially_working")),
    ("ticket_status", ("new", "assigned", "resolved")),
    ("sync_status", ("synced", "pending", "conflict")),
    ("warehouse_type", ("central", "mobile")),
    ("stock_movement_type", ("receipt", "transfer", "writeoff")),
)


def enum(name):
    return postgresql.ENUM(name=name, create_type=False)


def upgrade():
    bind = op.get_bind()
    for name, values in ENUMS:
        postgresql.ENUM(*values, name=name).create(bind, checkfirst=False)

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("phone", sa.String(32), nullable=True),
        sa.Column("role", enum("user_role"), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("email"),
    )
    op.create_table(
        "equipment_types",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "equipment",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("public_qr_token", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("equipment_type_id", sa.Integer(), sa.ForeignKey("equipment_types.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("manufacturer", sa.String(255), nullable=True),
        sa.Column("model", sa.String(255), nullable=True),
        sa.Column("serial_number", sa.String(255), nullable=False),
        sa.Column("status", enum("equipment_status"), nullable=False),
        sa.Column("location", sa.String(255), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("public_qr_token"),
        sa.UniqueConstraint("serial_number"),
    )
    op.create_table(
        "tickets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("equipment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("equipment.id"), nullable=False),
        sa.Column("severity", enum("ticket_severity"), nullable=False),
        sa.Column("symptom_tags", postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("reporter_name", sa.String(200), nullable=True),
        sa.Column("reporter_phone", sa.String(32), nullable=True),
        sa.Column("status", enum("ticket_status"), nullable=False),
        sa.Column("assigned_technician_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("idempotency_key", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index("ix_tickets_equipment_id", "tickets", ["equipment_id"])
    op.create_table(
        "tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("equipment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("equipment.id"), nullable=False),
        sa.Column("ticket_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tickets.id"), nullable=True),
        sa.Column("assigned_to", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("priority", enum("task_priority"), nullable=False),
        sa.Column("status", enum("task_status"), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "warehouses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("type", enum("warehouse_type"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("warehouses.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "parts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("article", sa.String(100), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("unit", sa.String(20), nullable=False),
        sa.Column("min_critical_qty", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("article"),
    )
    op.create_table(
        "repairs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("local_uuid", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("equipment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("equipment.id"), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tasks.id"), nullable=True),
        sa.Column("ticket_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tickets.id"), nullable=True),
        sa.Column("technician_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("fault_type", sa.String(100), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sync_status", enum("sync_status"), nullable=False),
        sa.Column("device_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("local_uuid"),
    )
    op.create_table(
        "repair_parts",
        sa.Column("repair_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("repairs.id"), primary_key=True),
        sa.Column("part_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("parts.id"), primary_key=True),
        sa.Column("quantity", sa.Integer(), nullable=False),
    )
    op.create_table(
        "repair_attachments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("repair_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("repairs.id"), nullable=False),
        sa.Column("file_url", sa.Text(), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "sync_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("device_id", sa.String(255), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("resolved_as", sa.String(50), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "sync_operations",
        sa.Column("operation_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("repair_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("repairs.id"), nullable=False),
        sa.Column("resolved_as", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "warehouse_stock",
        sa.Column("warehouse_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("warehouses.id"), primary_key=True),
        sa.Column("part_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("parts.id"), primary_key=True),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("quantity >= 0", name="chk_stock_non_negative"),
    )
    op.create_table(
        "stock_movements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("type", enum("stock_movement_type"), nullable=False),
        sa.Column("part_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("parts.id"), nullable=False),
        sa.Column("from_warehouse_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("warehouses.id"), nullable=True),
        sa.Column("to_warehouse_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("warehouses.id"), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("repair_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("repairs.id"), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade():
    for table in (
        "stock_movements",
        "warehouse_stock",
        "sync_operations",
        "sync_log",
        "repair_attachments",
        "repair_parts",
        "repairs",
        "parts",
        "warehouses",
        "tasks",
        "tickets",
        "equipment",
        "equipment_types",
        "users",
    ):
        op.drop_table(table)
    bind = op.get_bind()
    for name, values in reversed(ENUMS):
        postgresql.ENUM(*values, name=name).drop(bind, checkfirst=False)
