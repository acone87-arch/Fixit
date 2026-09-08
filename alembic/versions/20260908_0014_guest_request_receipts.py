"""Сохранять результат каждого QR submit, включая повтор активной заявки."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '20260908_0014'
down_revision = '20260905_0013'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('guest_request_receipts',
        sa.Column('organization_id', sa.UUID(), sa.ForeignKey('organizations.id'), primary_key=True),
        sa.Column('idempotency_key', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('service_request_id', sa.UUID(), sa.ForeignKey('service_requests.id'), nullable=False))
    op.create_index('ix_guest_request_receipts_service_request_id', 'guest_request_receipts', ['service_request_id'])
    # Исторические ключи продолжают читаться из Ticket. Переносить их не нужно.


def downgrade():
    # После запуска нового кода rollback приложения сохраняет эту таблицу.
    # Downgrade удалит ключи повторных QR: выполнять только до приёма новых данных.
    op.drop_index('ix_guest_request_receipts_service_request_id', table_name='guest_request_receipts')
    op.drop_table('guest_request_receipts')
