import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.deps import CurrentUser, get_current_user, require_roles
from app.database import get_db
from app.models.core import Equipment, User, UserRole
from app.models.customer import Client, Site
from app.models.repair import Repair, RepairPart
from app.models.service_request import ServiceRequest, ServiceRequestEvent
from app.models.warehouse import Part
from app.schemas.service_request import REQUEST_STATUSES, ServiceRequestOut, ServiceRequestStatusUpdate
from app.services.service_requests import event

router = APIRouter(prefix="/api/service-requests", tags=["service requests"])

async def serialize(db, request, org):
    row = (await db.execute(select(Equipment, Site, Client, User.full_name).join(Site, Site.id == Equipment.site_id).join(Client, Client.id == Site.client_id).outerjoin(User, User.id == request.assigned_technician_id).where(Equipment.id == request.equipment_id))).one()
    equipment, site, client, technician_name = row
    repair = await db.scalar(select(Repair).where(Repair.organization_id == org, ((Repair.task_id == request.task_id) if request.task_id else (Repair.ticket_id == request.ticket_id))).order_by(Repair.closed_at.desc()))
    parts = []
    if repair:
        parts = [{"part_name": name, "article": article, "quantity": qty} for name, article, qty in (await db.execute(select(Part.name, Part.article, RepairPart.quantity).join(RepairPart, RepairPart.part_id == Part.id).where(RepairPart.repair_id == repair.id))).all()]
    history = [{"at": item.created_at, "type": item.event_type, "message": item.message, "details": item.details_json} for item in (await db.scalars(select(ServiceRequestEvent).where(ServiceRequestEvent.service_request_id == request.id).order_by(ServiceRequestEvent.created_at))).all()]
    return ServiceRequestOut(id=request.id, number=request.number, ticket_id=request.ticket_id, task_id=request.task_id, equipment_id=request.equipment_id, client_name=client.name, site_name=site.name, equipment_name=equipment.name, serial_number=equipment.serial_number, description=request.description, priority=request.priority, assigned_technician_id=request.assigned_technician_id, assigned_technician_name=technician_name, status=request.status, created_at=request.created_at, completed_at=request.completed_at, repair_id=repair.id if repair else None, parts_used=parts, outcome=repair.description if repair else None, history=history)

@router.get("", response_model=list[ServiceRequestOut])
async def list_requests(db: AsyncSession = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    query = select(ServiceRequest).where(ServiceRequest.organization_id == user.organization_id).order_by(ServiceRequest.created_at.desc())
    if user.role == UserRole.technician: query = query.where(ServiceRequest.assigned_technician_id == user.id)
    return [await serialize(db, item, user.organization_id) for item in (await db.scalars(query)).all()]

@router.get("/{request_id}", response_model=ServiceRequestOut)
async def get_request(request_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    request = await db.scalar(select(ServiceRequest).where(ServiceRequest.id == request_id, ServiceRequest.organization_id == user.organization_id))
    if not request or (user.role == UserRole.technician and request.assigned_technician_id != user.id): raise HTTPException(404, "Заявка не найдена")
    return await serialize(db, request, user.organization_id)

@router.patch("/{request_id}/status", response_model=ServiceRequestOut)
async def update_status(request_id: uuid.UUID, payload: ServiceRequestStatusUpdate, db: AsyncSession = Depends(get_db), user: CurrentUser = Depends(require_roles(UserRole.dispatcher, UserRole.technician))):
    if payload.status not in REQUEST_STATUSES: raise HTTPException(422, "Неизвестный статус заявки")
    request = await db.scalar(select(ServiceRequest).where(ServiceRequest.id == request_id, ServiceRequest.organization_id == user.organization_id).with_for_update())
    if not request or (user.role == UserRole.technician and request.assigned_technician_id != user.id): raise HTTPException(404, "Заявка не найдена")
    previous = request.status; request.status = payload.status
    if payload.status in {"completed", "closed", "cancelled"}: request.completed_at = datetime.now(timezone.utc)
    db.add(event(user.organization_id, request.id, user.id, "status.changed", payload.note or f"Статус: {previous} → {payload.status}", {"from": previous, "to": payload.status}))
    await db.commit(); await db.refresh(request)
    return await serialize(db, request, user.organization_id)
