"""Existing parity APIs expose the fields required by the UI without new workflows."""
from datetime import datetime, timedelta, timezone
import uuid

import pytest

from app.models.customer import ClientInvite
from app.models.core import Equipment
from app.models.service_request import ServiceRequest
from test_onboarding_postgres import pg, auth, invite
from test_request_workflow_postgres import flow

pytestmark = pytest.mark.asyncio


async def test_client_list_exposes_filter_and_equipment_search_fields(flow):
    async with flow.sessions() as db:
        request = ServiceRequest(
            organization_id=flow.org.id, number=901, equipment_id=flow.equipment[0].id,
            title="Требует решения", status="waiting_approval", approval_target="client",
        )
        equipment = await db.get(Equipment, flow.equipment[0].id)
        equipment.inventory_number = 4401
        db.add(request)
        await db.commit()
    requests = await flow.http.get("/api/client-portal/requests", headers=flow.manager_headers)
    assert requests.status_code == 200, requests.text
    item = next(row for row in requests.json() if row["id"] == str(request.id))
    assert item["status"] == "waiting_approval" and item["approval_target"] == "client"
    equipment = await flow.http.get("/api/client-portal/equipment", headers=flow.manager_headers)
    assert equipment.status_code == 200, equipment.text
    assert next(row for row in equipment.json() if row["id"] == str(flow.equipment[0].id))["inventory_number"] == 4401


async def test_invite_metadata_derives_expired_without_disclosing_capability(flow):
    pending = await invite(flow, invited_email="parity@example.com")
    async with flow.sessions() as db:
        row = await db.get(ClientInvite, uuid.UUID(pending["id"]))
        row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        await db.commit()
    listed = await flow.http.get(
        f"/api/client-portal/clients/{flow.client.id}/invites",
        headers=auth(flow.owner, flow.org),
    )
    assert listed.status_code == 200, listed.text
    item = next(row for row in listed.json() if row["id"] == pending["id"])
    assert item["status"] == "expired"
    assert item["created_at"] and item["join_url"] is None and item["qr_url"] is None
