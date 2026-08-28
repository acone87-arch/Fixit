import uuid
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.service_request import ServiceRequest, ServiceRequestEvent

async def next_number(db: AsyncSession, organization_id: uuid.UUID) -> int:
    return int((await db.scalar(select(func.coalesce(func.max(ServiceRequest.number), 0)).where(ServiceRequest.organization_id == organization_id))) or 0) + 1

def event(org, request_id, actor, event_type, message, details=None):
    return ServiceRequestEvent(organization_id=org, service_request_id=request_id, actor_user_id=actor, event_type=event_type, message=message, details_json=details)
