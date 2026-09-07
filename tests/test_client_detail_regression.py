"""Regression coverage for the client detail failure seen in production."""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.models.core import UserRole
from app.models.service_request import ServiceRequest
from app.routers.customers import client_summary


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _SummaryDb:
    def __init__(self, client, rows):
        self.client = client
        self.rows = rows

    async def scalar(self, _query):
        return self.client

    async def execute(self, _query):
        return _Rows(self.rows)


def _run(coro):
    return asyncio.run(coro)


def _owner(org_id):
    return SimpleNamespace(id=uuid.uuid4(), organization_id=org_id, role=UserRole.owner)


def test_chistograd_summary_handles_legacy_completed_requests_without_completed_at():
    """The production client had two completed requests migrated without dates.

    The old boolean-and expression yielded ``None`` into ``sum`` and raised
    ``TypeError: unsupported operand type(s) for +: 'int' and 'NoneType'``.
    """
    org_id, client_id = uuid.uuid4(), uuid.uuid4()
    recent = datetime.now(timezone.utc) - timedelta(days=2)
    result = _run(client_summary(
        client_id,
        _SummaryDb(SimpleNamespace(id=client_id), [
            ("completed", None, uuid.uuid4()),
            ("closed", None, uuid.uuid4()),
            ("completed", recent, uuid.uuid4()),
            ("completed", recent - timedelta(days=31), uuid.uuid4()),
        ]),
        _owner(org_id),
    ))

    assert result["completed_last_30_days"] == 1
    assert result["active_requests"] == 0


def test_client_summary_keeps_another_organization_client_hidden():
    with pytest.raises(HTTPException) as denied:
        _run(client_summary(
            uuid.uuid4(), _SummaryDb(None, []), _owner(uuid.uuid4()),
        ))

    assert denied.value.status_code == 404


def test_completed_at_orm_contract_is_timezone_aware_like_the_migration():
    assert ServiceRequest.__table__.c.completed_at.type.timezone is True


def test_client_detail_secondary_failures_do_not_replace_primary_screen():
    source = Path("app/static/app.js").read_text(encoding="utf8")
    assert "location.hash = `clients/${element.dataset.clientOpen}`" in source
    assert "await Promise.allSettled" in source
    assert "Не удалось загрузить сводку клиента" in source
    assert "clientDetailLoadError('сводку по заявкам'" in source
    assert "bindClientDetailRetry(panel, client.id, 'overview')" in source
    assert "Не удалось загрузить количество пользователей клиента" in source
    assert "Не удалось загрузить пользователей клиента" in source


def test_owner_frontend_policy_matches_service_technician_endpoints():
    source = Path("app/routers/customers.py").read_text(encoding="utf8")
    assert source.count("require_roles(UserRole.owner, UserRole.admin, UserRole.dispatcher)") >= 2
