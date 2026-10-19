"""Keep site QR numbering after unused inventory cards are deleted."""
from alembic import op
import sqlalchemy as sa

revision = '20261019_0019'
down_revision = '20261002_0018'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('sites', sa.Column('inventory_last_number', sa.Integer(), nullable=False, server_default='0'))
    # Preserve every existing name and printed QR identity, including old batches
    # whose numbers restarted at one.
    op.execute('''UPDATE sites SET inventory_last_number = COALESCE(
        (SELECT MAX(e.inventory_number) FROM equipment e
         LEFT JOIN equipment_inventory_batches b ON b.id = e.inventory_batch_id
         WHERE (e.site_id = sites.id OR b.site_id = sites.id)
           AND e.organization_id = sites.organization_id), 0)''')


def downgrade():
    # Removing the watermark could reissue numbers of already deleted labels.
    if op.get_bind().execute(sa.text('SELECT EXISTS (SELECT 1 FROM sites WHERE inventory_last_number > 0)')).scalar():
        raise RuntimeError('Issued QR numbers exist: keep schema 0019 to prevent number reuse')
    op.drop_column('sites', 'inventory_last_number')
