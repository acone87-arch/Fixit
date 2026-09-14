"""P0.7 readiness, full Alembic chain and production boundary contracts."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.main import health


class ReadyDatabase:
    async def execute(self, statement):
        assert str(statement) == "SELECT 1"


class FailedDatabase:
    async def execute(self, statement):
        raise RuntimeError("database unavailable")


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


def test_full_alembic_chain_and_empty_baseline_are_reproducible():
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

    schema = "release_" + uuid.uuid4().hex

    async def create_schema():
        engine = create_async_engine(url)
        async with engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        await engine.dispose()

    async def drop_schema():
        engine = create_async_engine(url)
        async with engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await engine.dispose()

    async def snapshot():
        engine = create_async_engine(
            url, connect_args={"server_settings": {"search_path": schema}}
        )
        async with engine.connect() as connection:
            revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
            tables = set(
                (
                    await connection.execute(
                        text(
                            "SELECT table_name FROM information_schema.tables "
                            "WHERE table_schema=:schema AND table_type='BASE TABLE'"
                        ),
                        {"schema": schema},
                    )
                ).scalars()
            )
        await engine.dispose()
        return revision, tables

    env = {
        **os.environ,
        "DATABASE_URL": raw_url,
        "FIXIT_MIGRATION_SCHEMA": schema,
        "SECRET_KEY": os.getenv("SECRET_KEY", "isolated-alembic-test-secret"),
    }

    def alembic(*args):
        return subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            env=env,
            capture_output=True,
            text=True,
            timeout=90,
        )

    asyncio.run(create_schema())
    try:
        first = alembic("upgrade", "head")
        assert first.returncode == 0, first.stderr
        revision, tables = asyncio.run(snapshot())
        assert revision == "20260914_0016"
        assert {"organizations", "equipment", "service_requests", "repairs", "stock_movements"} <= tables

        rollback = alembic("downgrade", "20260905_0013")
        assert rollback.returncode == 0, rollback.stderr
        forward = alembic("upgrade", "head")
        assert forward.returncode == 0, forward.stderr
        assert asyncio.run(snapshot())[0] == "20260914_0016"
    finally:
        asyncio.run(drop_schema())
