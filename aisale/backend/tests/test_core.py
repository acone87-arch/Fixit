from datetime import datetime, timedelta, timezone
import asyncio

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from main import (
    Base, ChatSession, MeasurementSlot, PriceItem, WebhookEvent, calculate,
    claim_webhook_event, next_question, normalize_max, phone_normalize,
    reserve_slot, validate_photo, extract_fields, quick_reply_fields, merge_state,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)


def test_russian_phone_normalization_and_rejection():
    assert phone_normalize("8 (999) 123-45-67") == "+79991234567"
    assert phone_normalize("9991234567") == "+79991234567"
    with pytest.raises(HTTPException):
        phone_normalize("123")


def test_photo_signature_and_size_validation():
    assert validate_photo("image/jpeg", b"\xff\xd8payload")
    with pytest.raises(HTTPException):
        validate_photo("image/jpeg", b"not an image")
    with pytest.raises(HTTPException):
        validate_photo("image/svg+xml", b"<svg/>")


def test_next_question_skips_photo_and_unknown_size_without_fake_precision():
    session = ChatSession(state={"intent": {"value": "glazing", "source": "user", "confidence": 1},
                                 "photos_skipped": {"value": True, "source": "user", "confidence": 1}})
    prompt = next_question(session)
    assert prompt and prompt[2] == "ask_question"
    session.state = {**session.state,
        "usage_mode": {"value": "year_round", "source": "user", "confidence": 1},
        "size_unknown": {"value": True, "source": "user", "confidence": 1},
        "interior_finish": {"value": "none", "source": "user", "confidence": 1},
        "other_requests": {"value": "none", "source": "user", "confidence": 1},
        "desired_timeline": {"value": "month", "source": "user", "confidence": 1}}
    assert next_question(session) is None
    db_engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(db_engine)
    with Session(db_engine) as db:
        db.add(PriceItem(code="warm_glazing", name="Тёплое остекление", price_min=90000, price_max=125000))
        db.add(PriceItem(code="insulation", name="Утепление", price_min=18000, price_max=38000))
        db.flush()
        estimate = calculate(session.state, db)
    Base.metadata.drop_all(db_engine)
    assert estimate["confidence"] == "low"
    assert estimate["price_max"] > estimate["price_min"]
    assert estimate["demo"] is True


def test_demo_parser_and_vision_provider_failure_are_transparent(monkeypatch):
    monkeypatch.delenv("AI_API_KEY", raising=False)
    fields, note = asyncio.run(extract_fields("Хочу утеплить лоджию, примерно 3,6 м, свет и две розетки"))
    assert fields["intent"] == "glazing"
    assert fields["approx_length_m"] == 3.6
    assert fields["sockets_count"] == 2
    _, vision_note = asyncio.run(extract_fields("", ["missing.jpg"]))
    assert "Vision" in vision_note
    assert "обработаны Vision-моделью" not in note


def test_quick_reply_is_aware_of_current_stage():
    session = ChatSession(current_stage="DIMENSIONS", state={})
    assert quick_reply_fields("Не знаю", session) == {"size_unknown": True}
    session.current_stage = "OPTIONS"
    assert quick_reply_fields("Пока не знаю", session) == {"interior_finish": "undecided"}


def test_low_confidence_vision_dimension_is_not_treated_as_confirmed(db):
    session = ChatSession(state={"usage_mode": {"value": "year_round", "source": "user", "confidence": 1}},
                          photo_keys=["photo.jpg"])
    merge_state(session, {"intent": "glazing", "approx_length_m": {"value": 3.6, "confidence": 0.42}},
                source="vision", confidence=0.65)
    assert session.state["approx_length_m"]["source"] == "vision"
    assert session.state["approx_length_m"]["confidence"] == 0.42
    prompt = next_question(session)
    assert prompt and "длина" in prompt[0]
    session.state.update({
        "photos_skipped": {"value": True},
        "usage_mode": {"value": "year_round"},
        "interior_finish": {"value": "none"},
        "other_requests": {"value": "none"},
        "desired_timeline": {"value": "month"},
    })
    result = calculate(session.state, db)
    assert result["confidence"] == "low"


