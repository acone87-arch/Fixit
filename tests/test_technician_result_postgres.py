"""P0.4: сохранённый результат, акт, история и границы чтения через HTTP/PG."""
import uuid
from datetime import datetime, timezone
from io import BytesIO

import pytest
import pytest_asyncio
from PIL import Image
from sqlalchemy import delete, func, select

from app.models.core import Equipment, Task, User, UserRole
from app.models.customer import TechnicianClientAccess
from app.models.organization import OrganizationMembership
from app.models.repair import Repair, RepairPart, SyncOperation
from app.models.service_request import ServiceRequest
from app.models.warehouse import Part, Warehouse, WarehouseStock, WarehouseType
from test_onboarding_postgres import pg, auth
from test_request_workflow_postgres import flow, new_request, start, repair_body, sync, qr

pytestmark = pytest.mark.asyncio
DIAGNOSTIC = 'Обнаружен обрыв цепи питания двигателя. ' * 5
WORK = 'Восстановлен контакт, двигатель проверен под нагрузкой.'
DESCRIPTION = f'Диагностика: {DIAGNOSTIC}\nРаботы: {WORK}'


def photo_bytes():
    stream = BytesIO()
    Image.new('RGB', (8, 8), 'green').save(stream, format='PNG')
    return stream.getvalue()


@pytest_asyncio.fixture
async def result_flow(flow, monkeypatch, tmp_path):
    from app.routers import repairs
    monkeypatch.setattr(repairs, 'UPLOAD_ROOT', tmp_path)
    f = flow
    grant = await f.http.put(f'/api/clients/{f.client.id}/technicians', headers=auth(f.owner, f.org),
        json={'technician_ids': [str(f.tech.id)]})
    assert grant.status_code == 200, grant.text
    async with f.sessions() as db:
        f.part = Part(organization_id=f.org.id, article='PILOT-VALVE', name='Клапан')
        f.warehouse = Warehouse(organization_id=f.org.id, name='Мобильный', type=WarehouseType.mobile, owner_user_id=f.tech.id)
        db.add_all([f.part, f.warehouse]); await db.flush()
        db.add(WarehouseStock(warehouse_id=f.warehouse.id, part_id=f.part.id, quantity=5))
        await db.commit()
    yield f


async def upload_result(f, repair_id):
    response = await f.http.post(f'/api/repairs/{repair_id}/attachments', headers=auth(f.tech, f.org),
        data={'kind': 'after', 'client_id': 'p04-result-photo'}, files={'file': ('result.png', photo_bytes(), 'image/png')})
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.parametrize('description', ['', ' \n\t'])
async def test_empty_result_does_not_complete_or_consume_parts(result_flow, description):
    f = result_flow
    request_id = await new_request(f); await start(f, request_id)
    result = await sync(f, repair_body(f, request_id, description=description,
        parts_used=[{'part_id': str(f.part.id), 'quantity': 1}]))
    assert result['resolved_as'] == 'failed', result
    async with f.sessions() as db:
        assert (await db.get(ServiceRequest, uuid.UUID(request_id))).status == 'in_progress'
        assert await db.scalar(select(func.count()).select_from(Repair)) == 0
        assert await db.scalar(select(func.count()).select_from(SyncOperation)) == 0
        assert (await db.get(WarehouseStock, (f.warehouse.id, f.part.id))).quantity == 5


