"""P0.7 readiness, full Alembic chain and production boundary contracts."""
import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app import models as registered_models  # noqa: F401
from app.database import Base
from app.main import health


ROOT = Path(__file__).resolve().parents[1]
LEGACY_REVISION = "20260825_0000"
HEAD_REVISION = "20260914_0016"
LEGACY_TABLES = {
    "users", "equipment_types", "equipment", "tasks", "tickets",
    "repairs", "repair_parts", "repair_attachments", "sync_log",
    "sync_operations", "warehouses", "warehouse_stock", "parts",
    "stock_movements",
}
LEGACY_ENUMS = {
    "user_role": ["admin", "dispatcher", "technician"],
    "equipment_status": ["working", "needs_repair", "mothballed", "decommissioned"],
    "task_priority": ["urgent", "planned"],
    "task_status": ["new", "assigned", "in_progress", "closed", "cancelled"],
    "ticket_severity": ["not_working", "partially_working"],
    "ticket_status": ["new", "assigned", "resolved"],
    "sync_status": ["synced", "pending", "conflict"],
    "warehouse_type": ["central", "mobile"],
    "stock_movement_type": ["receipt", "transfer", "writeoff"],
}
HEAD_TABLES = {
    "organizations", "organization_memberships", "clients", "sites",
    "equipment", "equipment_inventory_batches", "service_requests",
    "service_request_events", "service_request_attachments",
    "guest_request_receipts", "repairs", "repair_parts",
    "repair_attachments", "warehouses", "parts", "stock_movements",
}


class ReadyDatabase:
    async def execute(self, statement):
        assert str(statement) == "SELECT 1"


class FailedDatabase:
    async def execute(self, statement):
        raise RuntimeError("database unavailable")


def migration_test_url():
    raw_url = os.getenv("FIXIT_TEST_DATABASE_URL")
    if not raw_url:
        pytest.skip("FIXIT_TEST_DATABASE_URL не задан: Alembic chain не выполнен")
    url = make_url(raw_url)
    if (
        url.drivername != "postgresql+asyncpg"
        or url.host not in {"localhost", "127.0.0.1", "::1"}
        or not (url.database or "").endswith("_test")
    ):
        pytest.fail("Требуется отдельная loopback PostgreSQL БД *_test")
    return raw_url, url


async def create_schema(url, schema):
    engine = create_async_engine(url)
    async with engine.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    await engine.dispose()


async def drop_schema(url, schema):
    engine = create_async_engine(url)
    async with engine.begin() as connection:
        await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    await engine.dispose()


def migration_env(raw_url, schema):
    return {
        **os.environ,
        "DATABASE_URL": raw_url,
        "FIXIT_MIGRATION_SCHEMA": schema,
        "SECRET_KEY": os.getenv("SECRET_KEY", "isolated-alembic-test-secret"),
    }


def run_alembic(raw_url, schema, *args, config=None):
    command = [sys.executable, "-m", "alembic"]
    if config is not None:
        command.extend(["-c", str(config)])
    command.extend(args)
    return subprocess.run(
        command,
        cwd=ROOT,
        env=migration_env(raw_url, schema),
        capture_output=True,
        text=True,
        timeout=120,
    )


async def schema_snapshot(url, schema):
    engine = create_async_engine(
        url, connect_args={"server_settings": {"search_path": schema}}
    )
    async with engine.connect() as connection:
        revision = await connection.scalar(
            text(f'SELECT version_num FROM "{schema}".alembic_version')
        )
        tables = tuple(
            (
                await connection.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema=:schema AND table_type='BASE TABLE' "
                        "ORDER BY table_name"
                    ),
                    {"schema": schema},
                )
            ).scalars()
        )
        columns = tuple(
            (
                await connection.execute(
                    text(
                        "SELECT table_name, column_name, data_type, is_nullable, "
                        "COALESCE(column_default, '') FROM information_schema.columns "
                        "WHERE table_schema=:schema "
                        "ORDER BY table_name, ordinal_position"
                    ),
                    {"schema": schema},
                )
            ).tuples()
        )
        constraints = tuple(
            (
                await connection.execute(
                    text(
                        "SELECT c.relname, con.conname, con.contype, pg_get_constraintdef(con.oid) "
                        "FROM pg_constraint con JOIN pg_class c ON c.oid=con.conrelid "
                        "JOIN pg_namespace n ON n.oid=c.relnamespace "
                        "WHERE n.nspname=:schema ORDER BY c.relname, con.conname"
                    ),
                    {"schema": schema},
                )
            ).tuples()
        )
    await engine.dispose()
    return revision, tables, columns, constraints


