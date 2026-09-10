"""Preprinted inventory labels refer to permanent Equipment identities."""
from alembic import op
import sqlalchemy as sa

revision = '20260910_0015'
down_revision = '20260908_0014'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('equipment_inventory_batches',
        sa.Column('id', sa.UUID(), primary_key=True),
        sa.Column('organization_id', sa.UUID(), sa.ForeignKey('organizations.id'), nullable=False),
        sa.Column('site_id', sa.UUID(), sa.ForeignKey('sites.id'), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('created_by_user_id', sa.UUID(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint('quantity BETWEEN 1 AND 500', name='ck_inventory_batch_quantity'))
    for field in ('organization_id', 'site_id'):
        op.create_index(f'ix_equipment_inventory_batches_{field}', 'equipment_inventory_batches', [field])
    op.add_column('equipment', sa.Column('inventory_pending', sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column('equipment', sa.Column('inventory_batch_id', sa.UUID(), sa.ForeignKey('equipment_inventory_batches.id')))
    op.add_column('equipment', sa.Column('inventory_number', sa.Integer()))
    op.create_index('ix_equipment_inventory_batch_id', 'equipment', ['inventory_batch_id'])
    op.alter_column('equipment', 'equipment_type_id', nullable=True)
    op.alter_column('equipment', 'serial_number', nullable=True)
    op.create_unique_constraint('uq_equipment_inventory_number', 'equipment', ['inventory_batch_id', 'inventory_number'])
    op.create_check_constraint('ck_equipment_inventory_complete', 'equipment', 'inventory_pending OR (equipment_type_id IS NOT NULL AND serial_number IS NOT NULL)')


def downgrade():
    # Never discard printed labels or guess missing serials during rollback.
    connection = op.get_bind()
    if connection.execute(sa.text('SELECT EXISTS (SELECT 1 FROM equipment_inventory_batches)')).scalar():
        raise RuntimeError('Inventory batches exist: keep schema 0015 and restore a compatible application image')
    op.alter_column('equipment', 'serial_number', nullable=False)
    op.alter_column('equipment', 'equipment_type_id', nullable=False)
    op.drop_constraint('ck_equipment_inventory_complete', 'equipment', type_='check')
    op.drop_constraint('uq_equipment_inventory_number', 'equipment', type_='unique')
    op.drop_index('ix_equipment_inventory_batch_id', table_name='equipment')
    for field in ('inventory_number', 'inventory_batch_id', 'inventory_pending'):
        op.drop_column('equipment', field)
    op.drop_table('equipment_inventory_batches')
