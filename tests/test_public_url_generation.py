import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.config import settings
from app.routers import equipment, invites


def test_new_invite_link_uses_configured_canonical_public_url(monkeypatch):
    monkeypatch.setattr(settings, "public_app_url", "https://fixitpulse.ru")
    assert invites._join_url("invite-token") == "https://fixitpulse.ru/join/invite-token"


def test_new_equipment_qr_uses_configured_public_url_without_changing_token(monkeypatch):
    token = uuid.uuid4()
    item = SimpleNamespace(
        id=uuid.uuid4(), public_qr_token=token, site_id=uuid.uuid4(),
        inventory_batch_id=None, inventory_number=17, name="Насос",
    )
    generated: list[tuple] = []

    async def equipment_for_user(*_args):
        return item

    def build(label, base_url):
        generated.append((label, base_url))
        return b"print-ready-pdf"

    monkeypatch.setattr(settings, "public_app_url", "https://fixitpulse.ru")
    monkeypatch.setattr(equipment, "_equipment_for_user", equipment_for_user)
    monkeypatch.setattr(equipment, "build_single_label_pdf", build)
    db = AsyncMock()
    db.get.return_value = SimpleNamespace(name="Главный склад")

    response = asyncio.run(equipment.equipment_qr(uuid.uuid4(), db=db, user=None))

    assert response.status_code == 200
    assert response.media_type == "application/pdf"
    assert len(generated) == 1
    label, base_url = generated[0]
    assert base_url == "https://fixitpulse.ru"
    assert label.token == str(token)
    assert label.site_name == "Главный склад"
    assert item.public_qr_token == token


def test_changing_public_url_changes_only_new_link_prefix(monkeypatch):
    token = uuid.uuid4()
    item = SimpleNamespace(public_qr_token=token, id=uuid.uuid4(), name="Existing equipment")

    monkeypatch.setattr(settings, "public_app_url", "https://185.239.51.251")
    legacy_link = f"{settings.public_app_url}/e/{item.public_qr_token}"
    monkeypatch.setattr(settings, "public_app_url", "https://fixitpulse.ru")
    canonical_link = f"{settings.public_app_url}/e/{item.public_qr_token}"

    assert legacy_link == f"https://185.239.51.251/e/{token}"
    assert canonical_link == f"https://fixitpulse.ru/e/{token}"
    assert item.public_qr_token == token
    assert item.name == "Existing equipment"