async def legacy_enums(url, schema):
    engine = create_async_engine(url)
    async with engine.connect() as connection:
        rows = (
            await connection.execute(
                text(
                    "SELECT t.typname, e.enumlabel FROM pg_type t "
                    "JOIN pg_enum e ON e.enumtypid=t.oid "
                    "JOIN pg_namespace n ON n.oid=t.typnamespace "
                    "WHERE n.nspname=:schema ORDER BY t.typname, e.enumsortorder"
                ),
                {"schema": schema},
            )
        ).tuples()
    await engine.dispose()
    result = {}
    for name, label in rows:
        result.setdefault(name, []).append(label)
    return result


async def remove_version_marker(url, schema):
    engine = create_async_engine(url)
    async with engine.begin() as connection:
        await connection.execute(text(f'DELETE FROM "{schema}".alembic_version'))
    await engine.dispose()


async def insert_legacy_sentinels(url, schema):
    values = {
        "user_id": "10000000-0000-0000-0000-000000000001",
        "equipment_id": "20000000-0000-0000-0000-000000000001",
        "qr": "30000000-0000-0000-0000-000000000001",
        "warehouse_id": "40000000-0000-0000-0000-000000000001",
        "part_id": "50000000-0000-0000-0000-000000000001",
    }
    engine = create_async_engine(
        url, connect_args={"server_settings": {"search_path": schema}}
    )
    async with engine.begin() as connection:
        await connection.execute(text("""
            INSERT INTO users
                (id, full_name, email, phone, role, hashed_password, is_active)
            VALUES
                (:user_id, 'Legacy Admin', 'legacy@example.test', NULL,
                 'admin', 'historical-hash', true)
        """), values)
        await connection.execute(text(
            "INSERT INTO equipment_types (id, name) VALUES (7, 'Legacy Type')"
        ))
        await connection.execute(text("""
            INSERT INTO equipment
                (id, public_qr_token, equipment_type_id, name, manufacturer,
                 model, serial_number, status, location, version)
            VALUES
                (:equipment_id, :qr, 7, 'Legacy Equipment', 'Legacy Maker',
                 'L-1', 'LEGACY-SERIAL-1', 'working', 'Legacy Site', 1)
        """), values)
        await connection.execute(text("""
            INSERT INTO warehouses (id, type, name, owner_user_id, parent_id)
            VALUES (:warehouse_id, 'mobile', 'Legacy Mobile', :user_id, NULL)
        """), values)
        await connection.execute(text("""
            INSERT INTO parts (id, article, name, unit, min_critical_qty)
            VALUES (:part_id, 'LEGACY-PART', 'Legacy Part', 'шт', 1)
        """), values)
        await connection.execute(text("""
            INSERT INTO warehouse_stock (warehouse_id, part_id, quantity, version)
            VALUES (:warehouse_id, :part_id, 4, 1)
        """), values)
    await engine.dispose()


async def sentinel_state(url, schema):
    engine = create_async_engine(
        url, connect_args={"server_settings": {"search_path": schema}}
    )
    async with engine.connect() as connection:
        state = {
            "user": tuple((await connection.execute(text(
                "SELECT full_name, email FROM users WHERE email='legacy@example.test'"
            ))).one()),
            "equipment": tuple((await connection.execute(text(
                "SELECT name, serial_number, location FROM equipment "
                "WHERE serial_number='LEGACY-SERIAL-1'"
            ))).one()),
            "stock": await connection.scalar(text(
                "SELECT quantity FROM warehouse_stock ws JOIN parts p ON p.id=ws.part_id "
                "WHERE p.article='LEGACY-PART'"
            )),
            "membership": await connection.scalar(text(
                "SELECT count(*) FROM organization_memberships om "
                "JOIN users u ON u.id=om.user_id WHERE u.email='legacy@example.test'"
            )),
        }
    await engine.dispose()
    return state


