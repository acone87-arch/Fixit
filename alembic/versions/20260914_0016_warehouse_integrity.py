"""Enforce positive stock movements and one mobile warehouse per technician."""
from alembic import op
import sqlalchemy as sa


revision = "20260914_0016"
down_revision = "20260910_0015"
branch_labels = None
depends_on = None


def _assert_clean_legacy_data(connection):
    invalid_movements = connection.execute(
        sa.text("SELECT count(*) FROM stock_movements WHERE quantity <= 0")
    ).scalar_one()
    invalid_repair_parts = connection.execute(
        sa.text("SELECT count(*) FROM repair_parts WHERE quantity <= 0")
    ).scalar_one()
    duplicate_mobile_owners = connection.execute(sa.text("""
        SELECT count(*) FROM (
            SELECT organization_id, owner_user_id
            FROM warehouses
            WHERE type = 'mobile' AND owner_user_id IS NOT NULL
            GROUP BY organization_id, owner_user_id
            HAVING count(*) > 1
        ) duplicates
    """)).scalar_one()
    if invalid_movements or invalid_repair_parts or duplicate_mobile_owners:
        raise RuntimeError(
            "Warehouse integrity preflight failed: reconcile legacy data before migration "
            f"(stock_movements={invalid_movements}, repair_parts={invalid_repair_parts}, "
            f"duplicate_mobile_owners={duplicate_mobile_owners})"
        )


def upgrade():
    connection = op.get_bind()
    _assert_clean_legacy_data(connection)
    op.create_check_constraint(
        "ck_stock_movement_quantity_positive", "stock_movements", "quantity > 0"
    )
    op.create_check_constraint(
        "ck_repair_part_quantity_positive", "repair_parts", "quantity > 0"
    )
    op.create_index(
        "uq_warehouse_org_mobile_owner",
        "warehouses",
        ["organization_id", "owner_user_id"],
        unique=True,
        postgresql_where=sa.text("type = 'mobile' AND owner_user_id IS NOT NULL"),
    )


def downgrade():
    op.drop_index("uq_warehouse_org_mobile_owner", table_name="warehouses")
    op.drop_constraint("ck_repair_part_quantity_positive", "repair_parts", type_="check")
    op.drop_constraint("ck_stock_movement_quantity_positive", "stock_movements", type_="check")
