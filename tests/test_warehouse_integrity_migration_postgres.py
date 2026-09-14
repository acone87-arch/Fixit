import importlib.util
import uuid

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

from test_onboarding_postgres import pg

pytestmark = pytest.mark.asyncio


def migration():
    spec = importlib.util.spec_from_file_location(
        "warehouse_integrity_migration",
        "alembic/versions/20260914_0016_warehouse_integrity.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_clean_legacy_schema_upgrades_with_integrity_constraints(pg):
    async with pg.sessions() as db:
        connection = await db.connection()

        def cycle(sync_connection):
            with Operations.context(MigrationContext.configure(sync_connection)):
                revision = migration()
                revision.downgrade()
                revision.upgrade()

        await connection.run_sync(cycle)
        await db.commit()
        constraints = set((await db.execute(text("""
            SELECT conname FROM pg_constraint
            WHERE conname IN (
                'ck_stock_movement_quantity_positive',
                'ck_repair_part_quantity_positive'
            )
        """))).scalars())
        index = await db.scalar(text("""
            SELECT indexname FROM pg_indexes
            WHERE indexname = 'uq_warehouse_org_mobile_owner'
        """))
        assert constraints == {
            "ck_stock_movement_quantity_positive", "ck_repair_part_quantity_positive"
        }
        assert index == "uq_warehouse_org_mobile_owner"


async def test_migration_refuses_duplicate_legacy_mobile_warehouses(pg):
    async with pg.sessions() as db:
        connection = await db.connection()

        def downgrade(sync_connection):
            with Operations.context(MigrationContext.configure(sync_connection)):
                migration().downgrade()

        await connection.run_sync(downgrade)
        for _ in range(2):
            await db.execute(text("""
                INSERT INTO warehouses
                    (id, organization_id, type, name, owner_user_id)
                VALUES (:id, :organization_id, 'mobile', 'Legacy duplicate', :owner_user_id)
            """), {
                "id": uuid.uuid4(),
                "organization_id": pg.org.id,
                "owner_user_id": pg.tech.id,
            })

        def upgrade(sync_connection):
            with Operations.context(MigrationContext.configure(sync_connection)):
                migration().upgrade()

        with pytest.raises(RuntimeError, match="duplicate_mobile_owners=1"):
            await connection.run_sync(upgrade)
        await db.rollback()
