"""P0.6: warehouse quantities, durable mobile stock and atomic ledger links."""
import asyncio
import uuid

import pytest
from sqlalchemy import func, select

from app.models.repair import Repair, RepairPart
from app.models.warehouse import (
    Part, StockMovement, StockMovementType, Warehouse, WarehouseStock, WarehouseType,
)
from test_onboarding_postgres import auth, pg
from test_request_workflow_postgres import flow, new_request, repair_body, start, sync

pytestmark = pytest.mark.asyncio


async def grant_technician(f):
    response = await f.http.put(
        f"/api/clients/{f.client.id}/technicians",
        headers=auth(f.owner, f.org),
        json={"technician_ids": [str(f.tech.id)]},
    )
    assert response.status_code == 200, response.text


async def create_stock_entities(f, quantity=0, second_part=False):
    async with f.sessions() as db:
        central = Warehouse(
            organization_id=f.org.id, type=WarehouseType.central, name="Центральный"
        )
        part = Part(organization_id=f.org.id, article="WH-PART-1", name="Рабочая деталь")
        rows = [central, part]
        extra = None
        if second_part:
            extra = Part(organization_id=f.org.id, article="WH-PART-2", name="Дефицитная деталь")
            rows.append(extra)
        db.add_all(rows)
        await db.flush()
        mobile = await db.scalar(
            select(Warehouse).where(
                Warehouse.organization_id == f.org.id,
                Warehouse.owner_user_id == f.tech.id,
                Warehouse.type == WarehouseType.mobile,
            )
        )
        if not mobile:
            mobile = Warehouse(
                organization_id=f.org.id,
                type=WarehouseType.mobile,
                name="Мобильный",
                owner_user_id=f.tech.id,
            )
            db.add(mobile)
            await db.flush()
        if quantity:
            db.add(WarehouseStock(warehouse_id=mobile.id, part_id=part.id, quantity=quantity))
        await db.commit()
    return central, mobile, part, extra


async def test_new_technician_gets_one_persistent_warehouse_and_full_stock_cycle(flow):
    f = flow
    await grant_technician(f)
    headers = auth(f.tech, f.org)
    responses = await asyncio.gather(
        f.http.get("/api/warehouses/mine/stock", headers=headers),
        f.http.get("/api/warehouses/mine/stock", headers=headers),
    )
    assert all(response.status_code == 200 and response.json() == [] for response in responses)
    async with f.sessions() as db:
        mobile_rows = (
            await db.scalars(
                select(Warehouse).where(
                    Warehouse.organization_id == f.org.id,
                    Warehouse.owner_user_id == f.tech.id,
                    Warehouse.type == WarehouseType.mobile,
                )
            )
        ).all()
        assert len(mobile_rows) == 1
        mobile = mobile_rows[0]

    central, _, part, _ = await create_stock_entities(f)
    owner = auth(f.owner, f.org)
    receipt_key = str(uuid.uuid4())
    receipt = {
        "type": "receipt",
        "part_id": str(part.id),
        "to_warehouse_id": str(central.id),
        "quantity": 5,
        "idempotency_key": receipt_key,
    }
    received = await asyncio.gather(
        f.http.post("/api/warehouses/movements/receive", headers=owner, json=receipt),
        f.http.post("/api/warehouses/movements/receive", headers=owner, json=receipt),
    )
    assert all(response.status_code == 201 for response in received), [r.text for r in received]
    assert {response.json()["movement_id"] for response in received} == {receipt_key}
    assert any(response.json()["already_applied"] for response in received)

    transfer_key = str(uuid.uuid4())
    transfer = {
        "type": "transfer",
        "part_id": str(part.id),
        "from_warehouse_id": str(central.id),
        "to_warehouse_id": str(mobile.id),
        "quantity": 3,
        "idempotency_key": transfer_key,
    }
    first = await f.http.post("/api/warehouses/movements/transfer", headers=owner, json=transfer)
    retry = await f.http.post("/api/warehouses/movements/transfer", headers=owner, json=transfer)
    assert first.status_code == retry.status_code == 201
    assert first.json()["movement_id"] == retry.json()["movement_id"] == transfer_key
    assert not first.json()["already_applied"] and retry.json()["already_applied"]

    request_id = await new_request(f)
    await start(f, request_id)
    result = await sync(
        f,
        repair_body(
            f, request_id, parts_used=[{"part_id": str(part.id), "quantity": 2}]
        ),
    )
    assert result["resolved_as"] in {"applied", "applied_with_conflict"}, result
    repair_id = uuid.UUID(result["server_id"])
    async with f.sessions() as db:
        assert (await db.get(WarehouseStock, (central.id, part.id))).quantity == 2
        assert (await db.get(WarehouseStock, (mobile.id, part.id))).quantity == 1
        movements = (
            await db.scalars(select(StockMovement).order_by(StockMovement.created_at))
        ).all()
        assert [item.type for item in movements] == [
            StockMovementType.receipt, StockMovementType.transfer, StockMovementType.writeoff
        ]
        assert [item.quantity for item in movements] == [5, 3, 2]
        assert movements[-1].repair_id == repair_id
        assert (await db.get(RepairPart, (repair_id, part.id))).quantity == 2


