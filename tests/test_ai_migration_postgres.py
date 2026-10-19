import importlib.util
import os
import subprocess
import sys
import uuid

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import text

from test_ai_integration_postgres import ai_flow, generate, pg, flow

pytestmark = pytest.mark.asyncio


def revision():
    spec = importlib.util.spec_from_file_location('ai_migration', 'alembic/versions/20261019_0021_ai_generations.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_empty_migration_cycle_preserves_equipment_and_refuses_accounting_loss(ai_flow):
    f = ai_flow
    async with f.sessions() as db:
        connection = await db.connection()
        def cycle(sync):
            with Operations.context(MigrationContext.configure(sync)):
                revision().downgrade()
                revision().upgrade()
                spec = importlib.util.spec_from_file_location("ai_observations", "alembic/versions/20261019_0022_ai_pilot_observations.py")
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                module.upgrade()
        await connection.run_sync(cycle)
        await db.commit()
        assert await db.scalar(text('SELECT count(*) FROM equipment')) == 3
    assert (await generate(f)).status_code == 200
    async with f.sessions() as db:
        connection = await db.connection()
        def downgrade(sync):
            with Operations.context(MigrationContext.configure(sync)):
                revision().downgrade()
        with pytest.raises(RuntimeError, match='preserve'):
            await connection.run_sync(downgrade)
        await db.rollback()
        assert await db.scalar(text('SELECT count(*) FROM ai_generations')) == 1


async def test_full_alembic_chain_from_empty_through_inventory_0020_and_ai_0022(pg):
    schema = 'ai_chain_' + uuid.uuid4().hex
    async with pg.sessions() as db:
        await db.execute(text(f'CREATE SCHEMA "{schema}"'))
        await db.commit()
    env = {**os.environ, 'DATABASE_URL': os.environ['FIXIT_TEST_DATABASE_URL'], 'FIXIT_MIGRATION_SCHEMA': schema}
    def upgrade(target):
        result = subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', target], env=env, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr[-3000:]
    try:
        upgrade('20261016_0019')
        marker = uuid.uuid4()
        async with pg.sessions() as db:
            await db.execute(text(f'INSERT INTO "{schema}".organizations (id, name, slug, is_active) VALUES (:id, :name, :slug, true)'),
                             {'id': marker, 'name': 'Synthetic migration organization', 'slug': 'migration-ai'})
            await db.commit()
        upgrade('20261019_0020')
        upgrade('head')
        upgrade('head')
        async with pg.sessions() as db:
            assert await db.scalar(text(f'SELECT version_num FROM "{schema}".alembic_version')) == '20261019_0022'
            assert await db.scalar(text(f'SELECT count(*) FROM "{schema}".organizations WHERE id=:id'), {'id': marker}) == 1
            assert await db.scalar(text(f'SELECT count(*) FROM "{schema}".ai_generations')) == 0
    finally:
        async with pg.sessions() as db:
            await db.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            await db.commit()


async def test_observation_migration_cycle_and_refusal_to_drop_feedback(ai_flow):
    f = ai_flow
    spec = importlib.util.spec_from_file_location('ai_observations', 'alembic/versions/20261019_0022_ai_pilot_observations.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    async with f.sessions() as db:
        connection = await db.connection()
        def cycle(sync):
            with Operations.context(MigrationContext.configure(sync)):
                module.downgrade()
                module.upgrade()
        await connection.run_sync(cycle)
        await db.commit()
    assert (await generate(f)).status_code == 200
    async with f.sessions() as db:
        connection = await db.connection()
        def downgrade(sync):
            with Operations.context(MigrationContext.configure(sync)):
                module.downgrade()
        with pytest.raises(RuntimeError, match='observations exist'):
            await connection.run_sync(downgrade)
        await db.rollback()
        assert await db.scalar(text('SELECT count(*) FROM ai_generations WHERE duration_ms IS NOT NULL')) == 1
