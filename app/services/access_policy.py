"""Canonical, reusable read authorization for service equipment and media."""
from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import CurrentUser
from app.models.core import Equipment, UserRole
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
        assigned = await db.scalar(select(ServiceRequest.id).where(
            ServiceRequest.organization_id == user.organization_id,
            ServiceRequest.equipment_id == equipment_id,
            ServiceRequest.assigned_technician_id == user.id,
            ServiceRequest.status.in_(ACTIVE_ASSIGNED_STATES),
        ).limit(1))
        if not assigned:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Оборудование доступно только по активной назначенной заявке")
    return equipment


async def ensure_repair_access(repair: Repair, user: CurrentUser, db: AsyncSession) -> Repair:
    if repair.organization_id != user.organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Акт ремонта не найден")
    if user.role in CLIENT_ROLES:
        await ensure_client_equipment(repair.equipment_id, user, db)
    elif user.role == UserRole.technician:
        if repair.technician_id == user.id:
            return repair  # Explicit, limited history of the technician's own completed work.
        if repair.service_request_id:
            request = await db.scalar(select(ServiceRequest).where(
                ServiceRequest.id == repair.service_request_id,
                ServiceRequest.organization_id == user.organization_id,
            ))
            if request and request.assigned_technician_id == user.id and request.status in ACTIVE_ASSIGNED_STATES:
                return repair
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Можно просматривать только свои или назначенные работы")
    return repair
