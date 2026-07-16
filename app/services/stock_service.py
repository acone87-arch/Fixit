import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.warehouse import StockMovement, StockMovementType, WarehouseStock


class InsufficientStockError(Exception):
    def __init__(self, part_id: uuid.UUID, available: int, requested: int):
        self.part_id = part_id
        self.available = available
        self.requested = requested


async def _lock_stock_row(db: AsyncSession, warehouse_id: uuid.UUID, part_id: uuid.UUID) -> WarehouseStock | None:
    """SELECT ... FOR UPDATE — без этого два одновременных списания одной и той же
    позиции (например, два запроса синка, пришедшие почти одновременно) могут оба
    прочитать один и тот же остаток и увести quantity в минус. Версия в модели
    полезна для аудита/оптимистичных проверок в админке, но сама защита от гонки —
    это блокировка строки на время транзакции."""
    result = await db.execute(
        select(WarehouseStock)
        .where(WarehouseStock.warehouse_id == warehouse_id, WarehouseStock.part_id == part_id)
        .with_for_update()
    )
    return result.scalar_one_or_none()


async def decrement_stock(
    db: AsyncSession,
    warehouse_id: uuid.UUID,
    part_id: uuid.UUID,
    quantity: int,
    repair_id: uuid.UUID | None,
    created_by: uuid.UUID | None,
) -> None:
    row = await _lock_stock_row(db, warehouse_id, part_id)
    available = row.quantity if row else 0
    if available < quantity:
        raise InsufficientStockError(part_id=part_id, available=available, requested=quantity)
    row.quantity -= quantity
    row.version += 1
    db.add(
        StockMovement(
            type=StockMovementType.writeoff,
            part_id=part_id,
            from_warehouse_id=warehouse_id,
            to_warehouse_id=None,
            quantity=quantity,
            repair_id=repair_id,
            created_by=created_by,
        )
    )


async def transfer_stock(
    db: AsyncSession,
    from_warehouse_id: uuid.UUID,
    to_warehouse_id: uuid.UUID,
    part_id: uuid.UUID,
    quantity: int,
    created_by: uuid.UUID | None,
) -> None:
    if from_warehouse_id == to_warehouse_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Склады должны отличаться")

    # Блокируем обе строки в стабильном порядке (по id), чтобы два встречных
    # перемещения между теми же двумя складами не привели к deadlock'у.
    ids_in_order = sorted([from_warehouse_id, to_warehouse_id], key=str)
    locked = {}
    for warehouse_id in ids_in_order:
        locked[warehouse_id] = await _lock_stock_row(db, warehouse_id, part_id)

    source = locked[from_warehouse_id]
    if not source or source.quantity < quantity:
        raise InsufficientStockError(part_id=part_id, available=source.quantity if source else 0, requested=quantity)

    destination = locked[to_warehouse_id]
    source.quantity -= quantity
    source.version += 1
    if destination:
        destination.quantity += quantity
        destination.version += 1
    else:
        db.add(WarehouseStock(warehouse_id=to_warehouse_id, part_id=part_id, quantity=quantity))

    db.add(
        StockMovement(
            type=StockMovementType.transfer,
            part_id=part_id,
            from_warehouse_id=from_warehouse_id,
            to_warehouse_id=to_warehouse_id,
            quantity=quantity,
            created_by=created_by,
        )
    )


async def receive_stock(
    db: AsyncSession,
    to_warehouse_id: uuid.UUID,
    part_id: uuid.UUID,
    quantity: int,
    created_by: uuid.UUID | None,
) -> None:
    row = await _lock_stock_row(db, to_warehouse_id, part_id)
    if row:
        row.quantity += quantity
        row.version += 1
    else:
        db.add(WarehouseStock(warehouse_id=to_warehouse_id, part_id=part_id, quantity=quantity))
    db.add(
        StockMovement(
            type=StockMovementType.receipt,
            part_id=part_id,
            from_warehouse_id=None,
            to_warehouse_id=to_warehouse_id,
            quantity=quantity,
            created_by=created_by,
        )
    )
