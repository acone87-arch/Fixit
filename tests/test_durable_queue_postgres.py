"""P0.5: concurrent delayed photo delivery to a completed repair, real HTTP/PG."""
import asyncio
import uuid

import pytest
from sqlalchemy import func, select
from app.models.repair import RepairAttachment
from test_onboarding_postgres import pg, auth
from test_request_workflow_postgres import flow, new_request, start, sync, repair_body
from test_technician_result_postgres import result_flow, photo_bytes

pytestmark = pytest.mark.asyncio


async def test_concurrent_photo_receipt_returns_one_attachment(result_flow):
    f = result_flow
    request_id = await new_request(f); await start(f, request_id)
    result = await sync(f, repair_body(f, request_id))
    repair_id = result['server_id']
    async def upload():
        return await f.http.post(f'/api/repairs/{repair_id}/attachments', headers=auth(f.tech, f.org),
            data={'kind': 'after', 'client_id': 'same-offline-photo'},
            files={'file': ('result.png', photo_bytes(), 'image/png')})
    responses = await asyncio.gather(*(upload() for _ in range(6)))
    assert [r.status_code for r in responses] == [201] * 6, [r.text for r in responses]
    assert len({r.json()['id'] for r in responses}) == 1
    async with f.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(RepairAttachment).where(
            RepairAttachment.repair_id == uuid.UUID(repair_id))) == 1
    assert (await upload()).json()['id'] == responses[0].json()['id']