def old_migration_config(tmp_path):
    old_tree = tmp_path / "old-alembic"
    shutil.copytree(ROOT / "alembic", old_tree)
    (old_tree / "versions" / "20260825_0000_legacy_baseline.py").unlink()
    foundation = old_tree / "versions" / "20260826_0001_saas_foundation.py"
    foundation.write_text(
        foundation.read_text(encoding="utf8").replace(
            'down_revision = "20260825_0000"', "down_revision = None"
        ),
        encoding="utf8",
    )
    config = tmp_path / "old-alembic.ini"
    config.write_text(
        (ROOT / "alembic.ini").read_text(encoding="utf8").replace(
            "script_location = alembic", f"script_location = {old_tree.as_posix()}"
        ),
        encoding="utf8",
    )
    return config


@pytest.mark.asyncio
async def test_health_requires_database_and_media_volume(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    unavailable_media = await health(ReadyDatabase())
    assert unavailable_media.status_code == 503
    assert json.loads(unavailable_media.body) == {"status": "unavailable"}

    (tmp_path / "uploads").mkdir()
    assert await health(ReadyDatabase()) == {"status": "ok"}

    unavailable_database = await health(FailedDatabase())
    assert unavailable_database.status_code == 503
    assert json.loads(unavailable_database.body) == {"status": "unavailable"}


def test_nginx_limit_wraps_all_application_upload_limits():
    nginx = Path("deploy/fixitpulse-https.conf").read_text(encoding="utf8")
    assert "client_max_body_size 9m;" in nginx
    for source in [
        "app/routers/equipment.py",
        "app/routers/repairs.py",
        "app/routers/service_requests.py",
        "app/routers/tickets.py",
    ]:
        content = Path(source).read_text(encoding="utf8")
        assert "1024 * 1024" in content
        assert "9 * 1024 * 1024" not in content


def test_docker_build_context_excludes_credentials_and_runtime_data():
    ignored = {
        line.strip()
        for line in (ROOT / ".dockerignore").read_text(encoding="utf8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert {
        ".git", ".env", ".env.*", "backups/", "uploads/",
        ".pytest_cache/", "*.pyc",
    } <= ignored
    compose = (ROOT / "docker-compose.prod.yml").read_text(encoding="utf8")
    assert "repair_uploads:/app/uploads" in compose


def test_full_alembic_chain_and_empty_baseline_are_reproducible():
    raw_url, url = migration_test_url()
    schema = "release_" + uuid.uuid4().hex
    asyncio.run(create_schema(url, schema))
    try:
        first = run_alembic(raw_url, schema, "upgrade", "head")
        assert first.returncode == 0, first.stderr
        revision, tables, columns, _ = asyncio.run(schema_snapshot(url, schema))
        assert revision == HEAD_REVISION
        assert HEAD_TABLES <= set(tables)
        assert set(Base.metadata.tables) <= set(tables)
        migrated_columns = {
            (table, column)
            for table, column, *_ in columns
        }
        model_columns = {
            (table.name, column.name)
            for table in Base.metadata.sorted_tables
            for column in table.columns
        }
        assert model_columns <= migrated_columns

        rollback = run_alembic(raw_url, schema, "downgrade", "20260905_0013")
        assert rollback.returncode == 0, rollback.stderr
        forward = run_alembic(raw_url, schema, "upgrade", "head")
        assert forward.returncode == 0, forward.stderr
        assert asyncio.run(schema_snapshot(url, schema))[0] == HEAD_REVISION
    finally:
        asyncio.run(drop_schema(url, schema))


def test_legacy_baseline_matches_pre_saas_git_schema():
    raw_url, url = migration_test_url()
    schema = "legacy_shape_" + uuid.uuid4().hex
    asyncio.run(create_schema(url, schema))
    try:
        result = run_alembic(raw_url, schema, "upgrade", LEGACY_REVISION)
        assert result.returncode == 0, result.stderr
        revision, tables, columns, constraints = asyncio.run(schema_snapshot(url, schema))
        assert revision == LEGACY_REVISION
        assert set(tables) == LEGACY_TABLES | {"alembic_version"}
        assert asyncio.run(legacy_enums(url, schema)) == LEGACY_ENUMS
        column_names = {(table, column) for table, column, *_ in columns}
        assert {
            ("users", "role"),
            ("equipment", "public_qr_token"),
            ("tickets", "idempotency_key"),
            ("repairs", "local_uuid"),
            ("warehouse_stock", "quantity"),
            ("stock_movements", "repair_id"),
        } <= column_names
        definitions = "\n".join(str(item) for item in constraints)
        assert "chk_stock_non_negative" in definitions
        assert "UNIQUE (email)" in definitions
        assert "UNIQUE (serial_number)" in definitions
        assert "UNIQUE (local_uuid)" in definitions
    finally:
        asyncio.run(drop_schema(url, schema))


def test_existing_old_chain_at_0016_treats_new_ancestor_as_noop(tmp_path):
    raw_url, url = migration_test_url()
    schema = "existing_0016_" + uuid.uuid4().hex
    asyncio.run(create_schema(url, schema))
    try:
        baseline = run_alembic(raw_url, schema, "upgrade", LEGACY_REVISION)
        assert baseline.returncode == 0, baseline.stderr
        asyncio.run(insert_legacy_sentinels(url, schema))
        asyncio.run(remove_version_marker(url, schema))

        old_config = old_migration_config(tmp_path)
        old_upgrade = run_alembic(
            raw_url, schema, "upgrade", "head", config=old_config
        )
        assert old_upgrade.returncode == 0, old_upgrade.stderr
        before_schema = asyncio.run(schema_snapshot(url, schema))
        before_data = asyncio.run(sentinel_state(url, schema))
        assert before_schema[0] == HEAD_REVISION

        current = run_alembic(raw_url, schema, "current")
        assert current.returncode == 0, current.stderr
        assert HEAD_REVISION in current.stdout
        no_op = run_alembic(raw_url, schema, "upgrade", "head")
        assert no_op.returncode == 0, no_op.stderr
        assert "Running upgrade" not in (no_op.stdout + no_op.stderr)
        assert LEGACY_REVISION not in (no_op.stdout + no_op.stderr)
        assert asyncio.run(schema_snapshot(url, schema)) == before_schema
        assert asyncio.run(sentinel_state(url, schema)) == before_data
    finally:
        asyncio.run(drop_schema(url, schema))


def test_unversioned_legacy_database_can_be_stamped_then_upgraded_without_data_loss():
    raw_url, url = migration_test_url()
    schema = "legacy_upgrade_" + uuid.uuid4().hex
    asyncio.run(create_schema(url, schema))
    try:
        baseline = run_alembic(raw_url, schema, "upgrade", LEGACY_REVISION)
        assert baseline.returncode == 0, baseline.stderr
        asyncio.run(insert_legacy_sentinels(url, schema))
        asyncio.run(remove_version_marker(url, schema))

        stamp = run_alembic(raw_url, schema, "stamp", LEGACY_REVISION)
        assert stamp.returncode == 0, stamp.stderr
        forward = run_alembic(raw_url, schema, "upgrade", "head")
        assert forward.returncode == 0, forward.stderr
        assert asyncio.run(schema_snapshot(url, schema))[0] == HEAD_REVISION
        assert asyncio.run(sentinel_state(url, schema)) == {
            "user": ("Legacy Admin", "legacy@example.test"),
            "equipment": ("Legacy Equipment", "LEGACY-SERIAL-1", "Legacy Site"),
            "stock": 4,
            "membership": 1,
        }
    finally:
        asyncio.run(drop_schema(url, schema))
