"""Add precise equipment location within a site."""
from alembic import op
import sqlalchemy as sa


revision = "20260928_0017"
down_revision = "20260914_0016"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("equipment", sa.Column("location_details", sa.String(length=500), nullable=True))


def downgrade():
    op.drop_column("equipment", "location_details")
