import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_roles
from app.database import get_db
from app.models.core import Equipment, Task, TaskStatus, Ticket, TicketStatus, User, UserRole
from app.models.organization import OrganizationMembership
from app.models.repair import Repair
from app.schemas.equipment import TaskCreate, TaskOut, TaskUpdate
from app.models.service_request import ServiceRequest
from app.services.service_requests import event, next_number
from app.services.service_request_workflow import transition

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.get("", response_model=list[TaskOut])
async def list_tasks(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    # Активные наряды показываем первыми, закрытые и отменённые — внизу.
    # Внутри групп свежие заявки идут раньше старых.
    closed_last = case(
        (Task.status.in_((TaskStatus.closed, TaskStatus.cancelled)), 1),
        else_=0,
    )
    query = select(Task).where(Task.organization_id == user.organization_id).order_by(closed_last, Task.created_at.desc())
    # Техник видит только свои назначенные заявки — так же, как в мобильном
    # клиенте (см. экран "Мои заявки" в мокапе); админ/диспетчер видят всё.
    if user.role == UserRole.technician:
        query = query.where(Task.assigned_to == user.id)
    return (await db.scalars(query)).all()


@router.post("", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
async def create_task(
    payload: TaskCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles(UserRole.admin, UserRole.dispatcher)),
):
    equipment = await db.scalar(select(Equipment.id).where(
        Equipment.id == payload.equipment_id, Equipment.organization_id == user.organization_id
    ))
    if not equipment:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Оборудование не найдено в организации")
    task = Task(**payload.model_dump(), created_by=user.id, organization_id=user.organization_id)
    db.add(task)
    await db.flush()
    if task.assigned_to:
        task.status = TaskStatus.assigned
    request = ServiceRequest(organization_id=user.organization_id, number=await next_number(db, user.organization_id), task_id=task.id, equipment_id=task.equipment_id, status="new", priority=task.priority.value, title=task.title, description=task.description)
    db.add(request); await db.flush(); db.add(event(user.organization_id, request.id, user.id, "request.created", "Заявка создана диспетчером", {"task_id": str(task.id)}))
    if task.assigned_to:
        await transition(db, request, user, "assigned", technician_id=task.assigned_to)
    await db.commit()
    await db.refresh(task)
    return task


@router.patch("/{task_id}", response_model=TaskOut)
async def update_task(
    task_id: uuid.UUID,
    payload: TaskUpdate,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_roles(UserRole.admin, UserRole.dispatcher)),
):
    task = await db.scalar(select(Task).where(Task.id == task_id, Task.organization_id == user.organization_id))
    if not task:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Наряд не найден")
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("assigned_to"):
        technician = await db.scalar(select(User).join(
            OrganizationMembership, OrganizationMembership.user_id == User.id
        ).where(
            User.id == changes["assigned_to"], User.is_active.is_(True),
            OrganizationMembership.organization_id == user.organization_id,
            OrganizationMembership.role == UserRole.technician,
            OrganizationMembership.is_active.is_(True),
        ))
        if not technician:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Можно назначить только активного техника")
    if changes.get('assigned_to') and task.status == TaskStatus.new:
        changes['status'] = TaskStatus.assigned
    for field, value in changes.items():
        setattr(task, field, value)
    request = await db.scalar(select(ServiceRequest).where(ServiceRequest.task_id == task.id).with_for_update())
    if request:
        if ("assigned_to" in changes and changes["assigned_to"] != request.assigned_technician_id) or changes.get("status") in {TaskStatus.closed, TaskStatus.cancelled}:
            raise HTTPException(status.HTTP_409_CONFLICT, "Связанную заявку изменяйте через её workflow; наряд не может обойти ServiceRequest")
        request.title, request.description, request.priority = task.title, task.description, task.priority.value
    await db.commit()
    await db.refresh(task)
    return task


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_roles(UserRole.admin, UserRole.dispatcher)),
):
    """Deletes a work order while preserving completed repair-act history."""
    task = await db.scalar(select(Task).where(Task.id == task_id, Task.organization_id == user.organization_id))
    if not task:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Наряд не найден")
    if task.status not in (TaskStatus.closed, TaskStatus.cancelled) and not (
        task.status == TaskStatus.new and task.assigned_to is None
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Активный назначенный наряд удалять нельзя. Сначала завершите или отмените его.",
        )

    # Акт ремонта является учётной историей, поэтому не удаляем его вместе с
    # нарядом. Отвязываем акт от наряда, чтобы внешний ключ не блокировал
    # удаление; сведения об оборудовании, технике и выполненной работе в акте
    # сохраняются.
    repairs = (await db.scalars(select(Repair).where(Repair.task_id == task_id))).all()
    for repair in repairs:
        repair.task_id = None

    await db.delete(task)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/{task_id}/assign", response_model=TaskOut)
async def assign_task(
    task_id: uuid.UUID,
    technician_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_roles(UserRole.admin, UserRole.dispatcher)),
):
    task = await db.scalar(select(Task).where(Task.id == task_id, Task.organization_id == user.organization_id))
    if not task:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Заявка не найдена")
    technician = await db.scalar(select(User).join(
        OrganizationMembership, OrganizationMembership.user_id == User.id
    ).where(
        User.id == technician_id, User.is_active.is_(True),
        OrganizationMembership.organization_id == user.organization_id,
        OrganizationMembership.role == UserRole.technician,
        OrganizationMembership.is_active.is_(True),
    ))
    if not technician:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Можно назначить только активного техника")
    request = await db.scalar(select(ServiceRequest).where(ServiceRequest.task_id == task.id).with_for_update())
    if request:
        await transition(db, request, user, "assigned", technician_id=technician_id)
    task.assigned_to = technician_id
    task.status = TaskStatus.assigned
    await db.commit()
    await db.refresh(task)
    return task


@router.post("/{task_id}/close", response_model=TaskOut)
async def close_own_task(
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles(UserRole.technician)),
):
    """Allows a technician to close only a work order assigned to them."""
    task = await db.scalar(
        select(Task)
        .where(Task.id == task_id, Task.assigned_to == user.id, Task.organization_id == user.organization_id)
        .with_for_update()
    )
    if not task:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Наряд не найден или не назначен вам")
    if task.status == TaskStatus.closed:
        return task
    if task.status in (TaskStatus.new, TaskStatus.cancelled):
        raise HTTPException(status.HTTP_409_CONFLICT, "Этот наряд нельзя закрыть")

    request = await db.scalar(select(ServiceRequest).where(ServiceRequest.task_id == task.id))
    if request:
        raise HTTPException(status.HTTP_409_CONFLICT, "Связанную заявку завершайте только через сервисный акт")
    task.status = TaskStatus.closed
    if task.ticket_id:
        ticket = await db.get(Ticket, task.ticket_id, with_for_update=True)
        if ticket and ticket.status != TicketStatus.resolved:
            ticket.status = TicketStatus.resolved

    await db.commit()
    await db.refresh(task)
    return task
