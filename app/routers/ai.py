import hashlib
import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.config import settings
from app.core.deps import CurrentUser, get_current_user
from app.database import get_db
from app.models.customer import Client
from app.routers.equipment import get_passport
from app.schemas.ai import DraftFeedback, RepairDraftInput
from app.services import ai
from app.services.access_policy import STAFF_ROLES, ensure_equipment_access

router = APIRouter(prefix="/api/ai", tags=["ai"])


def no_store(response):
    response.headers["Cache-Control"] = "no-store"


@router.get("/capabilities")
async def capabilities(response: Response, user: CurrentUser = Depends(get_current_user)):
    no_store(response)
    return ai.capabilities(user)


@router.post("/service-requests/{request_id}/repair-draft")
async def repair_draft(request_id: uuid.UUID, payload: RepairDraftInput, response: Response,
                       db: AsyncSession = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    no_store(response)
    return await ai.draft(db, user, request_id, payload)


@router.post("/equipment/{equipment_id}/brief")
async def equipment_brief(equipment_id: uuid.UUID, response: Response,
                          db: AsyncSession = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    no_store(response)
    if user.role not in STAFF_ROLES and user.role.value != "technician":
        raise HTTPException(403, "Сводка доступна сотрудникам сервиса")
    if not ai.capabilities(user)["equipment_brief"]:
        raise HTTPException(503, "Сводка пока не включена для вашей организации")
    await ensure_equipment_access(equipment_id, user, db)
    await ai.ensure_pilot_equipment(db, user, equipment_id)
    passport = await get_passport(equipment_id, db, user)
    # Evidence-only short history: no external call or model inference. This uses
    # the canonical passport selection/legacy deduplication and its current ACL.
    entries = passport.history
    entries = sorted(entries, key=lambda entry: entry.occurred_at, reverse=True)
    facts = []
    for entry in entries[:5]:
        text = " · ".join(value for value in [entry.problem, entry.work_summary] if value)
        facts.append({"source_id": entry.id, "date": entry.occurred_at.isoformat(),
                      "text": text or entry.title, "service_request_id": str(entry.service_request_id) if entry.service_request_id else None})
    digest = hashlib.sha256(json.dumps(facts, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return {"facts": facts, "context_hash": digest, "generated_at": datetime.now(timezone.utc).isoformat(),
            "coverage": {"included_count": len(facts), "available_count": len(entries), "truncated": len(entries) > 5},
            "method": "source_history_no_model_call", "estimated_rub": "0"}


@router.post("/generations/{generation_id}/feedback")
async def draft_feedback(generation_id: uuid.UUID, payload: DraftFeedback, response: Response,
                         db: AsyncSession = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    no_store(response)
    return await ai.feedback(db, user, generation_id, payload)


@router.get("/metrics")
async def pilot_metrics(response: Response, db: AsyncSession = Depends(get_db),
                        user: CurrentUser = Depends(get_current_user)):
    no_store(response)
    return await ai.metrics(db, user)


@router.get("/pilot")
async def pilot_overview(response: Response, db: AsyncSession = Depends(get_db),
                         user: CurrentUser = Depends(get_current_user)):
    no_store(response)
    # metrics performs the same staff guard even when all AI flags are off.
    report = await ai.metrics(db, user)
    client_ids = settings._split_csv(settings.ai_client_ids)
    # Compare configured strings without casting untrusted/mistyped values to UUID.
    clients = (await db.scalars(select(Client).where(
        Client.organization_id == user.organization_id).order_by(Client.name))).all() if client_ids else []
    pilot_clients = [client.name for client in clients if str(client.id) in client_ids]
    return {"organization": {"id": str(user.organization_id), "name": user.organization.name},
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "timezone": "Asia/Yekaterinburg", "metrics": report,
            "capabilities": ai.capabilities(user),
            "configuration": {"model": settings.ai_model,
                "pilot_clients": pilot_clients, "client_scope_restricted": bool(client_ids),
                "pilot_member": str(user.organization_id) in settings._split_csv(settings.ai_organization_ids),
                "monthly_limit_rub": str(settings.ai_monthly_limit_rub),
                "daily_limit_rub": str(settings.ai_daily_limit_rub),
                "budget_scope": "shared_pilot"}}
