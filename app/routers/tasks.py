import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_roles
from app.database import get_db
from app.models.core import Task, User, UserRole
from app.schemas.equipment import TaskCreate, TaskOut

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


@router.patch("/{task_id}/assign", response_model=TaskOut)
async def assign_task(
    task_id: uuid.UUID,
    technician_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_roles(UserRole.admin, UserRole.dispatcher)),
):
    from app.models.core import TaskStatus

    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Заявка не найдена")
    task.assigned_to = technician_id
    task.status = TaskStatus.assigned
    await db.commit()
    await db.refresh(task)
    return task
