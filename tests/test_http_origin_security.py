from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import configure_http_security


def _application(monkeypatch) -> FastAPI:
    monkeypatch.setattr(
        "app.main.settings",
        Settings(
            database_url="postgresql+asyncpg://user:pass@localhost:5432/test",
            secret_key="test-secret",
            allowed_origins="https://legacy.example,https://fixitpulse.ru",
            allowed_hosts="legacy.example,fixitpulse.ru,localhost,127.0.0.1",
        ),
    )
    application = FastAPI()
    configure_http_security(application)

    @application.get("/health")
    async def health():
        return {"status": "ok"}

    return application


def test_settings_parse_comma_separated_allowlists():
    settings = Settings(
        database_url="postgresql+asyncpg://user:pass@localhost:5432/test",
        secret_key="test-secret",
        allowed_origins="https://legacy.example/, https://fixitpulse.ru",
        allowed_hosts="legacy.example, fixitpulse.ru,127.0.0.1",
    )
    assert settings.cors_origins == ["https://legacy.example", "https://fixitpulse.ru"]
    assert settings.trusted_hosts == ["legacy.example", "fixitpulse.ru", "127.0.0.1"]


def test_allowed_host_and_origin_are_accepted(monkeypatch):
    with TestClient(_application(monkeypatch)) as client:
        response = client.get("/health", headers={"Host": "fixitpulse.ru", "Origin": "https://fixitpulse.ru"})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://fixitpulse.ru"


def test_foreign_origin_is_not_granted_cors(monkeypatch):
    with TestClient(_application(monkeypatch)) as client:
        response = client.get("/health", headers={"Host": "fixitpulse.ru", "Origin": "https://foreign.example"})
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_unknown_host_is_rejected(monkeypatch):
    with TestClient(_application(monkeypatch)) as client:
        response = client.get("/health", headers={"Host": "foreign.example"})
    assert response.status_code == 400


def test_localhost_health_check_is_accepted(monkeypatch):
    with TestClient(_application(monkeypatch)) as client:
        response = client.get("/health", headers={"Host": "127.0.0.1:8000"})
    assert response.status_code == 200