@pytest.mark.parametrize("quantity", [0, -1])
async def test_non_positive_quantities_are_rejected_without_stock_changes(flow, quantity):
    central, mobile, part, _ = await create_stock_entities(flow, quantity=4)
    owner = auth(flow.owner, flow.org)
    for path, body in [
        ("/api/warehouses/movements/receive", {
            "type": "receipt", "part_id": str(part.id), "to_warehouse_id": str(central.id),
            "quantity": quantity, "idempotency_key": str(uuid.uuid4()),
        }),
        ("/api/warehouses/movements/transfer", {
            "type": "transfer", "part_id": str(part.id),
            "from_warehouse_id": str(mobile.id), "to_warehouse_id": str(central.id),
            "quantity": quantity, "idempotency_key": str(uuid.uuid4()),
        }),
    ]:
        response = await flow.http.post(path, headers=owner, json=body)
        assert response.status_code == 422, response.text
    bad_repair = await flow.http.post(
        "/api/v1/sync/repairs",
        headers=auth(flow.tech, flow.org),
        json={
            "device_id": "invalid-warehouse-quantity",
            "repairs": [repair_body(
                flow, str(uuid.uuid4()),
                parts_used=[{"part_id": str(part.id), "quantity": quantity}],
            )],
        },
    )
    assert bad_repair.status_code == 422
    async with flow.sessions() as db:
        assert (await db.get(WarehouseStock, (mobile.id, part.id))).quantity == 4
        assert await db.scalar(select(func.count()).select_from(StockMovement)) == 0


async def test_idempotency_key_cannot_be_reused_for_different_movement(flow):
    central, _, part, _ = await create_stock_entities(flow)
    owner = auth(flow.owner, flow.org)
    key = str(uuid.uuid4())
    body = {
        "type": "receipt", "part_id": str(part.id), "to_warehouse_id": str(central.id),
        "quantity": 2, "idempotency_key": key,
    }
    assert (await flow.http.post(
        "/api/warehouses/movements/receive", headers=owner, json=body
    )).status_code == 201
    conflict = await flow.http.post(
        "/api/warehouses/movements/receive",
        headers=owner,
        json={**body, "quantity": 3},
    )
    assert conflict.status_code == 409
    async with flow.sessions() as db:
        assert (await db.get(WarehouseStock, (central.id, part.id))).quantity == 2
        assert await db.scalar(select(func.count()).select_from(StockMovement)) == 1


async def test_concurrent_receipts_accumulate_when_stock_row_does_not_exist(flow):
    central, _, part, _ = await create_stock_entities(flow)
    owner = auth(flow.owner, flow.org)
    payloads = [
        {
            "type": "receipt",
            "part_id": str(part.id),
            "to_warehouse_id": str(central.id),
            "quantity": quantity,
            "idempotency_key": str(uuid.uuid4()),
        }
        for quantity in (2, 3)
    ]
    responses = await asyncio.gather(*(
        flow.http.post("/api/warehouses/movements/receive", headers=owner, json=payload)
        for payload in payloads
    ))
    assert all(response.status_code == 201 for response in responses), [r.text for r in responses]
    async with flow.sessions() as db:
        assert (await db.get(WarehouseStock, (central.id, part.id))).quantity == 5
        assert await db.scalar(select(func.count()).select_from(StockMovement)) == 2


async def test_two_repairs_cannot_consume_the_same_last_part(flow):
    f = flow
    await grant_technician(f)
    _, mobile, part, _ = await create_stock_entities(f, quantity=1)
    request_ids = [await new_request(f, index=i) for i in range(2)]
    for request_id in request_ids:
        await start(f, request_id)
    bodies = [
        repair_body(
            f,
            request_id,
            equipment_id=str(f.equipment[index].id),
            base_equipment_version=f.equipment[index].version,
            parts_used=[{"part_id": str(part.id), "quantity": 1}],
        )
        for index, request_id in enumerate(request_ids)
    ]
    results = await asyncio.gather(*(sync(f, body) for body in bodies))
    assert sorted(result["resolved_as"] == "failed" for result in results) == [False, True]
    async with f.sessions() as db:
        assert (await db.get(WarehouseStock, (mobile.id, part.id))).quantity == 0
        assert await db.scalar(select(func.count()).select_from(Repair)) == 1
        movement = await db.scalar(select(StockMovement))
        repair = await db.scalar(select(Repair))
        assert movement.quantity == 1 and movement.repair_id == repair.id


async def test_second_missing_part_rolls_back_repair_first_part_and_ledger(flow):
    f = flow
    await grant_technician(f)
    _, mobile, available, missing = await create_stock_entities(f, quantity=2, second_part=True)
    request_id = await new_request(f)
    await start(f, request_id)
    result = await sync(
        f,
        repair_body(
            f,
            request_id,
            parts_used=[
                {"part_id": str(available.id), "quantity": 1},
                {"part_id": str(missing.id), "quantity": 1},
            ],
        ),
    )
    assert result["resolved_as"] == "failed"
    async with f.sessions() as db:
        assert (await db.get(WarehouseStock, (mobile.id, available.id))).quantity == 2
        assert await db.scalar(select(func.count()).select_from(Repair)) == 0
        assert await db.scalar(select(func.count()).select_from(RepairPart)) == 0
        assert await db.scalar(select(func.count()).select_from(StockMovement)) == 0