def test_price_engine_is_deterministic_and_never_accepts_llm_price(db):
    db.add_all([
        PriceItem(code="warm_glazing", name="Warm", price_min=90000, price_max=120000),
        PriceItem(code="insulation", name="Insulation", price_min=20000, price_max=30000),
    ])
    db.flush()
    state = {"usage_mode": {"value": "year_round"}, "approx_length_m": {"value": 4},
             "estimate_min": {"value": 1_000_000_000}}
    first = calculate(state, db)
    assert first == calculate(state, db)
    assert first["price_min"] < 1_000_000_000
    assert [x["code"] for x in first["items"]] == ["warm_glazing", "insulation"]


def test_price_engine_widens_for_invalid_or_implausible_model_dimensions(db):
    db.add(PriceItem(code="cold_glazing", name="Cold", price_min=50000, price_max=80000))
    db.flush()
    unknown = calculate({"approx_length_m": {"value": "примерно четыре"}}, db)
    absurd = calculate({"approx_length_m": {"value": 300}}, db)
    assert unknown["confidence"] == absurd["confidence"] == "low"
    assert unknown["price_min"] == absurd["price_min"]
    assert unknown["price_max"] == absurd["price_max"]


def test_max_normalization_and_duplicate_webhook_claim(db):
    payload = {"update_type": "message_created", "timestamp": 12345, "chat_id": 77,
               "message": {"sender": {"user_id": 12}, "recipient": {"chat_id": 77},
                           "body": {"text": "Хочу тёплый балкон", "attachments": []}}}
    normalized = normalize_max(payload)
    assert normalized["kind"] == "message_created"
    assert normalized["text"] == "Хочу тёплый балкон"
    assert normalized["chat_id"] == "77"
    assert claim_webhook_event(db, normalized["event_id"]) is True
    db.commit()
    assert claim_webhook_event(db, normalized["event_id"]) is False


def test_slot_reservation_is_single_winner(db):
    start = datetime.now(timezone.utc) + timedelta(days=1)
    slot = MeasurementSlot(start_at=start, end_at=start + timedelta(hours=1), status="available")
    db.add(slot)
    db.flush()
    assert reserve_slot(db, slot.id, "lead-a") is True
    db.commit()
    assert reserve_slot(db, slot.id, "lead-b") is False
    db.refresh(slot)
    assert slot.lead_id == "lead-a"


def test_web_happy_path_creates_and_books_one_lead():
    from fastapi.testclient import TestClient
    from main import app, db_session, seed

    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(test_engine)
    test_db = Session(test_engine, expire_on_commit=False)
    seed(test_db)
    app.dependency_overrides[db_session] = lambda: test_db
    try:
        with TestClient(app) as client:
            session_id = client.post("/api/sessions", json={"channel": "web", "utm": {"utm_source": "test"}}).json()["session_id"]
            def answer(text):
                result = client.post(f"/api/sessions/{session_id}/messages", json={"text": text})
                assert result.status_code == 200, result.text
                return result.json()
            assert answer("Хочу застеклить лоджию")["next_action"] == "request_photos"
            answer("Продолжить без фото")
            answer("Круглый год")
            answer("Не знаю")
            answer("Только остекление")
            answer("Ничего")
            estimate = answer("В течение месяца")["estimate"]
            assert estimate["price_min"] > 0 and estimate["price_max"] > estimate["price_min"]
            contact = client.post(f"/api/sessions/{session_id}/contact", json={"name": "Иван", "phone": "+7 999 123-45-67", "address": "Уфа, Ленина, 10", "consent": True})
            assert contact.status_code == 200
            slots = client.get(f"/api/sessions/{session_id}/slots").json()
            booked = client.post(f"/api/sessions/{session_id}/book", json={"slot_id": slots[0]["id"]})
            assert booked.status_code == 200
            assert booked.json()["lead"]["status"] == "measurement_scheduled"
    finally:
        app.dependency_overrides.clear()
        test_db.close()
        Base.metadata.drop_all(test_engine)
