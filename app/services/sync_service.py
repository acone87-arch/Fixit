import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_technician_mobile_warehouse_id
from app.models.core import Equipment, EquipmentStatus, Ticket, TicketStatus
from app.models.repair import Repair, RepairPart, SyncOperation, SyncStatus
from app.schemas.repair import RepairCreate, SyncItemResult
from app.services.stock_service import InsufficientStockError, decrement_stock


class _SyncFailure(Exception):
    """Internal signal to abort the current item's savepoint and report a clean
    per-item failure, instead of either raising a 500 or silently returning
    while partial writes (e.g. a stock decrement) stay staged in the session."""

    def __init__(self, message: str):
        self.message = message


async def sync_one_repair(db: AsyncSession, technician_id: uuid.UUID, payload: RepairCreate) -> SyncItemResult:
    # local_uuid служит и первичным ключом идемпотентности синка (через
    # sync_operations), и уникальным ключом самой записи repairs — при повторной
    # отправке того же пакета сервер не создаёт дубликат, а возвращает то же
    # самое решение, что было принято в первый раз.
    existing_op = await db.get(SyncOperation, payload.local_uuid)
    if existing_op:
        return SyncItemResult(
            local_uuid=payload.local_uuid,
            server_id=existing_op.repair_id,
            resolved_as="already_synced",
        )

    result: SyncItemResult | None = None
    try:
        # Каждый элемент пакета — в своей savepoint-транзакции. Если по одной
        # записи не хватило запчастей, исключение откатывает ТОЛЬКО эту
        # savepoint (включая уже применённые внутри неё частичные списания),
        # не трогая остальные уже обработанные записи того же пакета.
        async with db.begin_nested():
            mobile_warehouse_id = await get_technician_mobile_warehouse_id(db, technician_id)

            for item in payload.parts_used:
                try:
                    await decrement_stock(
                        db,
                        warehouse_id=mobile_warehouse_id,
                        part_id=item.part_id,
                        quantity=item.quantity,
                        repair_id=None,
                        created_by=technician_id,
                    )
                except InsufficientStockError as exc:
                    raise _SyncFailure(
                        f"Недостаточно запчастей на складе: доступно {exc.available}, "
                        f"требуется {exc.requested}"
                    ) from exc

            equipment = await db.scalar(
                select(Equipment).where(Equipment.id == payload.equipment_id).with_for_update()
            )
            if not equipment:
                raise _SyncFailure("Оборудование не найдено")

            conflict = equipment.version != payload.base_equipment_version

            repair = Repair(
                id=uuid.uuid4(),
                local_uuid=payload.local_uuid,
                equipment_id=equipment.id,
                task_id=payload.task_id,
                ticket_id=payload.ticket_id,
                technician_id=technician_id,
                fault_type=payload.fault_type,
                description=payload.description,
                started_at=payload.started_at,
                closed_at=payload.closed_at,
                sync_status=SyncStatus.conflict if conflict else SyncStatus.synced,
                device_updated_at=payload.device_updated_at,
            )
            db.add(repair)
            await db.flush()  # получаем repair.id для repair_parts и sync_operations

            for item in payload.parts_used:
                db.add(RepairPart(repair_id=repair.id, part_id=item.part_id, quantity=item.quantity))

            if payload.ticket_id and not conflict:
                ticket = await db.get(Ticket, payload.ticket_id, with_for_update=True)
                if ticket and ticket.status != TicketStatus.resolved:
                    ticket.status = TicketStatus.resolved

            # Новая гостевая заявка, пришедшая уже после того, как техник начал
            # офлайн-ремонт, "побеждает": статус остаётся requires_repair, и
            # диспетчер разбирает ситуацию вручную (см. conflict выше), а не
            # затирается автоматическим "всё починено".
            if not conflict:
                equipment.status = EquipmentStatus.working
                equipment.version += 1

            resolved_as = "applied_with_conflict" if conflict else "applied"
            db.add(SyncOperation(operation_id=payload.local_uuid, repair_id=repair.id, resolved_as=resolved_as))
            result = SyncItemResult(local_uuid=payload.local_uuid, server_id=repair.id, resolved_as=resolved_as)

    except _SyncFailure as exc:
        return SyncItemResult(local_uuid=payload.local_uuid, resolved_as="failed", error=exc.message)
    except Exception as exc:  # noqa: BLE001 — любая непредвиденная ошибка тоже не
        # должна обрывать обработку остальных элементов пакета 500-м ответом.
        return SyncItemResult(local_uuid=payload.local_uuid, resolved_as="failed", error=str(exc))

    return result
