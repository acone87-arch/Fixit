from urllib.parse import unquote

import pytest

from app.config import settings
from app.core.security import decode_access_token
from app.models.core import PasswordResetToken, User
from test_onboarding_postgres import PASSWORD, auth, pg

pytestmark = pytest.mark.asyncio


async def test_change_password_revokes_existing_sessions_and_accepts_new_password(pg):
    headers = auth(pg.owner, pg.org)
    changed = await pg.http.post("/api/auth/password/change", headers=headers, json={
        "current_password": PASSWORD, "new_password": "changed-password-2026", "confirmation": "changed-password-2026",
    })
    assert changed.status_code == 204, changed.text
    assert (await pg.http.get("/api/users/me", headers=headers)).status_code == 401
    assert (await pg.http.post("/api/auth/login", json={"email": pg.owner.email, "password": PASSWORD})).status_code == 401
    login = await pg.http.post("/api/auth/login", json={"email": pg.owner.email, "password": "changed-password-2026"})
    assert login.status_code == 200, login.text
    assert decode_access_token(login.json()["access_token"])["av"] == 1


async def test_password_change_rejects_wrong_current_password(pg):
    response = await pg.http.post("/api/auth/password/change", headers=auth(pg.owner, pg.org), json={
        "current_password": "wrong-password", "new_password": "changed-password-2026", "confirmation": "changed-password-2026",
    })
    assert response.status_code == 400


async def test_reset_is_non_disclosing_single_use_and_hashed(pg, monkeypatch):
    monkeypatch.setattr(settings, "password_reset_debug", True)
    monkeypatch.setattr(settings, "smtp_host", None)
    known = await pg.http.post("/api/auth/password/reset/request", json={"email": pg.owner.email})
    unknown = await pg.http.post("/api/auth/password/reset/request", json={"email": "nobody@example.com"})
    assert known.status_code == unknown.status_code == 200
    assert known.json()["message"] == unknown.json()["message"]
    assert unknown.json()["preview_url"] is None
    raw = unquote(known.json()["preview_url"].split("/#reset-password/", 1)[1])
    async with pg.sessions() as db:
        item = (await db.scalars(__import__("sqlalchemy").select(PasswordResetToken))).one()
        assert item.token_hash != raw and len(item.token_hash) == 64
    assert (await pg.http.get("/api/auth/password/reset/validate", params={"token": raw})).json() == {"valid": True}
    complete = await pg.http.post("/api/auth/password/reset/complete", json={
        "token": raw, "new_password": "reset-password-2026", "confirmation": "reset-password-2026",
    })
    assert complete.status_code == 204, complete.text
    assert (await pg.http.post("/api/auth/password/reset/complete", json={
        "token": raw, "new_password": "another-password-2026", "confirmation": "another-password-2026",
    })).status_code == 400
    assert (await pg.http.get("/api/auth/password/reset/validate", params={"token": raw})).json() == {"valid": False}
    assert (await pg.http.post("/api/auth/login", json={"email": pg.owner.email, "password": "reset-password-2026"})).status_code == 200


async def test_password_reset_model_has_no_raw_token_column():
    assert "token" not in PasswordResetToken.__table__.columns
    assert {"token_hash", "expires_at", "used_at", "user_id"} <= set(PasswordResetToken.__table__.columns.keys())
    assert "auth_version" in User.__table__.columns
