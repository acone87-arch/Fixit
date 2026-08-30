"""Authoritative lifecycle policy for canonical ServiceRequests.

Routers and compatibility adapters deliberately call this service instead of
writing ``ServiceRequest.status`` themselves.  The caller is responsible for
locking the request row (or uses ``locked_request`` below) and committing the
transaction that contains the related operation.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import CurrentUser
from app.models.core import User, UserRole
from app.models.organization import OrganizationMembership
from app.models.service_request import ServiceRequest
from app.services.service_requests import event

ACTIVE = {"new", "assigned", "on_the_way", "arrived", "in_progress"}
WAITING = {"waiting_parts", "waiting_approval"}
TERMINAL = {"completed", "cancelled"}
LEGACY = {"closed"}

TRANSITIONS = {
    "new": {"assigned", "cancelled"},
    "assigned": {"on_the_way", "cancelled"},
    "on_the_way": {"arrived", "cancelled"},
    "arrived": {"in_progress", "cancelled"},
    "in_progress": {"waiting_parts", "waiting_approval", "completed"},
    "waiting_parts": {"in_progress", "cancelled"},
    "waiting_approval": {"in_progress", "cancelled"},
    "completed": set(), "cancelled": set(), "closed": set(),
}

_SEMANTICS = {
    "assigned": ("technician.assigned", "Назначен мастер"),
    "on_the_way": ("technician.on_the_way", "Мастер выехал"),
    "arrived": ("technician.arrived", "Мастер прибыл на объект"),
    "in_progress": ("work.started", "Работа начата"),
    "waiting_parts": ("request.waiting_parts", "Ожидание запчастей"),
    "waiting_approval": ("request.waiting_approval", "Ожидание согласования"),
    "cancelled": ("request.cancelled", "Заявка отменена"),
}


async def locked_request(db: AsyncSession, request_id: uuid.UUID, organization_id: uuid.UUID) -> ServiceRequest:
    request = await db.scalar(select(ServiceRequest).where(
        ServiceRequest.id == request_id, ServiceRequest.organization_id == organization_id,
    ).with_for_update())
    if not request:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Заявка не найдена")
    return request


async def _validate_technician(db: AsyncSession, technician_id: uuid.UUID, organization_id: uuid.UUID) -> User:
    technician = await db.scalar(select(User).join(OrganizationMembership, (
        OrganizationMembership.user_id == User.id) & (OrganizationMembership.organization_id == organization_id)
    ).where(User.id == technician_id, User.is_active.is_(True), OrganizationMembership.is_active.is_(True),
            OrganizationMembership.role == UserRole.technician))
    if not technician:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Можно назначить только активного техника организации")
    return technician


def _forbidden(message: str) -> None:
    raise HTTPException(status.HTTP_403_FORBIDDEN, message)


async def transition(
    db: AsyncSession, request: ServiceRequest, actor: CurrentUser, target: str, *,
    technician_id: uuid.UUID | None = None, approval_target: str | None = None,
    reason: str | None = None, note: str | None = None, completion_repair_id: uuid.UUID | None = None,
) -> ServiceRequest:
    """Apply one allowed lifecycle edge and append exactly one state event."""
    if request.organization_id != actor.organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Заявка не найдена")
    source = request.status
    if target not in TRANSITIONS.get(source, set()):
        raise HTTPException(status.HTTP_409_CONFLICT, "Этот переход недоступен на текущем этапе заявки")
    role = actor.role

    if target == "assigned":
        if role not in {UserRole.owner, UserRole.admin, UserRole.dispatcher}:
            _forbidden("Назначать техника могут только диспетчер или администратор")
        if not technician_id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Укажите техника")
        technician = await _validate_technician(db, technician_id, actor.organization_id)
        request.assigned_technician_id = technician.id
    elif target in {"on_the_way", "arrived", "in_progress", "waiting_parts", "waiting_approval"}:
        if role != UserRole.technician or request.assigned_technician_id != actor.id:
            _forbidden("Это действие доступно только назначенному технику")
        if target == "in_progress" and source == "waiting_approval":
            _forbidden("Согласование должен принять уполномоченный участник")
        if target == "waiting_approval":
            if approval_target not in {"internal", "client"}:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Укажите получателя согласования")
            request.approval_target = approval_target
    elif target == "completed":
        if completion_repair_id is None:
            raise HTTPException(status.HTTP_409_CONFLICT, "Завершение возможно только при синхронизации сервисного акта")
        if role != UserRole.technician or request.assigned_technician_id != actor.id:
            _forbidden("Завершить заявку может только назначенный техник")
    elif target == "cancelled":
        if source == "waiting_approval":
            # Approval routes use the dedicated decision function below.
            raise HTTPException(status.HTTP_409_CONFLICT, "Используйте действие согласования для этой заявки")
        if role not in {UserRole.owner, UserRole.admin, UserRole.dispatcher}:
            _forbidden("Отменять заявку могут только диспетчер или администратор")
        if not (reason or note):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Укажите причину отмены")

    request.status = target
    if target == "cancelled":
        request.completed_at = datetime.now(timezone.utc)
    details = {"from": source, "to": target, "transitioned_at": datetime.now(timezone.utc).isoformat()}
    if technician_id:
        details["technician_id"] = str(technician_id)
    if approval_target:
        details["approval_target"] = approval_target
    if reason or note:
        details["reason"] = reason or note
    if completion_repair_id:
        details["repair_id"] = str(completion_repair_id)
    if target == "completed":
        event_type, message = "repair.completed", "Ремонт выполнен, сервисный акт оформлен"
    elif target == "in_progress" and source == "waiting_parts":
        event_type, message = "work.resumed", "Работа возобновлена"
    else:
        event_type, message = _SEMANTICS[target]
    db.add(event(actor.organization_id, request.id, actor.id, event_type, note or message, details))
    return request


async def decide_approval(db: AsyncSession, request: ServiceRequest, actor: CurrentUser, approved: bool, comment: str | None) -> ServiceRequest:
    if request.organization_id != actor.organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Заявка не найдена")
    if request.status != "waiting_approval":
        raise HTTPException(status.HTTP_409_CONFLICT, "Заявка не ожидает согласования")
    if request.approval_target == "internal":
        if actor.role not in {UserRole.owner, UserRole.admin, UserRole.dispatcher}:
            _forbidden("Внутреннее согласование недоступно клиенту")
    elif request.approval_target == "client":
        if actor.role not in {UserRole.client_admin, UserRole.client_site_user}:
            _forbidden("Согласование клиента доступно только пользователю клиента")
    else:
        raise HTTPException(status.HTTP_409_CONFLICT, "Неизвестный получатель согласования")
    if not approved and not comment:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Укажите причину отказа")
    target = "in_progress" if approved else "cancelled"
    request.status = target
    if not approved:
        request.completed_at = datetime.now(timezone.utc)
    now = datetime.now(timezone.utc)
    details = {"approved_by": str(actor.id), "approved_at": now.isoformat(), "comment": comment, "target": request.approval_target,
               "from": "waiting_approval", "to": target}
    db.add(event(actor.organization_id, request.id, actor.id,
                 "approval.approved" if approved else "approval.rejected",
                 "Работы согласованы" if approved else (comment or "Согласование отклонено"), details))
    return request
