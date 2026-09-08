"""Миграция 0014 на PostgreSQL с существующими данными; полный Alembic chain — P0.7."""
import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import func, select, text

from app.models.core import Equipment
from app.models.service_request import GuestRequestReceipt, ServiceRequest
from test_onboarding_postgres import pg
from test_request_workflow_postgres import flow, new_request, qr, qr_body

pytestmark = pytest.mark.asyncio


def migration():
    path = Path('alembic/versions/20260908_0014_guest_request_receipts.py')
    spec = importlib.util.spec_from_file_location('request_receipts_migration', path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


async def test_upgrade_downgrade_upgrade_preserves_existing_data(flow):
    request_id = await new_request(flow)
    async with flow.sessions() as db:
        connection = await db.connection()
        def apply(sync_connection):
            with Operations.context(MigrationContext.configure(sync_connection)):
                revision = migration()
                # Fixture создала текущую metadata; приводим к предшествующей схеме.
                revision.downgrade()
                revision.upgrade()
                revision.downgrade()
                revision.upgrade()
        await connection.run_sync(apply)
        assert await db.scalar(select(func.count()).select_from(Equipment)) == 3
        assert await db.scalar(select(func.count()).select_from(ServiceRequest)) == 1
        assert await db.scalar(select(func.count()).select_from(GuestRequestReceipt)) == 0
        await db.commit()
    body = qr_body()
    first = await qr(flow, body)
    retry = await qr(flow, body)
    assert first.status_code == retry.status_code == 201
    assert first.json()['service_request_id'] == retry.json()['service_request_id'] == request_id


async def test_migration_transaction_rollback_leaves_previous_schema(flow):
    async with flow.sessions() as db:
        connection = await db.connection()
        def previous(sync_connection):
            with Operations.context(MigrationContext.configure(sync_connection)):
                migration().downgrade()
        await connection.run_sync(previous); await db.commit()
        connection = await db.connection()
        def attempted(sync_connection):
            with Operations.context(MigrationContext.configure(sync_connection)):
                migration().upgrade()
        await connection.run_sync(attempted)
        await db.rollback()  # Эмуляция ошибки следующей операции той же миграционной транзакции.
        assert await db.scalar(text("SELECT to_regclass('guest_request_receipts')")) is None
        assert await db.scalar(select(func.count()).select_from(Equipment)) == 3
