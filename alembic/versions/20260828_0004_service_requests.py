"""Unified service request read model."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260828_0004"
down_revision = "20260828_0003"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("service_requests", sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False), sa.Column("number", sa.Integer(), nullable=False), sa.Column("ticket_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tickets.id"), unique=True), sa.Column("task_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tasks.id"), unique=True), sa.Column("equipment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("equipment.id"), nullable=False), sa.Column("status", sa.String(30), nullable=False), sa.Column("priority", sa.String(30), nullable=False), sa.Column("assigned_technician_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")), sa.Column("title", sa.String(255), nullable=False), sa.Column("description", sa.Text()), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()), sa.Column("completed_at", sa.DateTime(timezone=True)), sa.UniqueConstraint("organization_id", "number", name="uq_service_request_org_number"))
    op.create_index("ix_service_request_org_status", "service_requests", ["organization_id", "status"])
    op.create_table("service_request_events", sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False), sa.Column("service_request_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("service_requests.id", ondelete="CASCADE"), nullable=False), sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")), sa.Column("event_type", sa.String(60), nullable=False), sa.Column("message", sa.Text(), nullable=False), sa.Column("details_json", postgresql.JSONB()), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()))
    op.create_index("ix_service_request_event_request_created", "service_request_events", ["service_request_id", "created_at"])
    op.execute("""INSERT INTO service_requests (id, organization_id, number, ticket_id, equipment_id, status, priority, assigned_technician_id, title, description, created_at) SELECT md5('sr-ticket-' || id::text)::uuid, organization_id, row_number() over (partition by organization_id order by created_at), id, equipment_id, CASE status::text WHEN 'resolved' THEN 'completed' ELSE status::text END, CASE severity::text WHEN 'not_working' THEN 'urgent' ELSE 'planned' END, assigned_technician_id, COALESCE(comment, 'Заявка по QR'), comment, created_at FROM tickets""")
    op.execute("""UPDATE service_requests sr SET task_id = t.id, status = CASE t.status::text WHEN 'closed' THEN 'closed' WHEN 'cancelled' THEN 'cancelled' WHEN 'assigned' THEN 'assigned' ELSE sr.status END, assigned_technician_id = COALESCE(t.assigned_to, sr.assigned_technician_id) FROM tasks t WHERE t.ticket_id = sr.ticket_id""")
    op.execute("""INSERT INTO service_requests (id, organization_id, number, task_id, equipment_id, status, priority, assigned_technician_id, title, description, created_at) SELECT md5('sr-task-' || t.id::text)::uuid, t.organization_id, COALESCE((SELECT max(number) FROM service_requests x WHERE x.organization_id = t.organization_id), 0) + row_number() over (partition by t.organization_id order by t.created_at), t.id, t.equipment_id, CASE t.status::text WHEN 'closed' THEN 'closed' WHEN 'cancelled' THEN 'cancelled' WHEN 'assigned' THEN 'assigned' ELSE 'new' END, t.priority::text, t.assigned_to, t.title, t.description, t.created_at FROM tasks t WHERE t.ticket_id IS NULL""")

def downgrade():
    op.drop_table("service_request_events"); op.drop_table("service_requests")
