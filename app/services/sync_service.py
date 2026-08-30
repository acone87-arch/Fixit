import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_technician_mobile_warehouse_id
from app.models.core import Equipment, EquipmentStatus, Task, TaskStatus, Ticket, TicketStatus
from app.models.repair import Repair, RepairPart, SyncOperation, SyncStatus
from app.schemas.repair import RepairCreate, SyncItemResult
from app.services.stock_service import InsufficientStockError, decrement_stock
from app.models.service_request import ServiceRequest
from app.services.service_requests import event
from app.services.service_request_workflow import transition
from app.models.core import UserRole


# Completion from the current Pulse ServiceRequest workspace is emitted only
# after work has started.  Legacy Task/Ticket sync remains compatible below.
CANONICAL_COMPLETION_STATUSES = {"in_progress"}


class _SyncFailure(Exception):
    """Internal signal to abort the current item's savepoint and report a clean
    per-item failure, instead of either raising a 500 or silently returning
    while partial writes (e.g. a stock decrement) stay staged in the session."""

    def __init__(self, message: str):
        self.message = message


def validate_canonical_completion(
    request: ServiceRequest | None,
    *,
    organization_id: uuid.UUID,
    technician_id: uuid.UUID,
    equipment_id: uuid.UUID,
) -> ServiceRequest:
    """Validate the minimum server-side integrity contract for a canonical
    ServiceRequest completion.  Kept separate from the database query so this
    policy has direct regression coverage independent of the frontend."""
    if not request or request.organization_id != organization_id:
        raise _SyncFailure("Заявка не найдена")
    if request.equipment_id != equipment_id:
        raise _SyncFailure("Заявка относится к другому оборудованию")
    if not request.assigned_technician_id:
        raise _SyncFailure("Заявка не назначена мастеру")
    if request.assigned_technician_id != technician_id:
        raise _SyncFailure("Заявка назначена другому мастеру")
    if request.status not in CANONICAL_COMPLETION_STATUSES:
        raise _SyncFailure("Заявку нельзя завершить на текущем этапе")
    return request


async def sync_one_repair(db: AsyncSession, technician_id: uuid.UUID, organization_id: uuid.UUID,
                          payload: RepairCreate) -> SyncItemResult:
    # local_uuid служит и первичным ключом идемпотентности синка (через
    # sync_operations), и уникальным ключом самой записи repairs — при повторной
    # отправке того же пакета сервер не создаёт дубликат, а возвращает то же
    # самое решение, что было принято в первый раз.
    existing_op = await db.scalar(select(SyncOperation).where(
        SyncOperation.operation_id == payload.local_uuid,
        SyncOperation.organization_id == organization_id,
    ))
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
            equipment = await db.scalar(
                select(Equipment).where(Equipment.id == payload.equipment_id,
                                        Equipment.organization_id == organization_id).with_for_update()
            )
            if not equipment:
                raise _SyncFailure("Оборудование не найдено")

            task = None
            ticket_id = payload.ticket_id
            service_request_id = payload.service_request_id
            linked_request = None
            if service_request_id:
                linked_request = await db.scalar(select(ServiceRequest).where(
                    ServiceRequest.id == service_request_id,
                    ServiceRequest.organization_id == organization_id,
                ).with_for_update())
                linked_request = validate_canonical_completion(
                    linked_request,
                    organization_id=organization_id,
                    technician_id=technician_id,
                    equipment_id=equipment.id,
                )
                existing_repair = await db.scalar(select(Repair.id).where(
                    Repair.organization_id == organization_id,
                    Repair.service_request_id == linked_request.id,
                ))
                if existing_repair:
                    raise _SyncFailure("Для заявки уже оформлен сервисный акт")

            if payload.task_id:
                task = await db.scalar(
                    select(Task)
                    .where(Task.id == payload.task_id, Task.assigned_to == technician_id,
                           Task.organization_id == organization_id)
                    .with_for_update()
                )
                if not task:
                    raise _SyncFailure("Наряд не найден или не назначен вам")
                if task.equipment_id != equipment.id:
                    raise _SyncFailure("Наряд относится к другому оборудованию")
                ticket_id = task.ticket_id or ticket_id

            # Для акта без запчастей склад вообще не нужен. Раньше именно это
            # лишнее требование не давало технику закрыть выполненный ремонт.
            if payload.parts_used:
                mobile_warehouse_id = await get_technician_mobile_warehouse_id(db, technician_id, organization_id)
                for item in payload.parts_used:
                    try:
                        await decrement_stock(
                            db,
                            warehouse_id=mobile_warehouse_id,
                            part_id=item.part_id,
                            quantity=item.quantity,
                            repair_id=None,
                            created_by=technician_id,
                            organization_id=organization_id,
                        )
                    except InsufficientStockError as exc:
                        raise _SyncFailure(
                            f"Недостаточно запчастей на складе: доступно {exc.available}, "
                            f"требуется {exc.requested}"
                        ) from exc

            conflict = equipment.version != payload.base_equipment_version

            repair = Repair(
                organization_id=organization_id,
                id=uuid.uuid4(),
                local_uuid=payload.local_uuid,
                equipment_id=equipment.id,
                service_request_id=linked_request.id if linked_request else None,
                task_id=payload.task_id,
                ticket_id=ticket_id,
                technician_id=technician_id,
                fault_type=payload.fault_type,
                description=payload.description,
                labor_minutes=max(0, payload.labor_minutes),
                client_signer_name=payload.client_signer_name,
                client_signed_at=payload.client_signed_at,
                started_at=payload.started_at,
                closed_at=payload.closed_at,
                sync_status=SyncStatus.conflict if conflict else SyncStatus.synced,
                device_updated_at=payload.device_updated_at,
            )
            db.add(repair)
            await db.flush()  # получаем repair.id для repair_parts и sync_operations

            for item in payload.parts_used:
                db.add(RepairPart(repair_id=repair.id, part_id=item.part_id, quantity=item.quantity))

            # Only a canonical ServiceRequest payload may change its lifecycle.
            # Task/Ticket-only repairs remain readable historical records, but
            # can no longer silently complete a linked canonical request.
            service_request = linked_request
            if service_request:
                sync_actor = SimpleNamespace(id=technician_id, organization_id=organization_id, role=UserRole.technician)
                await transition(db, service_request, sync_actor, "completed", completion_repair_id=repair.id)
                if payload.parts_used:
                    db.add(event(organization_id, service_request.id, technician_id, "parts.used", "Использованы запчасти", {"repair_id": str(repair.id), "parts": [{"part_id": str(item.part_id), "quantity": item.quantity} for item in payload.parts_used]}))
                db.add(event(organization_id, service_request.id, technician_id, "service_act.generated", "Сервисный акт сформирован", {"repair_id": str(repair.id)}))

            if task:
                task.status = TaskStatus.closed

            if ticket_id and not conflict:
                ticket = await db.get(Ticket, ticket_id, with_for_update=True)
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
            db.add(SyncOperation(organization_id=organization_id, operation_id=payload.local_uuid,
                                 repair_id=repair.id, resolved_as=resolved_as))
            result = SyncItemResult(local_uuid=payload.local_uuid, server_id=repair.id, resolved_as=resolved_as)

    except _SyncFailure as exc:
        return SyncItemResult(local_uuid=payload.local_uuid, resolved_as="failed", error=exc.message)
    except Exception as exc:  # noqa: BLE001 — любая непредвиденная ошибка тоже не
        # должна обрывать обработку остальных элементов пакета 500-м ответом.
        return SyncItemResult(local_uuid=payload.local_uuid, resolved_as="failed", error=str(exc))

    return result
