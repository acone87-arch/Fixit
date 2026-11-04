"""Separate printed QR labels from equipment; retain legacy identities and data."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision = "20261104_0024"
down_revision = "20261019_0022"
branch_labels = None
depends_on = None

def upgrade():
    u = postgresql.UUID(as_uuid=True)
    op.create_table("qr_labels",
        sa.Column("token", u, primary_key=True),
        sa.Column("organization_id", u, sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("site_id", u, sa.ForeignKey("sites.id"), nullable=False),
        sa.Column("batch_id", u, sa.ForeignKey("equipment_inventory_batches.id")),
        sa.Column("number", sa.Integer()),
        sa.Column("equipment_id", u, sa.ForeignKey("equipment.id")),
        sa.Column("legacy_equipment_id", u, sa.ForeignKey("equipment.id")),
        sa.Column("bound_by_user_id", u, sa.ForeignKey("users.id")),
        sa.Column("bind_key", u),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("bound_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("batch_id", "number", name="uq_qr_label_batch_number"))
    for field in ("organization_id", "site_id", "batch_id", "equipment_id"):
        op.create_index("ix_qr_labels_" + field, "qr_labels", [field])
    # No equipment or service history is deleted. Old empty rows remain as
    # compatibility records, hidden from the equipment list, until migrated away.
    op.execute("""INSERT INTO qr_labels
        (token, organization_id, site_id, batch_id, number, equipment_id, legacy_equipment_id, created_at, bound_at)
        SELECT public_qr_token, organization_id, site_id, inventory_batch_id, inventory_number,
            CASE WHEN inventory_pending THEN NULL ELSE id END,
            CASE WHEN inventory_pending THEN id ELSE NULL END,
            created_at, CASE WHEN inventory_pending THEN NULL ELSE updated_at END
        FROM equipment""")

def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM qr_labels")):
        raise RuntimeError("QR identities must be preserved; restore a verified backup instead of dropping labels")
    op.drop_table("qr_labels")
