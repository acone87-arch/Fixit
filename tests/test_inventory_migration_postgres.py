import importlib.util

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import select, func

from app.models.core import Equipment
from test_onboarding_postgres import pg
from test_request_workflow_postgres import flow
from test_inventory_postgres import batch

pytestmark = pytest.mark.asyncio


def migration():
    spec=importlib.util.spec_from_file_location('inventory_migration','alembic/versions/20260910_0015_equipment_inventory.py')
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


async def test_inventory_upgrade_preserves_old_equipment_and_qr(flow):
    async with flow.sessions() as db:
        connection=await db.connection()
        def upgrade(sync_connection):
            with Operations.context(MigrationContext.configure(sync_connection)):
                revision=migration(); revision.downgrade(); revision.upgrade()
        await connection.run_sync(upgrade)
        await db.commit()
        assert await db.scalar(select(func.count()).select_from(Equipment))==3
        for old in flow.equipment:
            saved=await db.get(Equipment,old.id)
            assert saved.public_qr_token==old.public_qr_token and saved.serial_number==old.serial_number
            assert not saved.inventory_pending
    await batch(flow)
    async with flow.sessions() as db:
        connection=await db.connection()
        def downgrade(sync_connection):
            with Operations.context(MigrationContext.configure(sync_connection)):
                migration().downgrade()
        with pytest.raises(RuntimeError,match='Inventory batches exist'):
            await connection.run_sync(downgrade)
        await db.rollback()
        assert await db.scalar(select(func.count()).select_from(Equipment))==5


async def test_optional_serial_upgrade_and_safe_downgrade(flow):
    spec = importlib.util.spec_from_file_location('optional_serial_migration',
        'alembic/versions/20261016_0019_optional_equipment_serial.py')
    revision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision)
    async with flow.sessions() as db:
        connection = await db.connection()
        def cycle(sync_connection):
            with Operations.context(MigrationContext.configure(sync_connection)):
                revision.downgrade()
                revision.upgrade()
        await connection.run_sync(cycle)
        saved = await db.get(Equipment, flow.equipment[0].id)
        token = saved.public_qr_token
        saved.serial_number = None
        await db.commit()
        await db.refresh(saved)
        assert saved.public_qr_token == token and not saved.inventory_pending
        connection = await db.connection()
        def downgrade(sync_connection):
            with Operations.context(MigrationContext.configure(sync_connection)):
                revision.downgrade()
        with pytest.raises(RuntimeError, match='without serial numbers'):
            await connection.run_sync(downgrade)
        await db.rollback()
