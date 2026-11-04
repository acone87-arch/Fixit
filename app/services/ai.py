"""Draft generation, shared PostgreSQL estimates, and access rechecks."""
import asyncio
import time as timer
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_UP
import hashlib
import json
import re
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictStr
from sqlalchemy import func, select, text, update

from app.config import settings
from app.core.deps import CurrentUser
from app.models.ai import AIGeneration
from app.models.core import Equipment, User, UserRole
from app.models.customer import Client, Site
from app.models.organization import Organization, OrganizationMembership
from app.models.service_request import ServiceRequest
from app.services.access_policy import STAFF_ROLES, ensure_service_request_access
from app.services.ai_evidence import VERSION, grounded_output
from app.services import ai_provider

WORK_STATES = {"in_progress", "waiting_parts", "waiting_approval"}
LOCK = 714209031
PRIVATE = re.compile(r"https?://|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|(?:\+?\d[\s()-]*){8,}")


class RepairQuotes(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    diagnostic_quotes: list[StrictStr] = Field(max_length=30)
    work_quotes: list[StrictStr] = Field(max_length=30)
    comment_quotes: list[StrictStr] = Field(max_length=30)
    questions: list[StrictStr] = Field(max_length=10)


def capabilities(user):
    allowed = (settings.ai_enabled and str(user.organization_id) in settings._split_csv(settings.ai_organization_ids)
               and (user.role in STAFF_ROLES or user.role == UserRole.technician))
    rates_ok = settings.ai_model in {"yandexgpt-5.1", "yandexgpt-5-pro"}
    minimum = Decimal("1.2") if settings.ai_model == "yandexgpt-5-pro" else Decimal("0.8")
    rates_ok = rates_ok and settings.ai_input_rub_per_1000 >= minimum and settings.ai_output_rub_per_1000 >= minimum
    repair = bool(allowed and settings.ai_repair_enabled and settings.yandex_gpt_api_key
                  and settings.yandex_gpt_folder_id and rates_ok)
    return {"repair_draft": repair, "equipment_brief": bool(allowed and settings.ai_brief_enabled),
            "enabled": bool(allowed), "cost_basis": "local_estimate_not_cloud_balance"}


async def ensure_pilot_equipment(db, user, equipment_id):
    client_ids = settings._split_csv(settings.ai_client_ids)
    if not client_ids:
        return
    client_id = await db.scalar(select(Client.id).join(Site, Site.client_id == Client.id)
        .join(Equipment, Equipment.site_id == Site.id).where(
            Equipment.id == equipment_id, Equipment.organization_id == user.organization_id,
            Site.organization_id == user.organization_id, Client.organization_id == user.organization_id,
            Client.is_active.is_(True), Site.is_active.is_(True)))
    if str(client_id) not in client_ids:
        raise HTTPException(403, "AI-пилот не включён для клиента этого оборудования")


async def allowed_request(db, user, request_id):
    request = await db.scalar(select(ServiceRequest).where(ServiceRequest.id == request_id).execution_options(populate_existing=True))
    if not request:
        raise HTTPException(404, "Заявка не найдена")
    await ensure_service_request_access(request, user, db)
    if user.role not in STAFF_ROLES and user.role != UserRole.technician:
        raise HTTPException(403, "AI-черновик доступен сотрудникам сервиса")
    await ensure_pilot_equipment(db, user, request.equipment_id)
    if request.status not in WORK_STATES:
        raise HTTPException(409, "Черновик доступен только для заявки в работе или ожидании")
    return request


async def fresh_user(db, user_id, organization_id, auth_version):
    person = await db.get(User, user_id, populate_existing=True)
    member = await db.scalar(select(OrganizationMembership).where(
        OrganizationMembership.organization_id == organization_id, OrganizationMembership.user_id == user_id
    ).execution_options(populate_existing=True))
    org = await db.get(Organization, organization_id, populate_existing=True)
    if not person or not person.is_active or person.auth_version != auth_version or not member or not member.is_active or not org or not org.is_active:
        raise HTTPException(403, "Доступ изменился; откройте заявку заново")
    return CurrentUser(user=person, organization=org, membership=member)


def periods(now):
    local = now.astimezone(ZoneInfo("Asia/Yekaterinburg"))
    day = datetime.combine(local.date(), time.min, tzinfo=local.tzinfo)
    return day, day.replace(day=1)


async def draft(db, user, request_id, payload):
    await allowed_request(db, user, request_id)
    if not capabilities(user)["repair_draft"]:
        raise HTTPException(503, "AI пока не включён для вашей организации. Заполните форму вручную.")
    note = payload.note.strip()
    if not note:
        raise HTTPException(422, "Добавьте описание результата")
    if PRIVATE.search(note):
        raise HTTPException(422, "Уберите из текста контакты, ссылки и длинные номера перед отправкой в AI")
    user_id, org_id, auth_version = user.id, user.organization_id, user.user.auth_version
    encoded = json.dumps(ai_provider.request_body(note, settings), ensure_ascii=False).encode()
    fingerprint = hashlib.sha256(encoded + str(request_id).encode() + payload.revision.encode() + VERSION.encode()).hexdigest()
    now = datetime.now(timezone.utc)
    # One global lock serializes reservations across organizations and workers.
    # It is released before the network request.
    await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": LOCK})
    await db.execute(update(AIGeneration).where(AIGeneration.created_at < now - timedelta(days=7)).values(result_json=None))
    await db.execute(update(AIGeneration).where(AIGeneration.status == "pending", AIGeneration.created_at < now - timedelta(seconds=120)).values(status="unknown"))
    existing = await db.scalar(select(AIGeneration).where(
        AIGeneration.organization_id == org_id, AIGeneration.user_id == user_id,
        AIGeneration.operation_id == payload.operation_id))
    if existing:
        if existing.context_hash != fingerprint:
            raise HTTPException(409, "Ключ запроса уже использован с другим текстом")
        if existing.status == "succeeded" and existing.result_json:
            result = dict(existing.result_json)
            await db.commit()
            return {**result, "revision": payload.revision, "cached": True}
        raise HTTPException(409, "Запрос уже учтён. Результат ещё не готов или недоступен; автоматического повтора нет.")
    attempts = await db.scalar(select(func.count()).select_from(AIGeneration).where(
        AIGeneration.user_id == user_id, AIGeneration.created_at >= now - timedelta(minutes=1)))
    pending = await db.scalar(select(func.count()).select_from(AIGeneration).where(AIGeneration.status == "pending"))
    if attempts >= 5 or pending >= 2:
        raise HTTPException(429, "AI занят. Повторите позже или заполните форму вручную.")
    reserve = (((len(encoded) + 1024) * settings.ai_input_rub_per_1000 + ai_provider.MAX_OUTPUT * settings.ai_output_rub_per_1000) / 1000).quantize(Decimal("0.000001"), rounding=ROUND_UP)
    day, month = periods(now)
    for start, limit, prior_matches in (
        (day, settings.ai_daily_limit_rub, settings.ai_prior_accounted_date == day.date().isoformat()),
        (month, settings.ai_monthly_limit_rub, settings.ai_prior_accounted_date[:7] == month.date().isoformat()[:7]),
    ):
        estimated = func.coalesce(AIGeneration.estimated_rub, AIGeneration.reserved_rub)
        spent = await db.scalar(select(func.coalesce(func.sum(estimated), 0)).where(AIGeneration.created_at >= start))
        spent += settings.ai_prior_accounted_rub if prior_matches else Decimal(0)
        if spent + reserve > limit:
            raise HTTPException(429, "Недостаточно лимита AI для безопасного резерва. Сохраните результат вручную.")
    record = AIGeneration(organization_id=org_id, user_id=user_id, request_id=request_id,
        operation_id=payload.operation_id, context_hash=fingerprint, model=settings.ai_model,
        prompt_version=VERSION, reserved_rub=reserve, status="pending")
    db.add(record)
    await db.commit()
    generation_id = record.id
    started = timer.monotonic()
    try:
        response = await ai_provider.generate(note, settings)
        usage = response.get("usage", {})
        incoming, outgoing = usage.get("prompt_tokens"), usage.get("completion_tokens")
        if type(incoming) is not int or incoming < 0 or type(outgoing) is not int or outgoing < 0:
            raise ValueError("Missing usage")
        cost = (incoming * settings.ai_input_rub_per_1000 + outgoing * settings.ai_output_rub_per_1000) / 1000
        record.estimated_rub, record.input_tokens, record.output_tokens = cost, incoming, outgoing
        await db.commit()  # Keep known usage even if content/ACL fails afterwards.
        if cost > reserve:
            raise ValueError("Reserve exceeded")
        choice = response["choices"][0]
        if choice.get("finish_reason") != "stop":
            raise ValueError("Incomplete generation")
        raw = RepairQuotes.model_validate(json.loads(choice["message"]["content"])).model_dump()
        result = grounded_output({"note": note}, raw)
        if any(len(s) > 8000 for s in [result["diagnostic"], result["work"], result["comment"], *result["questions"]]):
            raise ValueError("Output too long")
        current = await fresh_user(db, user_id, org_id, auth_version)
        await allowed_request(db, current, request_id)
        if not capabilities(current)["repair_draft"]:
            raise HTTPException(503, "AI отключён во время запроса")
        result.update(generation_id=str(generation_id), model=settings.ai_model,
                      prompt_version=VERSION, estimated_rub=str(cost))
        record.status, record.result_json, record.finished_at = "succeeded", result, datetime.now(timezone.utc)
        record.duration_ms = int((timer.monotonic() - started) * 1000)
        await db.commit()
        return {**result, "revision": payload.revision, "cached": False}
    except (Exception, asyncio.CancelledError) as exc:
        await db.rollback()
        # Refresh after rollback; avoid expired ORM attributes in error paths.
        record = await db.get(AIGeneration, generation_id, populate_existing=True)
        record.status = "failed" if record.estimated_rub is not None else "unknown"
        record.duration_ms = int((timer.monotonic() - started) * 1000)
        record.result_json, record.finished_at = None, datetime.now(timezone.utc)
        await db.commit()
        if isinstance(exc, (HTTPException, asyncio.CancelledError)):
            raise
        raise HTTPException(502, "AI не смог подготовить проверяемый черновик. Исходный текст сохранён в форме; автоматического повтора нет.") from None


async def feedback(db, user, generation_id, payload):
    # Feedback remains available after completion or flag rollback, but always
    # requires current request ACL and ownership of the original generation.
    row = await db.scalar(select(AIGeneration).where(
        AIGeneration.id == generation_id, AIGeneration.organization_id == user.organization_id,
        AIGeneration.user_id == user.id).with_for_update())
    if not row:
        raise HTTPException(404, "Черновик не найден")
    request = await db.get(ServiceRequest, row.request_id, populate_existing=True)
    if not request:
        raise HTTPException(404, "Заявка не найдена")
    await ensure_service_request_access(request, user, db)
    if user.role not in STAFF_ROLES and user.role != UserRole.technician:
        raise HTTPException(403, "Оценка доступна сотрудникам сервиса")
    if row.status != "succeeded":
        raise HTTPException(409, "Оценка доступна только для готового черновика")
    now = datetime.now(timezone.utc)
    if payload.action == "applied":
        row.applied_at = row.applied_at or now
    elif payload.action == "rejected":
        row.rejected_at = row.rejected_at or now
    else:
        row.rating, row.rating_reason = payload.action, payload.reason
    await db.commit()
    return {"recorded": True}


async def metrics(db, user):
    if user.role not in STAFF_ROLES:
        raise HTTPException(403, "Показатели доступны диспетчеру и администратору")
    _, month = periods(datetime.now(timezone.utc))
    rows = list((await db.execute(select(
        AIGeneration.status, AIGeneration.duration_ms, AIGeneration.applied_at,
        AIGeneration.rejected_at, AIGeneration.repair_id, AIGeneration.rating,
        AIGeneration.input_tokens, AIGeneration.output_tokens,
        AIGeneration.estimated_rub, AIGeneration.reserved_rub).where(
        AIGeneration.organization_id == user.organization_id,
        AIGeneration.created_at >= month))).all())
    durations = sorted(row.duration_ms for row in rows if row.duration_ms is not None)
    def percentile(fraction):
        if not durations:
            return None
        import math
        return durations[max(0, math.ceil(len(durations) * fraction) - 1)]
    return {"period_start": month.isoformat(), "scenario": "repair_draft",
        "cost_basis": "local_estimate_not_cloud_balance", "calls": len(rows),
        "statuses": {status: sum(row.status == status for row in rows)
                     for status in ("pending", "succeeded", "failed", "unknown")},
        "applied": sum(row.applied_at is not None for row in rows),
        "rejected": sum(row.rejected_at is not None for row in rows),
        "saved_repairs": sum(row.repair_id is not None for row in rows),
        "helpful": sum(row.rating == "helpful" for row in rows),
        "not_helpful": sum(row.rating == "not_helpful" for row in rows),
        "input_tokens": sum(row.input_tokens or 0 for row in rows),
        "output_tokens": sum(row.output_tokens or 0 for row in rows),
        "estimated_rub": str(sum((row.estimated_rub or Decimal(0) for row in rows), Decimal(0))),
        "unresolved_reserve_rub": str(sum((row.reserved_rub for row in rows if row.estimated_rub is None), Decimal(0))),
        "latency_ms": {"samples": len(durations), "p50": percentile(.5), "p95": percentile(.95)},
        "scope": "current_organization_only_excludes_cli_and_other_services"}
