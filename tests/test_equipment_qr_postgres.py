from io import BytesIO
import uuid

import pytest
from pypdf import PdfReader

from app.config import settings
from app.models.core import Equipment
from test_onboarding_postgres import auth, pg

pytestmark = pytest.mark.asyncio


async def test_equipment_download_is_print_label_with_same_safe_url(pg):
    created = await pg.http.post("/api/equipment", headers=auth(pg.owner, pg.org), json={
        "equipment_type_id": pg.kind.id, "site_id": str(pg.sites[0].id), "serial_number": "LONG-LABEL-1",
    })
    assert created.status_code == 201, created.text
    equipment_id = uuid.UUID(created.json()["id"])
    async with pg.sessions() as db:
        equipment = await db.get(Equipment, equipment_id)
        equipment.name = ("Промышленная посудомоечная машина с очень длинным названием " * 4)[:255]
        expected = f"{settings.public_app_url.rstrip('/')}/e/{equipment.public_qr_token}"
        await db.commit()
    response = await pg.http.get(f"/api/equipment/{equipment_id}/qr", headers=auth(pg.owner, pg.org))
    assert response.status_code == 200 and response.headers["content-type"].startswith("application/pdf")
    assert "attachment" in response.headers["content-disposition"]
    reader = PdfReader(BytesIO(response.content))
    links = [item.get_object()["/A"]["/URI"] for item in reader.pages[0]["/Annots"]]
    assert links == [expected]