@pytest.mark.parametrize('conflict', [False, True])
async def test_complete_result_retry_media_act_history_and_scope(result_flow, conflict):
    from pypdf import PdfReader
    f = result_flow
    request_id = await new_request(f); await start(f, request_id)
    body = repair_body(f, request_id, description=DESCRIPTION, fault_type='Обрыв цепи',
        base_equipment_version=f.equipment[0].version - int(conflict),
        parts_used=[{'part_id': str(f.part.id), 'quantity': 2}])
    result = await sync(f, body)
    assert result['resolved_as'] == ('applied_with_conflict' if conflict else 'applied'), result
    repair_id = result['server_id']
    assert (await sync(f, body))['resolved_as'] == 'already_synced'
    photo = await upload_result(f, repair_id)
    assert (await upload_result(f, repair_id))['id'] == photo['id']
    for headers in [auth(f.owner, f.org), auth(f.tech, f.org), f.manager_headers]:
        detail = await f.http.get(f'/api/service-requests/{request_id}', headers=headers)
        assert detail.status_code == 200, detail.text
        data = detail.json()
        assert data['outcome'] == DESCRIPTION and data['repair_id'] == repair_id
        assert data['repair_sync_status'] == ('conflict' if conflict else 'synced')
        assert data['parts_used'][0]['quantity'] == 2
        assert len(data['attachments']) == 1
        media = await f.http.get(photo['download_url'], headers=headers)
        assert media.status_code == 200
        Image.open(BytesIO(media.content)).verify()
        act = await f.http.get(f'/api/repairs/{repair_id}/act.pdf', headers=headers)
        assert act.status_code == 200, act.text
        text = '\n'.join(page.extract_text() for page in PdfReader(BytesIO(act.content)).pages)
        assert WORK in text and 'PILOT-VALVE' in text and 'Клапан' in text
        assert 'QR-0' in text and 'Техник' in text
        passport = await f.http.get(f'/api/equipment/{f.equipment[0].id}/passport', headers=headers)
        assert passport.status_code == 200, passport.text
        history = passport.json()['history']
        assert len(history) == 1 and history[0]['service_request_id'] == request_id
        assert history[0]['work_summary'] == DESCRIPTION and history[0]['has_service_act']
        assert history[0]['photos'][0]['id'] == photo['id']
    # Другая Site/Client/Organization не получает ни результат, ни PDF, ни фото.
    async with f.sessions() as db:
        manager_id = (await db.scalar(select(User).where(User.email == 'manager@example.com'))).id
        from app.models.customer import ClientUserAccess
        access = await db.scalar(select(ClientUserAccess).where(ClientUserAccess.user_id == manager_id))
        access.site_id = f.sites[1].id
        await db.commit()
    for url in [f'/api/client-portal/requests/{request_id}', f'/api/equipment/{f.equipment[0].id}/passport',
                f'/api/repairs/{repair_id}/act.pdf', photo['download_url']]:
        denied = await f.http.get(url, headers=f.manager_headers)
        assert denied.status_code in {403, 404}, denied.text
    async with f.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Repair)) == 1
        assert await db.scalar(select(func.count()).select_from(RepairPart)) == 1
        assert (await db.get(WarehouseStock, (f.warehouse.id, f.part.id))).quantity == 3
        repair = await db.get(Repair, uuid.UUID(repair_id))
        assert repair.closed_at is not None
        assert (await db.get(Equipment, f.equipment[0].id)).status.value == ('needs_repair' if conflict else 'working')
        await db.execute(delete(TechnicianClientAccess).where(TechnicianClientAccess.technician_id == f.tech.id))
        await db.commit()
    # Автор читает свой результат после отзыва fleet grant, пока membership активен.
    assert (await f.http.get(f'/api/repairs/{repair_id}/act.pdf', headers=auth(f.tech, f.org))).status_code == 200
    assert (await f.http.get(photo['download_url'], headers=auth(f.tech, f.org))).status_code == 200


@pytest.mark.parametrize('link', ['task', 'ticket'])
async def test_legacy_results_do_not_disappear_or_get_arbitrary_canonical_owner(result_flow, link):
    f = result_flow
    response = await qr(f)
    request_id = uuid.UUID(response.json()['service_request_id'])
    async with f.sessions() as db:
        request = await db.get(ServiceRequest, request_id)
        if link == 'task':
            task = Task(organization_id=f.org.id, equipment_id=f.equipment[0].id, title='Старый наряд')
            db.add(task); await db.flush(); request.task_id = task.id
        kwargs = {'task_id': request.task_id} if link == 'task' else {'ticket_id': request.ticket_id}
        repairs = [Repair(organization_id=f.org.id, local_uuid=uuid.uuid4(), equipment_id=f.equipment[0].id,
            technician_id=f.tech.id, description=f'Историческая работа {i}', device_updated_at=datetime.now(timezone.utc), **kwargs) for i in range(2)]
        db.add_all(repairs); await db.commit()
    passport = await f.http.get(f'/api/equipment/{f.equipment[0].id}/passport', headers=f.manager_headers)
    assert passport.status_code == 200, passport.text
    history = passport.json()['history']
    for repair in repairs:
        entry = next((item for item in history if item['id'] == f'repair:{repair.id}'), None)
        assert entry is not None and entry['work_summary'] == repair.description
        assert entry['legacy'] and entry['service_request_id'] is None
    assert sum(item['service_request_id'] == str(request_id) for item in history) == 1
