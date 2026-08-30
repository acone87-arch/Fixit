"""Read-only compatibility API for historical Task records.

Fixit 2.0 creates, assigns, and completes work through ServiceRequest. This
router intentionally exposes no Task mutation endpoints: historical clients
may still inspect old records, but cannot bypass the ServiceRequest workflow.
"""
from fastapi import APIRouter, Depends
from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.database import get_db
from app.models.core import Task, TaskStatus, User, UserRole
from app.schemas.equipment import TaskOut


router = APIRouter(prefix="/api/tasks", tags=["tasks (legacy read-only)"])


@router.get("", response_model=list[TaskOut], deprecated=True)
async def list_tasks(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """Return historical tasks only; use /api/service-requests for live work."""
    closed_last = case((Task.status.in_((TaskStatus.closed, TaskStatus.cancelled)), 1), else_=0)
    query = select(Task).where(Task.organization_id == user.organization_id).order_by(closed_last, Task.created_at.desc())
    if user.role == UserRole.technician:
        query = query.where(Task.assigned_to == user.id)
    return (await db.scalars(query)).all()
