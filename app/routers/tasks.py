import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_roles
from app.database import get_db
from app.models.core import Task, TaskStatus, User, UserRole
from app.models.repair import Repair
from app.schemas.equipment import TaskCreate, TaskOut, TaskUpdate

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.get("", response_model=list[TaskOut])
async def list_tasks(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    query = select(Task).order_by(Task.due_at)
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
    task = Task(**payload.model_dump(), created_by=user.id)
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return task


@router.patch("/{task_id}", response_model=TaskOut)
async def update_task(
    task_id: uuid.UUID,
    payload: TaskUpdate,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_roles(UserRole.admin, UserRole.dispatcher)),
):
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Наряд не найден")
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("assigned_to"):
        technician = await db.get(User, changes["assigned_to"])
        if not technician or technician.role != UserRole.technician or not technician.is_active:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Можно назначить только активного техника")
    if changes.get('assigned_to') and task.status == TaskStatus.new:
        changes['status'] = TaskStatus.assigned
    for field, value in changes.items():
        setattr(task, field, value)
    await db.commit()
    await db.refresh(task)
    return task


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_roles(UserRole.admin, UserRole.dispatcher)),
):
    """Удаляет ошибочно созданный, ещё не выданный технику наряд."""
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Наряд не найден")

    # После назначения техник мог уже начать работу офлайн. Удаление такого
    # наряда сделает его будущую синхронизацию некорректной, поэтому безопасно
    # удалять только новый (неназначенный) наряд.
    if task.status != TaskStatus.new or task.assigned_to is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Можно удалить только новый неназначенный наряд. Сначала снимите назначение и верните статус «Новый».",
        )

    has_repair = await db.scalar(select(Repair.id).where(Repair.task_id == task_id).limit(1))
    if has_repair:
        raise HTTPException(status.HTTP_409_CONFLICT, "Нельзя удалить наряд с оформленным актом ремонта")

    await db.delete(task)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/{task_id}/assign", response_model=TaskOut)
async def assign_task(
    task_id: uuid.UUID,
    technician_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_roles(UserRole.admin, UserRole.dispatcher)),
):
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Заявка не найдена")
    technician = await db.get(User, technician_id)
    if not technician or technician.role != UserRole.technician or not technician.is_active:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Можно назначить только активного техника")
    task.assigned_to = technician_id
    task.status = TaskStatus.assigned
    await db.commit()
    await db.refresh(task)
    return task
