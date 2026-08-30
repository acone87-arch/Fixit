"""Canonical, reusable read authorization for service equipment and media."""
from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import CurrentUser
from app.models.core import Equipment, UserRole
from app.models.customer import TechnicianClientAccess, Site
from app.models.repair import Repair
from app.models.service_request import ServiceRequest
from app.services.client_portal import CLIENT_ROLES, ensure_client_equipment

ACTIVE_ASSIGNED_STATES = {"assigned", "on_the_way", "arrived", "in_progress", "waiting_parts", "waiting_approval"}
STAFF_ROLES = {UserRole.owner, UserRole.admin, UserRole.dispatcher}


async def ensure_service_request_access(request: ServiceRequest, user: CurrentUser, db: AsyncSession) -> ServiceRequest:
    if request.organization_id != user.organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Заявка не найдена")
    if user.role in CLIENT_ROLES:
        await ensure_client_equipment(request.equipment_id, user, db)
    elif user.role == UserRole.technician and request.assigned_technician_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Заявка не найдена")
    return request


async def ensure_equipment_access(equipment_id: uuid.UUID, user: CurrentUser, db: AsyncSession) -> Equipment:
    if user.role in CLIENT_ROLES:
        return await ensure_client_equipment(equipment_id, user, db)
    equipment = await db.scalar(select(Equipment).where(
        Equipment.id == equipment_id, Equipment.organization_id == user.organization_id,
    ))
    if not equipment:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Оборудование не найдено")
    if user.role == UserRole.technician:
        fleet_access = await db.scalar(select(TechnicianClientAccess.id).join(Site, Site.client_id == TechnicianClientAccess.client_id).where(
            TechnicianClientAccess.organization_id == user.organization_id, TechnicianClientAccess.technician_id == user.id,
            Site.id == equipment.site_id, Site.organization_id == user.organization_id).limit(1))
        if not fleet_access:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Оборудование не назначено вам для обслуживания")
    return equipment


async def ensure_repair_access(repair: Repair, user: CurrentUser, db: AsyncSession) -> Repair:
    if repair.organization_id != user.organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Акт ремонта не найден")
    if user.role in CLIENT_ROLES:
        await ensure_client_equipment(repair.equipment_id, user, db)
    elif user.role == UserRole.technician:
        await ensure_equipment_access(repair.equipment_id, user, db)
    return repair
