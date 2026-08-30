import asyncio
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from app.models.repair import Repair, SyncOperation
from app.models.service_request import ServiceRequest
from app.routers.client_portal import repair_for_service_request_query
from app.schemas.repair import RepairCreate
from app.services.sync_service import _SyncFailure, sync_one_repair, validate_canonical_completion


def request(**overrides):
    values = {
        "id": uuid.uuid4(),
        "organization_id": uuid.uuid4(),
        "equipment_id": uuid.uuid4(),
        "assigned_technician_id": uuid.uuid4(),
        "status": "in_progress",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_repair_persists_nullable_canonical_request_link_with_partial_uniqueness():
    columns = Repair.__table__.columns
    assert "service_request_id" in columns
    assert columns.service_request_id.nullable
    assert columns.service_request_id.foreign_keys
    indexes = {index.name: index for index in Repair.__table__.indexes}
    assert "ix_repairs_service_request_id" in indexes
    canonical_unique = indexes["uq_repair_service_request"]
    assert canonical_unique.unique
    assert str(canonical_unique.dialect_options["postgresql"]["where"]) == "service_request_id IS NOT NULL"


def test_canonical_completion_accepts_only_assigned_technician_on_matching_in_progress_request():
    item = request()
    accepted = validate_canonical_completion(
        item,
        organization_id=item.organization_id,
        technician_id=item.assigned_technician_id,
        equipment_id=item.equipment_id,
    )
    repair = Repair(
        organization_id=item.organization_id,
        local_uuid=uuid.uuid4(),
        equipment_id=item.equipment_id,
        service_request_id=accepted.id,
        technician_id=item.assigned_technician_id,
        description="Completed offline",
        device_updated_at=datetime.now(timezone.utc),
    )
    assert repair.service_request_id == item.id


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"assigned_technician_id": None}, "не назначена"),
        ({"assigned_technician_id": uuid.uuid4()}, "другому мастеру"),
        ({"equipment_id": uuid.uuid4()}, "другому оборудованию"),
        ({"organization_id": uuid.uuid4()}, "не найдена"),
        ({"status": "completed"}, "нельзя завершить"),
    ],
)
def test_canonical_completion_rejects_invalid_request_ownership_or_state(changes, expected):
    item = request()
    original_org, original_tech, original_equipment = item.organization_id, item.assigned_technician_id, item.equipment_id
    for key, value in changes.items():
        setattr(item, key, value)
    with pytest.raises(_SyncFailure, match=expected):
        validate_canonical_completion(
            item,
            organization_id=original_org,
            technician_id=original_tech,
            equipment_id=original_equipment,
        )


def test_migration_backfill_uses_only_explicit_task_or_ticket_links_not_recency_guessing():
    source = open("alembic/versions/20260830_0009_repair_service_request.py", encoding="utf8").read()
    assert "request.task_id = repair.task_id" in source
    assert "request.ticket_id = repair.ticket_id" in source
    assert "request.organization_id = repair.organization_id" in source
    assert "request.equipment_id = repair.equipment_id" in source
    assert source.count("AND NOT EXISTS") == 2
    assert "created_at" not in source
    assert "closed_at" not in source


def test_service_request_relationship_is_one_repair_for_new_canonical_rows():
    assert ServiceRequest.repairs.property.uselist
    foreign_keys = Repair.service_request.property.local_columns
    assert Repair.__table__.c.service_request_id in foreign_keys


def test_legacy_repair_without_canonical_request_link_remains_representable():
    repair = Repair(
        organization_id=uuid.uuid4(), local_uuid=uuid.uuid4(), equipment_id=uuid.uuid4(),
        technician_id=uuid.uuid4(), description="Historical Task repair",
        device_updated_at=datetime.now(timezone.utc),
    )
    assert repair.service_request_id is None


class _NestedTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class _SyncSession:
    """Small deterministic session double for the sync operation's public
    contract: it exercises the real sync function without a production DB."""

    def __init__(self, scalar_results):
        self.scalar_results = list(scalar_results)
        self.added = []

    async def scalar(self, _statement):
        return self.scalar_results.pop(0)

    def begin_nested(self):
        return _NestedTransaction()

    async def flush(self):
        return None

    def add(self, item):
        self.added.append(item)


def test_offline_sync_persists_canonical_link_and_retry_is_idempotent():
    organization_id, technician_id, equipment_id, request_id = [uuid.uuid4() for _ in range(4)]
    equipment = SimpleNamespace(id=equipment_id, version=1, status=None)
    item = request(
        id=request_id,
        organization_id=organization_id,
        equipment_id=equipment_id,
        assigned_technician_id=technician_id,
    )
    payload = RepairCreate(
        local_uuid=uuid.uuid4(), equipment_id=equipment_id, service_request_id=request_id,
        description="Completed offline", device_updated_at=datetime.now(timezone.utc),
        base_equipment_version=1,
    )
    session = _SyncSession([None, equipment, item, None])
    result = asyncio.run(sync_one_repair(session, technician_id, organization_id, payload))
    repairs = [saved for saved in session.added if isinstance(saved, Repair)]
    assert result.resolved_as == "applied"
    assert len(repairs) == 1
    assert repairs[0].service_request_id == request_id

    retry = _SyncSession([SyncOperation(
        operation_id=payload.local_uuid, organization_id=organization_id, repair_id=repairs[0].id,
        resolved_as="applied",
    )])
    retried = asyncio.run(sync_one_repair(retry, technician_id, organization_id, payload))
    assert retried.resolved_as == "already_synced"
    assert not [saved for saved in retry.added if isinstance(saved, Repair)]


def test_client_document_query_resolves_only_the_repair_linked_to_that_request():
    organization_id, request_a, request_b = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    sql_a = str(repair_for_service_request_query(organization_id, request_a).compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
    ))
    sql_b = str(repair_for_service_request_query(organization_id, request_b).compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
    ))
    assert str(request_a) in sql_a and str(request_b) not in sql_a
    assert str(request_b) in sql_b and str(request_a) not in sql_b
    assert "repairs.equipment_id" not in sql_a.split("WHERE", 1)[1]


def test_status_endpoint_cannot_mark_canonical_request_completed_without_linked_repair():
    source = open("app/routers/service_requests.py", encoding="utf8").read()
    status_handler = source.split("async def update_status", 1)[1].split("async def decide_approval", 1)[0]
    assert 'if payload.status == "completed"' in status_handler
    assert "Repair.service_request_id == request.id" in status_handler
    assert "Сначала оформите ремонт и сервисный акт" in status_handler
