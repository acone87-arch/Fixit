import uuid
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.service_request import ServiceRequest, ServiceRequestEvent

async def lock_request_intake(db: AsyncSession, organization_id: uuid.UUID) -> None:
    # Все entry points используют один transaction-level lock. Row lock на
    # Organization здесь конфликтовал бы с FK key-share после INSERT Ticket.
    # Разные tenant не блокируют друг друга; коллизия ключа лишь сериализует их.
    key = organization_id.int % (1 << 63)
    await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})


async def next_number(db: AsyncSession, organization_id: uuid.UUID) -> int:
    await lock_request_intake(db, organization_id)
    return int((await db.scalar(select(func.coalesce(func.max(ServiceRequest.number), 0)).where(ServiceRequest.organization_id == organization_id))) or 0) + 1

def event(org, request_id, actor, event_type, message, details=None):
    return ServiceRequestEvent(organization_id=org, service_request_id=request_id, actor_user_id=actor, event_type=event_type, message=message, details_json=details)
