from __future__ import annotations

import base64
import asyncio
import hmac
import json
import logging
import math
import os
import re
import secrets
import uuid
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from fastapi import BackgroundTasks, Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, Field
from sqlalchemy import Boolean, DateTime, Integer, JSON, String, Text, create_engine, select, update
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from storage_service import StorageService

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./demo.db")
engine = create_engine(
    DATABASE_URL, pool_pre_ping=True,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(engine, expire_on_commit=False)
storage = StorageService()
COMPANY = {"company_name": os.getenv("COMPANY_NAME", "Тёплый балкон"), "city": os.getenv("COMPANY_CITY", "Уфа"),
           "phone": os.getenv("COMPANY_PHONE", ""), "service_area": os.getenv("SERVICE_AREA", "Уфа"),
           "measurement_duration_minutes": int(os.getenv("MEASUREMENT_DURATION_MINUTES", "60")),
           "currency": os.getenv("CURRENCY", "RUB"), "working_hours": os.getenv("WORKING_HOURS", "09:00-19:00")}
BUSINESS_TZ = ZoneInfo(os.getenv("BUSINESS_TIMEZONE", "Asia/Yekaterinburg"))
app = FastAPI(title="AI-замерщик", version="0.1.0")
logger = logging.getLogger(__name__)
basic = HTTPBasic()
_request_times: dict[str, deque] = defaultdict(deque)


@app.middleware("http")
async def public_rate_limit(request: Request, call_next):
    if request.url.path.startswith("/api/") and request.url.path != "/api/health":
        forwarded = request.headers.get("x-forwarded-for", "")
        address = forwarded.split(",", 1)[0].strip() if forwarded else (request.client.host if request.client else "unknown")
        now = datetime.now(timezone.utc).timestamp()
        recent = _request_times[address]
        while recent and recent[0] < now - 60:
            recent.popleft()
        if len(recent) >= 90:
            return JSONResponse({"detail": "Слишком много запросов. Попробуйте через минуту."}, status_code=429)
        recent.append(now)
    return await call_next(request)


class Base(DeclarativeBase):
    pass


class ChatSession(Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    channel: Mapped[str] = mapped_column(String, default="web")
    external_user_id: Mapped[str | None] = mapped_column(String, nullable=True)
    external_chat_id: Mapped[str | None] = mapped_column(String, nullable=True)
    current_stage: Mapped[str] = mapped_column(String, default="INTENT")
    state: Mapped[dict] = mapped_column(JSON, default=dict)
    photo_keys: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[str] = mapped_column(String, index=True)
    role: Mapped[str] = mapped_column(String)
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class PriceItem(Base):
    __tablename__ = "price_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String, unique=True)
    name: Mapped[str] = mapped_column(String)
    unit: Mapped[str] = mapped_column(String, default="комплект")
    price_min: Mapped[int] = mapped_column(Integer)
    price_max: Mapped[int] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    demo: Mapped[bool] = mapped_column(Boolean, default=True)


class MeasurementSlot(Base):
    __tablename__ = "measurement_slots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String, default="available", index=True)
    lead_id: Mapped[str | None] = mapped_column(String, nullable=True)


class Lead(Base):
    __tablename__ = "leads"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    status: Mapped[str] = mapped_column(String, default="new")
    channel: Mapped[str] = mapped_column(String)
    session_id: Mapped[str] = mapped_column(String, index=True)
    customer_name: Mapped[str] = mapped_column(String)
    phone: Mapped[str] = mapped_column(String)
    address: Mapped[str] = mapped_column(Text)
    consent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    estimate_state: Mapped[dict] = mapped_column(JSON)
    estimate_min: Mapped[int] = mapped_column(Integer)
    estimate_max: Mapped[int] = mapped_column(Integer)
    calculation_details: Mapped[list] = mapped_column(JSON)
    desired_timeline: Mapped[str] = mapped_column(String, default="")
    budget: Mapped[str] = mapped_column(String, default="")
    appointment_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    utm: Mapped[dict] = mapped_column(JSON, default=dict)
    photo_count: Mapped[int] = mapped_column(Integer, default=0)
    vision_summary: Mapped[str] = mapped_column(Text, default="")


class Photo(Base):
    __tablename__ = "photos"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[str] = mapped_column(String, index=True)
    storage_key: Mapped[str] = mapped_column(String)
    mime_type: Mapped[str] = mapped_column(String)
    size: Mapped[int] = mapped_column(Integer)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class ProductEvent(Base):
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, index=True)
    channel: Mapped[str] = mapped_column(String)
    session_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class WebhookEvent(Base):
    __tablename__ = "webhook_events"
    event_id: Mapped[str] = mapped_column(String, primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    session_id: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


PRICE_SEED = [
    # Demo-only benchmark based on public Ufa price examples. Values are
    # normalized to a rough 4 m reference and are not a partner quote.
    ("cold_glazing", "Холодное остекление", 52000, 66000),
    ("warm_glazing", "Тёплое остекление", 72000, 110000),
    ("demolition", "Демонтаж старого остекления", 7000, 16000),
    ("interior_finish", "Внутренняя отделка", 30000, 36000),
    ("insulation", "Утепление пола и стен", 14000, 20000),
    ("electric", "Свет и розетки", 500, 4000),
    ("exterior_finish", "Наружная отделка", 6000, 10000),
    ("window_sill", "Подоконник", 1000, 3000),
    ("wardrobe", "Шкаф для хранения", 5000, 15000),
    ("roof", "Козырёк / крыша", 14000, 18000),
]


def db_session():
    with SessionLocal() as db:
        yield db


def emit(db: Session, name: str, channel: str, session_id: str | None = None, payload: dict | None = None):
    db.add(ProductEvent(name=name, channel=channel, session_id=session_id, payload=payload or {}))


def seed(db: Session):
    for code, name, low, high in PRICE_SEED:
        if not db.scalar(select(PriceItem).where(PriceItem.code == code)):
            db.add(PriceItem(code=code, name=name, price_min=low, price_max=high, unit="комплект", demo=True))
    if not db.scalar(select(MeasurementSlot.id).limit(1)):
        now = datetime.now(BUSINESS_TZ)
        for day in range(1, 8):
            for hour in (11, 14, 17):
                start = (now + timedelta(days=day)).replace(hour=hour, minute=0, second=0, microsecond=0)
                db.add(MeasurementSlot(start_at=start, end_at=start + timedelta(hours=1), status="available"))
    db.commit()


def purge_expired_data(db: Session):
    days = int(os.getenv("DATA_RETENTION_DAYS", "180"))
    if days <= 0:
        return
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    expired = db.scalars(select(ChatSession).where(ChatSession.created_at < cutoff)).all()
    for session in expired:
        leads = db.scalars(select(Lead).where(Lead.session_id == session.id)).all()
        for lead in leads:
            slot = db.scalar(select(MeasurementSlot).where(MeasurementSlot.lead_id == lead.id))
            if slot:
                slot.status, slot.lead_id = "available", None
            db.delete(lead)
        for key in session.photo_keys or []:
            try:
                storage.delete(key)
            except Exception:
                pass
        db.query(Message).filter(Message.session_id == session.id).delete()
        db.query(Photo).filter(Photo.session_id == session.id).delete()
        db.delete(session)
    db.commit()


@app.on_event("startup")
async def startup():
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        purge_expired_data(db)
        seed(db)
    await replay_pending_webhooks()


class StartRequest(BaseModel):
    channel: str = "web"
    utm: dict[str, str] = Field(default_factory=dict)


class EventRequest(BaseModel):
    name: str
    channel: str = "web"
    session_id: str | None = None
    payload: dict = Field(default_factory=dict)


class TextRequest(BaseModel):
    text: str = Field(min_length=1, max_length=3000)


class ContactRequest(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    phone: str
    address: str = Field(min_length=3, max_length=500)
    consent: bool


class BookRequest(BaseModel):
    slot_id: int


class PriceRequest(BaseModel):
    name: str
    price_min: int = Field(ge=0)
    price_max: int = Field(ge=0)
    enabled: bool = True


class SlotRequest(BaseModel):
    start_at: datetime
    end_at: datetime


def value(state: dict, key: str, default=None):
    item = state.get(key)
    return item.get("value", default) if isinstance(item, dict) else default


async def llm_extract(text: str, paths: list[str]) -> dict:
    """Provider adapter: OpenAI-compatible JSON chat endpoint; secrets stay server-side."""
    token = os.getenv("AI_API_KEY")
    if not token:
        return {}
    fields_prompt = (
        "intent, object_type, shape, usage_mode, glazing_mode, existing_glazing, approx_length_m, "
        "approx_depth_m, approx_height_m, demolition_required, interior_finish, wall_finish, "
        "ceiling_finish, floor_finish, insulation_floor, insulation_walls, insulation_ceiling, "
        "exterior_finish, lighting, sockets_count, window_sill, storage, roof_required, "
        "other_requests, desired_timeline, budget"
    )
    if paths:
        instruction = (
            "Осмотри фото и верни JSON вида {\"fields\": {\"object_type\": "
            "{\"value\": \"loggia\", \"confidence\": 0.9}}, \"summary\": \"...\"}. "
            f"Допустимые поля: {fields_prompt}. Включай только визуально обоснованные признаки. "
            "Для каждого признака дай confidence от 0 до 1. Размеры по фото без масштаба не определяй "
            "точно: если нет надежной опоры для оценки, пропусти размер. Не делай выводов о скрытых работах."
        )
    else:
        instruction = (
            f"Извлеки только явно сообщенные пользователем значения полей: {fields_prompt}. "
            "Верни JSON с полями верхнего уровня. Не додумывай неизвестные значения.\n" + text
        )
    content: list[dict] = [{"type": "text", "text": instruction}]
    for key in paths[:4]:
        raw = storage.get(key)
        suffix = Path(key).suffix.lower()
        mime = {".png": "image/png", ".webp": "image/webp", ".heic": "image/heic"}.get(suffix, "image/jpeg")
        content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{base64.b64encode(raw).decode()}"}})
    base = os.getenv("AI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    headers = {"Authorization": f"{os.getenv('AI_AUTH_SCHEME', 'Bearer')} {token}"}
    project_id = os.getenv("AI_PROJECT_ID")
    if project_id:
        headers["OpenAI-Project"] = project_id
    async with httpx.AsyncClient(timeout=22) as client:
        response = await client.post(
            f"{base}/chat/completions", headers=headers,
            json={"model": os.getenv("AI_MODEL", "gpt-4o-mini"), "messages": [{"role": "user", "content": content}], "response_format": {"type": "json_object"}},
        )
        response.raise_for_status()
        data = json.loads(response.json()["choices"][0]["message"]["content"])
        return data if isinstance(data, dict) else {}


class LLMService:
    """Replaceable text understanding adapter. A missing provider falls back to the demo parser."""
    async def extract(self, text: str) -> dict:
        return await llm_extract(text, [])


class VisionService:
    """Replaceable multimodal adapter. It returns only fields from the configured model."""
    async def analyze(self, text: str, photo_keys: list[str]) -> dict:
        return await llm_extract(text, photo_keys)


llm_service = LLMService()
vision_service = VisionService()


async def extract_fields(text: str, paths: list[str] | None = None) -> tuple[dict, str]:
    fields: dict[str, Any] = {}
    vision_note = ""
    if paths and not os.getenv("AI_API_KEY"):
        vision_note = "Фото сохранены. Vision-модель пока не подключена; продолжим уточнять детали вопросами."
    try:
        fields = await vision_service.analyze(text, paths) if paths else await llm_service.extract(text)
        if paths and isinstance(fields, dict):
            # Normalize the confidence envelope; tolerate a legacy flat response conservatively.
            raw_fields = fields.get("fields") if isinstance(fields.get("fields"), dict) else fields
            normalized = {}
            for key, item in raw_fields.items():
                if key not in {"intent", "object_type", "shape", "usage_mode", "glazing_mode", "profile_type", "existing_glazing", "approx_length_m", "approx_depth_m", "approx_height_m", "demolition_required", "interior_finish", "wall_finish", "ceiling_finish", "floor_finish", "insulation", "insulation_floor", "insulation_walls", "insulation_ceiling", "exterior_finish", "lighting", "sockets_count", "window_sill", "storage", "roof_required", "desired_timeline", "budget", "other_requests"}:
                    continue
                if isinstance(item, dict) and "value" in item:
                    confidence = item.get("confidence", 0.5)
                    try:
                        confidence = max(0.0, min(float(confidence), 1.0))
                    except (TypeError, ValueError):
                        confidence = 0.0
                    normalized[key] = {"value": item["value"], "confidence": confidence}
                elif key not in ("summary", "vision_summary") and item is not None:
                    normalized[key] = {"value": item, "confidence": 0.35 if key.startswith("approx_") else 0.5}
            fields = normalized
        if paths and os.getenv("AI_API_KEY"):
            vision_note = "Фото обработаны Vision-моделью. Размеры по фото считаются ориентировочными."
    except Exception:
        # Preserve the session and continue with the deterministic parser.
        if paths:
            vision_note = "Не удалось проанализировать фото; продолжим без них."
    lower = text.lower()
    if any(term in lower for term in ("балкон", "лоджи", "остекл", "застек", "утепл")):
        fields.setdefault("intent", "glazing")
    if any(term in lower for term in ("круглый год", "зимой", "тёпл", "тепл")):
        fields.setdefault("usage_mode", "year_round")
        fields.setdefault("glazing_mode", "warm")
    if "утепл" in lower:
        fields.setdefault("insulation", True)
    if "алюмин" in lower:
        fields.setdefault("existing_glazing", "old_aluminum")
    match = re.search(r"(\d+(?:[,.]\d+)?)\s*(?:м(?:етр(?:а|ов)?)?)", lower)
    if match:
        fields.setdefault("approx_length_m", float(match.group(1).replace(",", ".")))
    if "под ключ" in lower:
        fields.setdefault("interior_finish", "full")
    elif "отделк" in lower:
        fields.setdefault("interior_finish", "simple")
    if "свет" in lower:
        fields.setdefault("lighting", True)
        fields.setdefault("other_requests", "lighting")
    if "розет" in lower:
        socket_match = re.search(r"(\d+)\s*розет", lower)
        count = int(socket_match.group(1)) if socket_match else 2 if any(word in lower for word in ("две розет", "двух розет")) else 3 if "три розет" in lower else 1
        fields.setdefault("sockets_count", count)
        fields.setdefault("other_requests", "electrical")
    if any(term in lower for term in ("шкаф", "подоконник", "хранение")):
        fields.setdefault("other_requests", text)
    if lower.strip() == "ничего":
        fields.setdefault("other_requests", "none")
    sockets = re.search(r"(\d+)\s*розет", lower)
    if sockets:
        fields.setdefault("sockets_count", int(sockets.group(1)))
    if "срочно" in lower or "как можно скорее" in lower:
        fields.setdefault("desired_timeline", "asap")
    elif "месяц" in lower:
        fields.setdefault("desired_timeline", "month")
    return fields, vision_note


def merge_state(session: ChatSession, fields: dict, source="user", confidence=0.9):
    state = dict(session.state or {})
    allowed = {"intent", "object_type", "shape", "usage_mode", "glazing_mode", "profile_type", "existing_glazing", "approx_length_m", "approx_depth_m", "approx_height_m", "demolition_required", "interior_finish", "wall_finish", "ceiling_finish", "floor_finish", "insulation", "insulation_floor", "insulation_walls", "insulation_ceiling", "exterior_finish", "lighting", "sockets_count", "window_sill", "storage", "roof_required", "desired_timeline", "budget", "other_requests", "photos_skipped", "size_unknown", "customer_name", "phone", "address"}
    for key, val in fields.items():
        if key in allowed and val is not None:
            field_confidence = confidence
            if isinstance(val, dict) and "value" in val:
                field_confidence = val.get("confidence", confidence)
                val = val["value"]
            field_source = "vision" if source == "vision" or key.startswith("vision_") else source
            state[key] = {"value": val, "source": field_source, "confidence": field_confidence}
    session.state = state
    session.updated_at = datetime.now(timezone.utc)


def next_question(session: ChatSession) -> tuple[str, list[str], str] | None:
    state = session.state or {}
    if not value(state, "intent"):
        session.current_stage = "INTENT"
        return "Что хотите сделать с балконом или лоджией?", ["Застеклить", "Заменить старое остекление", "Утеплить", "Сделать под ключ", "Пока не знаю"], "ask_question"
    if not session.photo_keys and not value(state, "photos_skipped"):
        session.current_stage = "PHOTOS"
        return "Можете прислать 2–4 фото: общий вид, остекление и боковые стены. Фото необязательно.", ["Добавить фото", "Продолжить без фото"], "request_photos"
    if not value(state, "usage_mode"):
        session.current_stage = "REQUIREMENTS"
        return "Как планируете использовать балкон?", ["Хранение / летом", "Весной и осенью", "Круглый год", "Как продолжение комнаты", "Пока не знаю"], "ask_question"
    length_item = state.get("approx_length_m") if isinstance(state.get("approx_length_m"), dict) else {}
    length_is_confirmed = length_item.get("source") != "vision" or float(length_item.get("confidence", 0)) >= 0.7
    if (not value(state, "approx_length_m") or not length_is_confirmed) and not value(state, "size_unknown"):
        session.current_stage = "DIMENSIONS"
        return "Примерно какая длина балкона по передней стороне?", ["≈3 м", "≈4 м", "≈6 м", "Другой размер", "Не знаю"], "ask_question"
    if value(state, "interior_finish") is None:
        session.current_stage = "OPTIONS"
        return "Нужна внутренняя отделка?", ["Только остекление", "Простая отделка", "Полностью под ключ", "Пока не знаю"], "ask_question"
    if value(state, "other_requests") is None:
        session.current_stage = "OPTIONS"
        return "Что ещё хотелось бы сделать? Можно выбрать несколько услуг или написать своими словами.", ["Свет", "Розетки", "Шкаф", "Подоконник", "Ничего"] , "ask_question"
    if value(state, "desired_timeline") is None:
        session.current_stage = "OPTIONS"
        return "Когда планируете делать?", ["Как можно скорее", "В течение месяца", "1–3 месяца", "Просто узнаю цену"], "ask_question"
    return None


def quick_reply_fields(text: str, session: ChatSession) -> dict | None:
    lower = text.strip().lower()
    state = session.state or {}
    if lower == "пока не знаю" and session.current_stage == "INTENT":
        return {"intent": "undecided"}
    if lower == "продолжить без фото":
        return {"photos_skipped": True}
    if lower in ("не знаю", "пока не знаю") and session.current_stage == "DIMENSIONS":
        return {"size_unknown": True}
    if lower in ("не знаю", "пока не знаю") and session.current_stage == "REQUIREMENTS":
        return {"usage_mode": "undecided"}
    if lower in ("не знаю", "пока не знаю") and session.current_stage == "OPTIONS":
        if value(state, "interior_finish") is None:
            return {"interior_finish": "undecided"}
        if value(state, "other_requests") is None:
            return {"other_requests": "undecided"}
        return {"desired_timeline": "researching"}
    if lower in ("застеклить", "заменить старое остекление", "утеплить", "сделать под ключ"):
        fields = {"intent": "glazing"}
        if "под ключ" in lower:
            fields["interior_finish"] = "full"
        if "утепл" in lower:
            fields["insulation"] = True
        return fields
    if lower == "только остекление":
        return {"interior_finish": "none"}
    if lower == "простая отделка":
        return {"interior_finish": "simple"}
    if lower == "полностью под ключ":
        return {"interior_finish": "full"}
    if lower == "ничего":
        return {"other_requests": "none"}
    if lower in ("≈3 м", "≈3м", "3 м"):
        return {"approx_length_m": 3}
    if lower in ("≈4 м", "≈4м", "4 м"):
        return {"approx_length_m": 4}
    if lower in ("≈6 м", "≈6м", "6 м"):
        return {"approx_length_m": 6}
    if "круглый год" in lower or "зимой" in lower:
        return {"usage_mode": "year_round", "glazing_mode": "warm"}
    if "весной" in lower:
        return {"usage_mode": "seasonal"}
    if "летом" in lower or "хранение" in lower:
        return {"usage_mode": "summer"}
    if lower in ("как можно скорее", "в течение месяца", "1–3 месяца", "1-3 месяца", "просто узнаю цену"):
        return {"desired_timeline": "asap" if "скорее" in lower else "month" if "месяц" in lower else "1-3 months" if "1" in lower else "researching"}
    return None


def calculate(state: dict, db: Session) -> dict:
    length_item = state.get("approx_length_m") if isinstance(state.get("approx_length_m"), dict) else {}
    length = value(state, "approx_length_m")
    if length_item.get("source") == "vision" and float(length_item.get("confidence", 0)) < 0.7:
        length = None
    try:
        length = float(length) if length is not None else None
    except (TypeError, ValueError):
        length = None
    if length is not None and (not math.isfinite(length) or length <= 0 or length > 20):
        length = None
    scale = max(0.65, min(float(length or 4.0) / 4, 2.0))
    glazing = "warm" if value(state, "glazing_mode") == "warm" or value(state, "usage_mode") == "year_round" else "cold"
    codes = [f"{glazing}_glazing"]
    if value(state, "existing_glazing") not in (None, "none", "unknown"):
        codes.append("demolition")
    if value(state, "insulation") or value(state, "usage_mode") == "year_round":
        codes.append("insulation")
    if value(state, "insulation_floor") or value(state, "insulation_walls") or value(state, "insulation_ceiling"):
        if "insulation" not in codes:
            codes.append("insulation")
    if value(state, "interior_finish") in ("simple", "full"):
        codes.append("interior_finish")
    extras = str(value(state, "other_requests", "")).lower()
    if value(state, "lighting") or value(state, "sockets_count") or "свет" in extras or "розет" in extras:
        codes.append("electric")
    if value(state, "exterior_finish") or "наруж" in extras:
        codes.append("exterior_finish")
    if value(state, "window_sill") or "подокон" in extras:
        codes.append("window_sill")
    if value(state, "storage") or "шкаф" in extras:
        codes.append("wardrobe")
    if value(state, "roof_required") or "крыш" in extras or "козыр" in extras:
        codes.append("roof")
    items = []
    for code in codes:
        item = db.scalar(select(PriceItem).where(PriceItem.code == code, PriceItem.enabled.is_(True)))
        if item:
            items.append({"code": code, "name": item.name, "min": round(item.price_min * scale), "max": round(item.price_max * scale), "demo": item.demo})
    low, high = sum(x["min"] for x in items), sum(x["max"] for x in items)
    confidence = "medium" if length else "low"
    low = int(round(low * (0.95 if length else 0.85) / 1000) * 1000)
    high = int(round(high * (1.12 if length else 1.38) / 1000) * 1000)
    return {"price_min": low, "price_max": high, "items": items, "confidence": confidence, "demo": any(item["demo"] for item in items), "currency": "₽"}


def write_message(db: Session, session: ChatSession, role: str, text: str):
    db.add(Message(session_id=session.id, role=role, text=text[:3000]))


def phone_normalize(raw: str) -> str:
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    if len(digits) == 10:
        digits = "7" + digits
    if len(digits) != 11 or not digits.startswith("7"):
        raise HTTPException(422, "Введите российский номер телефона")
    return "+" + digits


def validate_photo(mime: str, raw: bytes) -> bool:
    signatures = {
        "image/jpeg": raw.startswith(b"\xff\xd8"),
        "image/png": raw.startswith(b"\x89PNG"),
        "image/webp": len(raw) >= 12 and raw[:4] == b"RIFF" and raw[8:12] == b"WEBP",
        "image/heic": len(raw) >= 12 and raw[4:8] == b"ftyp",
    }
    if mime not in signatures:
        raise HTTPException(415, "Поддерживаются JPG, PNG, WEBP и HEIC")
    if not raw or len(raw) > 10 * 1024 * 1024:
        raise HTTPException(413, "Размер одного фото — до 10 МБ")
    if not signatures[mime]:
        raise HTTPException(415, "Файл не похож на изображение заявленного типа")
    return True


def reserve_slot(db: Session, slot_id: int, lead_id: str) -> bool:
    result = db.execute(update(MeasurementSlot).where(
        MeasurementSlot.id == slot_id, MeasurementSlot.status == "available"
    ).values(status="reserved", lead_id=lead_id))
    return result.rowcount == 1


def claim_webhook_event(db: Session, event_id: str, payload: dict | None = None) -> bool:
    if db.get(WebhookEvent, event_id):
        return False
    db.add(WebhookEvent(event_id=event_id, payload=payload or {}, status="pending"))
    try:
        db.flush()
    except Exception:
        db.rollback()
        return False
    return True


def slots_payload(db: Session):
    now = datetime.now(BUSINESS_TZ)
    return [{"id": slot.id, "start_at": slot.start_at.isoformat()} for slot in db.scalars(
        select(MeasurementSlot).where(MeasurementSlot.status == "available", MeasurementSlot.start_at >= now).order_by(MeasurementSlot.start_at).limit(6)
    ).all()]


def lead_payload(lead: Lead):
    return {"id": lead.id, "created_at": lead.created_at.isoformat(), "status": lead.status, "channel": lead.channel,
            "customer_name": lead.customer_name, "phone": lead.phone, "address": lead.address,
            "estimate_state": lead.estimate_state, "estimate_min": lead.estimate_min, "estimate_max": lead.estimate_max,
            "calculation_details": lead.calculation_details, "desired_timeline": lead.desired_timeline,
            "budget": lead.budget, "appointment_at": lead.appointment_at.isoformat() if lead.appointment_at else None,
            "photo_count": lead.photo_count, "utm": lead.utm}


async def notify_business(lead: Lead):
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return
    appointment = lead.appointment_at.astimezone(BUSINESS_TZ).strftime("%d.%m %H:%M") if lead.appointment_at else "не выбрано"
    price = f"Предварительно: {lead.estimate_min:,}–{lead.estimate_max:,} ₽" if lead.estimate_max else "Расчёт ещё не выполнялся"
    body = (f"🔥 НОВАЯ ЗАЯВКА\n\n{lead.customer_name}\n{lead.phone}\n\n{lead.address}\n\n"
            f"{price}\n"
            f"Планирует: {lead.desired_timeline or 'не указано'}\nЗамер: {appointment}\nФото: {lead.photo_count}").replace(",", " ")
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id": chat, "text": body})
            response.raise_for_status()
            if response.json().get("ok") is not True:
                raise RuntimeError("Telegram rejected the notification")
    except (httpx.HTTPError, ValueError, RuntimeError):
        # Lead remains committed if the notification provider is temporarily unavailable.
        logger.warning("Telegram notification could not be delivered for lead %s", lead.id)
        return


@app.get("/api/health")
def health():
    return {"status": "ok", "company": COMPANY}


@app.post("/api/events")
def track_event(req: EventRequest, db: Session = Depends(db_session)):
    if req.name not in {"landing_opened", "session_abandoned"} or req.channel not in ("web", "max"):
        raise HTTPException(422, "Событие не поддерживается")
    if req.name == "session_abandoned" and req.session_id:
        session = db.get(ChatSession, req.session_id)
        if not session or session.current_stage == "COMPLETE":
            return {"ok": True}
    emit(db, req.name, req.channel, req.session_id, req.payload)
    db.commit()
    return {"ok": True}


@app.post("/api/sessions")
def create_session(req: StartRequest, db: Session = Depends(db_session)):
    if req.channel not in ("web", "max"):
        raise HTTPException(422, "Неизвестный канал")
    session = ChatSession(channel=req.channel, state={"utm": req.utm})
    db.add(session)
    db.flush()
    write_message(db, session, "assistant", "Расскажите, что хотите сделать с балконом?")
    emit(db, "session_started", req.channel, session.id)
    db.commit()
    return {"session_id": session.id, "assistant_message": "Расскажите, что хотите сделать с балконом?", "quick_replies": ["Застеклить", "Заменить старое остекление", "Утеплить", "Сделать под ключ", "Пока не знаю"], "stage": "INTENT"}


@app.post("/api/sessions/{session_id}/messages")
async def send_message(session_id: str, req: TextRequest, db: Session = Depends(db_session)):
    session = db.get(ChatSession, session_id)
    if not session:
        raise HTTPException(404, "Сессия не найдена")
    text = req.text.strip()
    write_message(db, session, "user", text)
    emit(db, "first_message_sent", session.channel, session.id)
    lower = text.lower()
    if any(phrase in lower for phrase in ("специалист", "человек", "оператор", "позвоните")):
        session.current_stage = "HANDOFF"
        event = {"handoff_requested": {"value": True, "source": "user", "confidence": 1}}
        session.state = {**(session.state or {}), **event}
        answer = "Подключу специалиста. Сохраню уже собранную информацию, чтобы вам не пришлось повторять её заново. Оставьте телефон и адрес, пожалуйста."
        write_message(db, session, "assistant", answer)
        emit(db, "handoff_requested", session.channel, session.id)
        db.commit()
        return {"assistant_message": answer, "next_action": "request_contact", "stage": session.current_stage}
    if lower in ("застеклить", "заменить старое остекление", "утеплить", "сделать под ключ"):
        fields, _ = await extract_fields(text)
        if "под ключ" in lower:
            fields["interior_finish"] = "full"
        if "утепл" in lower:
            fields["insulation"] = True
    elif lower in ("не знаю", "пока не знаю") and session.current_stage == "DIMENSIONS":
        fields = {"size_unknown": True}
    elif lower == "пока не знаю" and session.current_stage == "INTENT":
        fields = {"intent": "undecided"}
    elif lower == "пока не знаю" and session.current_stage == "REQUIREMENTS":
        fields = {"usage_mode": "undecided"}
    elif lower == "пока не знаю" and session.current_stage == "OPTIONS":
        if value(session.state or {}, "interior_finish") is None:
            fields = {"interior_finish": "undecided"}
        elif value(session.state or {}, "other_requests") is None:
            fields = {"other_requests": "undecided"}
        else:
            fields = {"desired_timeline": "researching"}
    elif lower == "продолжить без фото":
        fields = {"photos_skipped": True}
    elif lower in ("только остекление",):
        fields = {"interior_finish": "none"}
    elif "простая отделка" in lower:
        fields = {"interior_finish": "simple"}
    elif "под ключ" in lower:
        fields = {"intent": "glazing", "interior_finish": "full"}
    elif "≈3" in lower or "3 м" in lower:
        fields = {"approx_length_m": 3}
    elif "≈4" in lower or "4 м" in lower:
        fields = {"approx_length_m": 4}
    elif "≈6" in lower or "6 м" in lower:
        fields = {"approx_length_m": 6}
    elif "круглый год" in lower or "зимой" in lower:
        fields = {"usage_mode": "year_round", "glazing_mode": "warm"}
    elif "весной" in lower:
        fields = {"usage_mode": "seasonal"}
    elif "летом" in lower:
        fields = {"usage_mode": "summer"}
    elif any(x in lower for x in ("срочно", "скорее")):
        fields = {"desired_timeline": "asap"}
    elif "месяц" in lower:
        fields = {"desired_timeline": "month"}
    elif "1–3" in lower or "1-3" in lower:
        fields = {"desired_timeline": "1-3 months"}
    elif "узнаю цену" in lower:
        fields = {"desired_timeline": "researching"}
    else:
        fields, _ = await extract_fields(text, session.photo_keys)
    merge_state(session, fields)
    question = next_question(session)
    if question:
        answer, choices, action = question
        response = {"assistant_message": answer, "quick_replies": choices, "next_action": action, "stage": session.current_stage, "estimate_state": session.state}
    else:
        estimate = calculate(session.state or {}, db)
        session.state = {**(session.state or {}), "estimate": {"value": estimate, "source": "derived", "confidence": 0.7 if estimate["confidence"] == "medium" else 0.4}}
        session.current_stage = "CONTACT"
        emit(db, "estimate_completed", session.channel, session.id)
        response = {"assistant_message": "Подготовил предварительный вариант. Точную стоимость специалист подтвердит после замера.", "next_action": "calculate", "stage": "CONTACT", "estimate": estimate, "estimate_state": session.state}
    write_message(db, session, "assistant", response["assistant_message"])
    db.commit()
    return response


@app.post("/api/sessions/{session_id}/photos")
async def upload_photos(session_id: str, files: list[UploadFile] = File(...), db: Session = Depends(db_session)):
    session = db.get(ChatSession, session_id)
    if not session:
        raise HTTPException(404, "Сессия не найдена")
    if not files or len(files) + len(session.photo_keys) > 4:
        raise HTTPException(413, "Можно загрузить не более четырёх фотографий")
    accepted = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/heic": ".heic"}
    for upload in files:
        if upload.content_type not in accepted:
            raise HTTPException(415, "Поддерживаются JPG, PNG, WEBP и HEIC")
        raw = await upload.read()
        validate_photo(upload.content_type, raw)
        key = f"{session.id}/{secrets.token_hex(16)}{accepted[upload.content_type]}"
        storage.save(key, raw, upload.content_type)
        session.photo_keys = [*session.photo_keys, key]
        db.add(Photo(session_id=session.id, storage_key=key, mime_type=upload.content_type, size=len(raw)))
    emit(db, "photos_uploaded", session.channel, session.id, {"count": len(files)})
    db.commit()
    vision_note = "Фото загружены. Сейчас посмотрю на объект…"
    fields, note = await extract_fields("", session.photo_keys)
    if fields:
        merge_state(session, fields, source="vision", confidence=0.65)
        vision_note = "По фото удалось уточнить некоторые детали. Размер по фотографии без масштаба не подтверждаю."
    if note:
        vision_note = note
    emit(db, "vision_completed", session.channel, session.id, {"photo_count": len(session.photo_keys), "fields_found": bool(fields)})
    db.commit()
    return {"count": len(session.photo_keys), "assistant_message": vision_note, "estimate_state": session.state}


@app.post("/api/sessions/{session_id}/contact")
async def submit_contact(session_id: str, req: ContactRequest, db: Session = Depends(db_session)):
    session = db.get(ChatSession, session_id)
    if not session:
        raise HTTPException(404, "Сессия не найдена")
    if not req.consent:
        raise HTTPException(422, "Подтвердите согласие на обработку данных")
    handoff = bool(value(session.state or {}, "handoff_requested", False))
    estimate_field = (session.state or {}).get("estimate", {})
    estimate = estimate_field.get("value") if isinstance(estimate_field, dict) else None
    estimate = estimate or (calculate(session.state or {}, db) if not handoff else {"price_min": 0, "price_max": 0, "items": []})
    digits = re.sub(r"\D", "", req.phone)
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    if len(digits) == 10:
        digits = "7" + digits
    if len(digits) != 11 or not digits.startswith("7"):
        raise HTTPException(422, "Введите российский номер телефона")
    lead = Lead(
        channel=session.channel, session_id=session.id, customer_name=req.name.strip(), phone="+" + digits,
        address=req.address.strip(), consent_at=datetime.now(timezone.utc), estimate_state=session.state or {},
        estimate_min=estimate["price_min"], estimate_max=estimate["price_max"], calculation_details=estimate["items"],
        desired_timeline=value(session.state or {}, "desired_timeline", ""), budget=value(session.state or {}, "budget", ""),
        utm=value(session.state or {}, "utm", {}), photo_count=len(session.photo_keys),
        vision_summary="Размер по фото не подтверждается; фотографии приложены к заявке." if session.photo_keys else "Фото не предоставлены.",
    )
    db.add(lead)
    session.current_stage = "SCHEDULING"
    emit(db, "contact_submitted", session.channel, session.id)
    if handoff:
        emit(db, "handoff_requested", session.channel, session.id)
    db.flush()
    db.commit()
    if handoff:
        await notify_business(lead)
        return {"lead_id": lead.id, "assistant_message": "Передал заявку специалисту. Он свяжется с вами по указанному телефону.", "next_action": "handoff"}
    return {"lead_id": lead.id, "assistant_message": "Спасибо! Выберите удобное время бесплатного замера.", "next_action": "show_slots"}


@app.get("/api/sessions/{session_id}/slots")
def get_slots(session_id: str, db: Session = Depends(db_session)):
    session = db.get(ChatSession, session_id)
    if not session:
        raise HTTPException(404, "Сессия не найдена")
    emit(db, "slots_shown", session.channel, session.id)
    db.commit()
    return slots_payload(db)


@app.post("/api/sessions/{session_id}/book")
async def book_slot(session_id: str, req: BookRequest, db: Session = Depends(db_session)):
    session = db.get(ChatSession, session_id)
    lead = db.scalar(select(Lead).where(Lead.session_id == session_id).order_by(Lead.created_at.desc()))
    if not session or not lead:
        raise HTTPException(409, "Сначала оставьте контакт")
    # Conditional update is atomic in PostgreSQL and prevents double booking.
    if not reserve_slot(db, req.slot_id, lead.id):
        existing = db.get(MeasurementSlot, req.slot_id)
        if existing and existing.status == "reserved" and existing.lead_id == lead.id:
            return {"assistant_message": "Готово! Замер запланирован.", "lead": lead_payload(lead)}
        db.rollback()
        raise HTTPException(409, "Это время уже заняли. Выберите другое.")
    slot = db.get(MeasurementSlot, req.slot_id)
    lead.appointment_at = slot.start_at
    lead.status = "measurement_scheduled"
    session.current_stage = "COMPLETE"
    emit(db, "measurement_scheduled", session.channel, session.id, {"slot_id": slot.id})
    db.commit()
    await notify_business(lead)
    return {"assistant_message": "Готово! Замер запланирован.", "lead": lead_payload(lead)}


def require_admin(credentials: HTTPBasicCredentials = Depends(basic)):
    username, password = os.getenv("ADMIN_USERNAME", "admin"), os.getenv("ADMIN_PASSWORD", "demo-change-me")
    if not (hmac.compare_digest(credentials.username, username) and hmac.compare_digest(credentials.password, password)):
        raise HTTPException(401, "Требуется вход", headers={"WWW-Authenticate": "Basic"})
    return credentials.username


@app.get("/admin", response_class=HTMLResponse)
def admin_page(_=Depends(require_admin)):
    return Path(__file__).with_name("admin.html").read_text(encoding="utf-8")
    return """<!doctype html><html lang='ru'><meta name='viewport' content='width=device-width'><title>Заявки</title><body style='font:15px system-ui;max-width:1000px;margin:32px auto;padding:16px;color:#203330'><h1>Заявки на замер</h1><section id='funnel'></section><section id='leads'></section><section><h2>Demo-прайс · суммы в рублях</h2><div id='prices'></div></section><section><h2>Расписание · добавить свободный слот</h2><form id='slotform' style='display:flex;gap:10px;flex-wrap:wrap'><label>Начало <input id='from' type='datetime-local' required></label><label>Конец <input id='to' type='datetime-local' required></label><button>Добавить слот</button></form><div id='slots'></div></section><script>
async function load(){let [fr,lr,pr,sr]=await Promise.all(['/admin/api/funnel','/admin/api/leads','/admin/api/prices','/admin/api/slots'].map(x=>fetch(x)));let f=await fr.json(),l=await lr.json(),p=await pr.json(),s=await sr.json();document.querySelector('#funnel').innerHTML='<h2>Воронка</h2><div style="display:flex;gap:10px;flex-wrap:wrap">'+Object.entries(f).map(([k,v])=>'<div style="background:#eef2e9;padding:12px;border-radius:10px"><b>'+v+'</b><br><small>'+k+'</small></div>').join('')+'</div>';document.querySelector('#leads').innerHTML='<h2>Заявки</h2>'+l.map(x=>'<article style="border:1px solid #ddd;padding:16px;margin:12px 0;border-radius:12px"><b>'+x.customer_name+'</b> · '+x.phone+' · '+x.channel+'<br>'+x.address+'<br>'+x.estimate_min+'–'+x.estimate_max+' ₽ · '+(x.appointment_at||'без записи')+' · '+x.photo_count+' фото <button onclick="removeLead(\''+x.id+'\')">Удалить данные</button></article>').join('');document.querySelector('#prices').innerHTML=p.map(x=>'<div style="padding:10px;border-bottom:1px solid #ddd"><b>'+x.name+'</b> '+(x.demo?'(DEMO)':'')+' <input id="min-'+x.code+'" type="number" value="'+x.price_min+'" style="width:110px"> – <input id="max-'+x.code+'" type="number" value="'+x.price_max+'" style="width:110px"> <button onclick="savePrice(\''+x.code+'\',\''+x.name+'\',\''+x.enabled+'\')">Сохранить</button></div>').join('');document.querySelector('#slots').innerHTML='<h3>Ближайшие слоты</h3>'+s.slice(0,30).map(x=>'<div>'+new Date(x.start_at).toLocaleString('ru-RU')+' · '+x.status+'</div>').join('')}
async function savePrice(code,name,enabled){await fetch('/admin/api/prices/'+code,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,price_min:Number(document.querySelector('#min-'+code).value),price_max:Number(document.querySelector('#max-'+code).value),enabled:enabled==='true'})});load()}
async function removeLead(id){if(confirm('Удалить контакт, сообщения и фотографии заявки?')){await fetch('/admin/api/leads/'+id,{method:'DELETE'});load()}}
document.querySelector('#slotform').addEventListener('submit',async e=>{e.preventDefault();await fetch('/admin/api/slots',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({start_at:new Date(document.querySelector('#from').value).toISOString(),end_at:new Date(document.querySelector('#to').value).toISOString()})});load()});load();</script></body></html>"""


@app.get("/admin/api/leads")
def admin_leads(_=Depends(require_admin), db: Session = Depends(db_session)):
    result = []
    for lead in db.scalars(select(Lead).order_by(Lead.created_at.desc())).all():
        payload = lead_payload(lead)
        session = db.get(ChatSession, lead.session_id)
        payload["messages"] = [{"role": item.role, "text": item.text, "created_at": item.created_at.isoformat()}
                                for item in db.scalars(select(Message).where(Message.session_id == lead.session_id).order_by(Message.created_at)).all()]
        payload["photos"] = [storage.signed_url(key) for key in (session.photo_keys if session else [])]
        payload["vision_summary"] = lead.vision_summary
        result.append(payload)
    return result


@app.get("/admin/api/photos/{key:path}")
def admin_photo(key: str, _=Depends(require_admin), db: Session = Depends(db_session)):
    photo = db.scalar(select(Photo).where(Photo.storage_key == key))
    if not photo:
        raise HTTPException(404, "Фото не найдено")
    if os.getenv("STORAGE_ENDPOINT"):
        from fastapi.responses import RedirectResponse
        return RedirectResponse(storage.signed_url(key), status_code=307)
    try:
        return Response(storage.get(key), media_type=photo.mime_type, headers={"Cache-Control": "private, no-store"})
    except OSError:
        raise HTTPException(404, "Файл не найден")


@app.delete("/admin/api/leads/{lead_id}")
def delete_lead(lead_id: str, _=Depends(require_admin), db: Session = Depends(db_session)):
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(404, "Заявка не найдена")
    session = db.get(ChatSession, lead.session_id)
    if session:
        for key in session.photo_keys:
            try:
                storage.delete(key)
            except OSError:
                pass
        db.query(Message).filter(Message.session_id == session.id).delete()
        db.query(Photo).filter(Photo.session_id == session.id).delete()
        db.delete(session)
    booked = db.scalar(select(MeasurementSlot).where(MeasurementSlot.lead_id == lead.id))
    if booked:
        booked.status, booked.lead_id = "cancelled", None
    db.delete(lead)
    db.commit()
    return {"ok": True}


@app.get("/admin/api/funnel")
def admin_funnel(_=Depends(require_admin), db: Session = Depends(db_session)):
    names = ["session_started", "first_message_sent", "photos_uploaded", "vision_completed", "estimate_completed", "contact_submitted", "slots_shown", "measurement_scheduled", "session_abandoned"]
    return {name: db.query(ProductEvent).filter(ProductEvent.name == name).count() for name in names}


@app.get("/admin/api/prices")
def admin_prices(_=Depends(require_admin), db: Session = Depends(db_session)):
    return [{"code": x.code, "name": x.name, "unit": x.unit, "price_min": x.price_min, "price_max": x.price_max, "enabled": x.enabled, "demo": x.demo} for x in db.scalars(select(PriceItem)).all()]


@app.put("/admin/api/prices/{code}")
def update_price(code: str, req: PriceRequest, _=Depends(require_admin), db: Session = Depends(db_session)):
    item = db.scalar(select(PriceItem).where(PriceItem.code == code))
    if not item:
        raise HTTPException(404, "Позиция не найдена")
    if req.price_min > req.price_max:
        raise HTTPException(422, "Минимум не может быть выше максимума")
    item.name, item.price_min, item.price_max, item.enabled = req.name, req.price_min, req.price_max, req.enabled
    item.demo = False
    db.commit()
    return {"ok": True}


@app.post("/admin/api/slots")
def add_slot(req: SlotRequest, _=Depends(require_admin), db: Session = Depends(db_session)):
    if req.end_at <= req.start_at:
        raise HTTPException(422, "Некорректный интервал")
    slot = MeasurementSlot(start_at=req.start_at, end_at=req.end_at, status="available")
    db.add(slot)
    db.commit()
    return {"id": slot.id, "start_at": slot.start_at.isoformat()}


@app.get("/admin/api/slots")
def admin_slots(_=Depends(require_admin), db: Session = Depends(db_session)):
    return [{"id": x.id, "start_at": x.start_at.isoformat(), "end_at": x.end_at.isoformat(), "status": x.status}
            for x in db.scalars(select(MeasurementSlot).order_by(MeasurementSlot.start_at.desc()).limit(100)).all()]


def normalize_max(payload: dict[str, Any]) -> dict[str, Any]:
    """Translate MAX Update into a channel-neutral event before core processing."""
    message = payload.get("message") or (payload.get("message_created") or {}).get("message") or {}
    body = message.get("body") or {}
    sender = message.get("sender") or payload.get("user") or {}
    recipient = message.get("recipient") or {}
    event_id = str(payload.get("update_id") or payload.get("event_id") or f"{payload.get('timestamp')}:{body.get('mid')}:{payload.get('update_type')}")
    callback = payload.get("callback") or {}
    return {"event_id": event_id, "kind": payload.get("update_type", ""), "chat_id": str(recipient.get("chat_id") or payload.get("chat_id") or ""),
            "user_id": str(sender.get("user_id") or sender.get("id") or ""), "text": body.get("text") or callback.get("payload") or "", "attachments": body.get("attachments") or []}


async def max_send(chat_id: str, text: str, choices: list[str] | None = None):
    token = os.getenv("MAX_BOT_TOKEN")
    if not token or not chat_id:
        return
    attachments = []
    if choices:
        buttons = []
        for choice in choices:
            if choice.startswith("SLOT:"):
                payload, label = choice.split(" · ", 1)
                buttons.append({"type": "callback", "text": label, "payload": payload})
            else:
                buttons.append({"type": "message", "text": choice})
        attachments = [{"type": "inline_keyboard", "payload": {"buttons": [[button] for button in buttons]}}]
    async with httpx.AsyncClient(timeout=8) as client:
        await client.post("https://platform-api2.max.ru/messages", headers={"Authorization": token}, params={"chat_id": chat_id}, json={"text": text, "attachments": attachments})


async def max_process_photo(attachment: dict, session: ChatSession, db: Session):
    payload = attachment.get("payload") or {}
    image_url = payload.get("url") or payload.get("image_url")
    if not image_url:
        return
    # Only fetch MAX-owned media URLs. Arbitrary URLs are rejected to avoid SSRF.
    host = httpx.URL(image_url).host or ""
    if not (host == "max.ru" or host.endswith(".max.ru")):
        return
    async with httpx.AsyncClient(timeout=12, follow_redirects=False) as client:
        response = await client.get(image_url)
        response.raise_for_status()
        mime = response.headers.get("content-type", "").split(";")[0]
        validate_photo(mime, response.content)
    suffix = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}[mime]
    key = f"{session.id}/{secrets.token_hex(16)}{suffix}"
    storage.save(key, response.content, mime)
    session.photo_keys = [*session.photo_keys, key][:4]
    db.add(Photo(session_id=session.id, storage_key=key, mime_type=mime, size=len(response.content), metadata_json={"source": "max"}))


def max_slot_choices(db: Session) -> list[str]:
    slots = slots_payload(db)
    return [f"SLOT:{item['id']} · {datetime.fromisoformat(item['start_at']).astimezone(BUSINESS_TZ).strftime('%d.%m %H:%M')}" for item in slots]


async def max_book(session: ChatSession, slot_id: int, db: Session) -> str:
    lead = db.scalar(select(Lead).where(Lead.session_id == session.id).order_by(Lead.created_at.desc()))
    if not lead:
        return "Не нашёл заявку. Напишите «Записаться», чтобы начать оформление."
    if not reserve_slot(db, slot_id, lead.id):
        already_booked = db.get(MeasurementSlot, slot_id)
        if already_booked and already_booked.status == "reserved" and already_booked.lead_id == lead.id:
            return f"Готово! Замер запланирован на {already_booked.start_at.astimezone(BUSINESS_TZ).strftime('%d.%m в %H:%M')}."
        db.rollback()
        return "Это время уже заняли. Напишите «время», чтобы показать другие варианты."
    slot = db.get(MeasurementSlot, slot_id)
    lead.appointment_at = slot.start_at
    lead.status = "measurement_scheduled"
    session.current_stage = "COMPLETE"
    emit(db, "measurement_scheduled", "max", session.id, {"slot_id": slot_id})
    db.commit()
    await notify_business(lead)
    return f"Готово! Замер запланирован на {slot.start_at.astimezone(BUSINESS_TZ).strftime('%d.%m в %H:%M')}. Скоро подтвердим запись по телефону."


async def max_contact_or_booking(text: str, chat_id: str, session: ChatSession, db: Session) -> bool:
    lower = text.strip().lower()
    slot_match = re.search(r"slot\s*:\s*(\d+)", lower)
    if slot_match:
        response = await max_book(session, int(slot_match.group(1)), db)
        await max_send(chat_id, response, max_slot_choices(db) if "уже заняли" in response else None)
        return True
    if lower in ("время", "показать слоты", "другое время"):
        choices = max_slot_choices(db)
        await max_send(chat_id, "Выберите удобное время (кнопки содержат код слота):", choices or None)
        return True
    if session.current_stage not in ("CONTACT", "SCHEDULING", "HANDOFF") and not (session.state or {}).get("estimate"):
        return False
    state = session.state or {}
    if not value(state, "consent_given"):
        if lower in ("согласен", "согласна", "принимаю", "да, согласен", "да, согласна"):
            session.state = {**state, "consent_given": {"value": True, "source": "user", "confidence": 1}}
            db.commit()
            await max_send(chat_id, "Спасибо. Пришлите одним сообщением имя, номер телефона и адрес объекта. Пример: Иван, +7 999 123-45-67, Уфа, улица Ленина, 10.")
        else:
            await max_send(chat_id, "Предварительный расчёт готов. Чтобы записать на замер, нужно ваше согласие на обработку имени, телефона и адреса по политике компании. Ответьте «Согласен» для продолжения.")
        return True
    phone_match = re.search(r"(?:\+?7|8)[\s(\)-]*\d[\d\s(\)-]{8,}\d", text)
    if not phone_match:
        await max_send(chat_id, "Не нашёл номер телефона. Пришлите имя, российский номер и адрес в одном сообщении.")
        return True
    try:
        phone = phone_normalize(phone_match.group(0))
    except HTTPException:
        await max_send(chat_id, "Проверьте номер: нужен российский номер, например +7 999 123-45-67.")
        return True
    remainder = (text[:phone_match.start()] + " " + text[phone_match.end():]).strip(" ,;—-\n")
    parts = [part.strip() for part in re.split(r"[,;\n]", remainder) if part.strip()]
    if len(parts) < 2:
        await max_send(chat_id, "Нужны имя и адрес объекта. Формат: Иван, +7 999 123-45-67, Уфа, улица, дом.")
        return True
    name, address = parts[0][:100], ", ".join(parts[1:])[:500]
    handoff = bool(value(state, "handoff_requested", False))
    estimate_field = state.get("estimate", {})
    estimate = estimate_field.get("value") if isinstance(estimate_field, dict) else None
    if not estimate and handoff:
        estimate = {"price_min": 0, "price_max": 0, "items": []}
    elif not estimate:
        estimate = calculate(state, db)
    lead = db.scalar(select(Lead).where(Lead.session_id == session.id).order_by(Lead.created_at.desc()))
    if not lead or lead.phone != phone:
        lead = Lead(channel="max", session_id=session.id, customer_name=name, phone=phone, address=address,
                    consent_at=datetime.now(timezone.utc), estimate_state=state, estimate_min=estimate["price_min"],
                    estimate_max=estimate["price_max"], calculation_details=estimate["items"],
                    desired_timeline=value(state, "desired_timeline", ""), budget=value(state, "budget", ""),
                    utm=value(state, "utm", {}), photo_count=len(session.photo_keys),
                    vision_summary="Фото сохранены; размер по фото не подтверждается." if session.photo_keys else "Фото не предоставлены.")
        db.add(lead)
    elif lead.appointment_at:
        await max_send(chat_id, f"Замер уже запланирован на {lead.appointment_at.astimezone(BUSINESS_TZ).strftime('%d.%m в %H:%M')}.")
        return True
    session.current_stage = "SCHEDULING"
    emit(db, "contact_submitted", "max", session.id, {"consent": True})
    db.commit()
    if handoff:
        await notify_business(lead)
        await max_send(chat_id, "Передал заявку специалисту. Он свяжется с вами по телефону.")
        return True
    choices = max_slot_choices(db)
    if choices:
        await max_send(chat_id, "Заявку сохранил. Выберите свободное время замера:", choices)
    else:
        await max_send(chat_id, "Заявку сохранил, но свободных слотов сейчас нет. Специалист свяжется с вами.")
    return True


async def process_max_event(update_data: dict[str, Any], session_id: str):
    """Do bounded attachment/AI work after the MAX webhook has received its 200 response."""
    with SessionLocal() as db:
        session = db.get(ChatSession, session_id)
        if not session:
            return
        chat_id = update_data["chat_id"]
        kind = update_data["kind"]
        if kind == "bot_started":
            question = next_question(session)
            await max_send(chat_id, question[0] if question else "Расскажите, что хотите сделать с балконом?", question[1] if question else None)
            return
        if kind not in ("message_created", "message_callback"):
            return
        for attachment in update_data["attachments"][:4]:
            if len(session.photo_keys) >= 4:
                break
            try:
                if attachment.get("type") == "image":
                    await max_process_photo(attachment, session, db)
            except (httpx.HTTPError, OSError, HTTPException):
                emit(db, "max_photo_failed", "max", session.id)
        text = update_data["text"]
        if text:
            write_message(db, session, "user", text)
            db.commit()
        if text and any(term in text.lower() for term in ("специалист", "человек", "оператор", "позвоните")):
            session.current_stage = "HANDOFF"
            session.state = {**(session.state or {}), "handoff_requested": {"value": True, "source": "user", "confidence": 1}}
            emit(db, "handoff_requested", "max", session.id)
            db.commit()
            await max_contact_or_booking(text, chat_id, session, db)
            return
        if text and await max_contact_or_booking(text, chat_id, session, db):
            return
        if text:
            fields = quick_reply_fields(text, session)
            if fields is None:
                fields, _ = await extract_fields(text, session.photo_keys)
            merge_state(session, fields)
        question = next_question(session)
        if question:
            answer, choices, _ = question
            write_message(db, session, "assistant", answer)
            emit(db, "first_message_sent", "max", session.id)
            db.commit()
            await max_send(chat_id, answer, choices)
            return
        estimate = calculate(session.state or {}, db)
        session.state = {**(session.state or {}), "estimate": {"value": estimate, "source": "derived", "confidence": 0.4}}
        session.current_stage = "CONTACT"
        emit(db, "estimate_completed", "max", session.id)
        answer = (f"Предварительно {estimate['price_min']:,}–{estimate['price_max']:,} ₽. Точную стоимость подтвердит замерщик. "
                  "Для записи сначала потребуется согласие на обработку данных.").replace(",", " ")
        write_message(db, session, "assistant", answer)
        db.commit()
        await max_send(chat_id, answer)


async def process_pending_webhook(event_id: str):
    with SessionLocal() as db:
        item = db.get(WebhookEvent, event_id)
        if not item or item.status != "pending" or not item.session_id:
            return
        payload, session_id = item.payload, item.session_id
        item.status = "processing"
        db.commit()
    try:
        await process_max_event(payload, session_id)
    except Exception:
        with SessionLocal() as db:
            item = db.get(WebhookEvent, event_id)
            if item:
                item.attempts += 1
                item.status = "pending" if item.attempts < 5 else "failed"
                if item.status == "failed":
                    item.payload = {}
                db.commit()
        return
    with SessionLocal() as db:
        item = db.get(WebhookEvent, event_id)
        if item:
            item.status = "processed"
            item.processed_at = datetime.now(timezone.utc)
            item.payload = {}  # Drop the copied message/photo URLs after durable processing.
            db.commit()


async def replay_pending_webhooks():
    with SessionLocal() as db:
        items = db.scalars(select(WebhookEvent).where(WebhookEvent.status.in_(("pending", "processing")))).all()
        event_ids = [item.event_id for item in items]
        for item in items:
            item.status = "pending"
        db.commit()
    for event_id in event_ids:
        asyncio.create_task(process_pending_webhook(event_id))


@app.post("/api/integrations/max/webhook")
async def max_webhook(request: Request, background_tasks: BackgroundTasks, db: Session = Depends(db_session), secret: str | None = Header(default=None, alias="X-Max-Bot-Api-Secret")):
    if not os.getenv("MAX_BOT_TOKEN"):
        raise HTTPException(503, "MAX integration is not enabled")
    expected = os.getenv("MAX_WEBHOOK_SECRET")
    if not expected:
        raise HTTPException(503, "MAX webhook secret is not configured")
    if expected and not secrets.compare_digest(secret or "", expected):
        raise HTTPException(401, "Invalid webhook secret")
    payload = await request.json()
    update_data = normalize_max(payload)
    existing = db.get(WebhookEvent, update_data["event_id"])
    if existing:
        if existing.status == "pending":
            background_tasks.add_task(process_pending_webhook, existing.event_id)
        return {"ok": True, "duplicate": True}
    if not claim_webhook_event(db, update_data["event_id"], update_data):
        return {"ok": True, "duplicate": True}
    kind, chat_id, user_id = update_data["kind"], update_data["chat_id"], update_data["user_id"]
    session = db.scalar(select(ChatSession).where(ChatSession.channel == "max", ChatSession.external_chat_id == chat_id)) if chat_id else None
    if not session:
        session = ChatSession(channel="max", external_chat_id=chat_id, external_user_id=user_id, state={})
        db.add(session)
        db.flush()
        emit(db, "session_started", "max", session.id)
    webhook = db.get(WebhookEvent, update_data["event_id"])
    webhook.session_id = session.id
    if kind not in ("bot_started", "message_created", "message_callback"):
        webhook.status = "processed"
        webhook.processed_at = datetime.now(timezone.utc)
        webhook.payload = {}
    db.commit()
    if kind in ("bot_started", "message_created", "message_callback"):
        background_tasks.add_task(process_pending_webhook, update_data["event_id"])
    return {"ok": True}
