"""Allow completed equipment without a serial number."""
from alembic import op
import sqlalchemy as sa

revision = '20261016_0019'
down_revision = '20261002_0018'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint('ck_equipment_inventory_complete', 'equipment', type_='check')
    op.create_check_constraint('ck_equipment_inventory_complete', 'equipment',
                               'inventory_pending OR equipment_type_id IS NOT NULL')


def downgrade():
    # Never invent serials or erase completed cards to satisfy the old schema.
    if op.get_bind().scalar(sa.text(
        'SELECT EXISTS (SELECT 1 FROM equipment WHERE NOT inventory_pending AND serial_number IS NULL)'
    )):
        raise RuntimeError('Completed equipment without serial numbers exists; downgrade is unsafe')
    op.drop_constraint('ck_equipment_inventory_complete', 'equipment', type_='check')
    op.create_check_constraint('ck_equipment_inventory_complete', 'equipment',
                               'inventory_pending OR (equipment_type_id IS NOT NULL AND serial_number IS NOT NULL)')
