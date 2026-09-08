"""P0.3: реальные HTTP/ORM/PostgreSQL, в том числе конкурирующие транзакции."""
import asyncio
import uuid
from datetime import datetime
from io import BytesIO

import pytest
import pytest_asyncio
from PIL import Image
from sqlalchemy import func, select, text

from app.models.core import Equipment, EquipmentStatus, Ticket
from app.models.repair import Repair, SyncOperation
from app.models.service_request import ServiceRequest, ServiceRequestAttachment, ServiceRequestEvent
from test_onboarding_postgres import pg, auth, invite, accept, changed

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def flow(pg, monkeypatch, tmp_path):
    from app.routers import tickets, service_requests
    monkeypatch.setattr(tickets, 'UPLOAD_ROOT', tmp_path)
    monkeypatch.setattr(service_requests, 'UPLOAD_ROOT', tmp_path)
    invitation = await invite(pg)
    accepted = await accept(pg, invitation)
    assert accepted.status_code == 200, accepted.text
    pg.manager_headers = {'Authorization': 'Bearer ' + accepted.json()['access_token']}
    pg.equipment = []
    for i, site in enumerate(pg.sites[:3]):
        result = await pg.http.post('/api/equipment', headers=auth(pg.owner, pg.org), json={
            'equipment_type_id': pg.kind.id, 'site_id': str(site.id), 'serial_number': f'QR-{i}'})
        assert result.status_code == 201, result.text
        async with pg.sessions() as db:
            pg.equipment.append(await db.get(Equipment, uuid.UUID(result.json()['id'])))
    yield pg


def qr_body(key=None):
    return {'idempotency_key': str(key or uuid.uuid4()), 'severity': 'not_working',
            'symptom_tags': ['Не включается'], 'comment': 'Не запускается двигатель'}


async def qr(f, body=None, index=0):
    return await f.http.post(f'/api/public/equipment/{f.equipment[index].public_qr_token}/tickets',
                            json=body or qr_body())


async def new_request(f, index=0):
    response = await f.http.post('/api/service-requests', headers=auth(f.owner, f.org),
        json={'equipment_id': str(f.equipment[index].id), 'title': 'Ремонт двигателя'})
    assert response.status_code == 201, response.text
    return response.json()['id']


async def status(f, request_id, target, details=None, note=None, headers=None):
    return await f.http.patch(f'/api/service-requests/{request_id}/status',
        headers=headers or auth(f.tech, f.org), json={'status': target, 'details': details, 'note': note})


async def start(f, request_id):
    assigned = await f.http.patch(f'/api/service-requests/{request_id}/assign',
        headers=auth(f.owner, f.org), params={'technician_id': str(f.tech.id)})
    assert assigned.status_code == 200, assigned.text
    for target in ['on_the_way', 'in_progress']:
        response = await status(f, request_id, target)
        assert response.status_code == 200, response.text
    async with f.sessions() as db:
        f.equipment = [await db.get(Equipment, eq.id) for eq in f.equipment]


def repair_body(f, request_id, **overrides):
    body = {'local_uuid': str(uuid.uuid4()), 'equipment_id': str(f.equipment[0].id),
        'service_request_id': str(request_id), 'description': 'Диагностика: обрыв. Работы: восстановлен контакт.',
        'device_updated_at': datetime.now().isoformat(), 'base_equipment_version': f.equipment[0].version,
        'parts_used': []}
    return {**body, **overrides}


async def sync(f, body):
    response = await f.http.post('/api/v1/sync/repairs', headers=auth(f.tech, f.org),
        json={'device_id': 'p03-integration', 'repairs': [body]})
    assert response.status_code == 200, response.text
    return response.json()['results'][0]


@pytest.mark.parametrize('manual', [False, True])
async def test_repeat_qr_active_request(flow, manual):
    f = flow
    if manual:
        expected = await new_request(f)
    else:
        first = await qr(f)
        assert first.status_code == 201, first.text
        expected = first.json()['service_request_id']
    repeated = await qr(f)
    assert repeated.status_code == 201, repeated.text
    assert repeated.json()['service_request_id'] == expected
    assert repeated.json()['duplicate'] and repeated.json()['active_request']
    async with f.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(ServiceRequest)) == 1


async def test_qr_response_loss_and_foreign_equipment_key(flow):
    body = qr_body()
    first = await qr(flow, body)
    retry = await qr(flow, body)
    assert first.status_code == retry.status_code == 201
    assert first.json()['service_request_id'] == retry.json()['service_request_id']
    denied = await qr(flow, body, index=1)
    assert denied.status_code == 409, denied.text
    assert first.json()['service_request_id'] not in denied.text


async def test_repeat_key_remains_bound_after_completion(flow):
    first = await qr(flow)
    assert first.status_code == 201, first.text
    request_id = first.json()['service_request_id']
    retry_body = qr_body()
    repeated = await qr(flow, retry_body)
    assert repeated.status_code == 201, repeated.text
    await start(flow, request_id)
    result = await sync(flow, repair_body(flow, request_id))
    assert result['resolved_as'] in {'applied', 'applied_with_conflict'}, result
    late = await qr(flow, retry_body)
    assert late.status_code == 201 and late.json()['service_request_id'] == request_id, late.text
    assert late.json()['duplicate'] and not late.json()['active_request']
    fresh = await qr(flow)
    assert fresh.status_code == 201 and fresh.json()['service_request_id'] != request_id


@pytest.mark.parametrize('source', ['qr', 'staff', 'client'])
async def test_concurrent_numbering(flow, monkeypatch, source):
    from app.routers import tickets, service_requests, client_portal
    router = {'qr': tickets, 'staff': service_requests, 'client': client_portal}[source]
    original = router.next_number
    async def delayed(db, organization_id):
        number = await original(db, organization_id)
        # Расширяем окно между выделением номера и INSERT; ORM/БД не мокируются.
        await asyncio.sleep(0.1)
        return number
    monkeypatch.setattr(router, 'next_number', delayed)
    async def create(i):
        if source == 'qr': return await qr(flow, index=i)
        return await flow.http.post('/api/service-requests' if source == 'staff' else '/api/client-portal/requests',
            headers=auth(flow.owner, flow.org) if source == 'staff' else flow.manager_headers,
            json={'equipment_id': str(flow.equipment[i if source == 'staff' else 0].id), 'title': f'Поломка {i}'})
    responses = await asyncio.gather(create(0), create(1))
    assert all(r.status_code == 201 for r in responses), [r.text for r in responses]
    assert sorted(r.json()['number'] for r in responses) == [1, 2]


async def test_concurrent_same_qr_creates_one_request(flow):
    responses = await asyncio.gather(qr(flow), qr(flow))
    assert all(r.status_code == 201 for r in responses), [r.text for r in responses]
    assert len({r.json()['service_request_id'] for r in responses}) == 1


async def test_guest_photo_partial_retry_and_legacy(flow):
    result = await qr(flow)
    request_id = result.json()['service_request_id']
    url = f'/api/public/equipment/{flow.equipment[0].public_qr_token}/requests/{request_id}/attachments'
    content = BytesIO(); Image.new('RGB', (3, 3)).save(content, format='PNG')
    async def photo(key=None, data=None):
        return await flow.http.post(url, data={} if key is None else {'client_id': key},
            files={'file': ('photo.png', content.getvalue() if data is None else data, 'image/png')})
    first = await photo('first')
    assert first.status_code == 201
    invalid = await photo('second', b'not-an-image')
    assert invalid.status_code == 422
    second = await photo('second')
    legacy = await photo()
    assert second.status_code == legacy.status_code == 201
    retry = await photo('first')
    assert retry.status_code == 201 and retry.json()['id'] == first.json()['id']
    limit = await photo('fourth')
    assert limit.status_code == 422
    async with flow.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(ServiceRequestAttachment)) == 3
    detail = await flow.http.get(f'/api/service-requests/{request_id}', headers=auth(flow.owner, flow.org))
    assert len(detail.json()['request_attachments']) == 3
    for item in detail.json()['request_attachments']:
        downloaded = await flow.http.get(item['download_url'], headers=flow.manager_headers)
        assert downloaded.status_code == 200


APPROVAL = {'diagnostic': 'Обрыв обмотки', 'work': 'Замена двигателя', 'comment': 'Подтвердите работы',
            'parts': [{'name': 'Двигатель', 'quantity': 1}], 'photo_count': 0}


@pytest.mark.parametrize('target,approved', [('internal', True), ('internal', False), ('client', True), ('client', False)])
async def test_approval_contract_and_authority(flow, target, approved):
    request_id = await new_request(flow)
    await start(flow, request_id)
    waiting = await status(flow, request_id, 'waiting_approval',
        details={'approval_target': target, 'approval': APPROVAL}, note='Требуется согласование')
    assert waiting.status_code == 200, waiting.text
    detail = await flow.http.get(f'/api/service-requests/{request_id}', headers=auth(flow.owner, flow.org))
    event = next(e for e in detail.json()['history'] if e['type'] == 'request.waiting_approval')
    assert event['details']['approval'] == APPROVAL
    bypass = await status(flow, request_id, 'in_progress')
    assert bypass.status_code == 403
    result = await sync(flow, repair_body(flow, request_id))
    assert result['resolved_as'] == 'failed'
    route = '/api/client-portal/requests' if target == 'client' else '/api/service-requests'
    headers = flow.manager_headers if target == 'client' else auth(flow.owner, flow.org)
    other_route = '/api/service-requests' if target == 'client' else '/api/client-portal/requests'
    other_headers = auth(flow.owner, flow.org) if target == 'client' else flow.manager_headers
    denied = await flow.http.patch(f'{other_route}/{request_id}/approval', headers=other_headers, json={'action': 'approved'})
    assert denied.status_code == 403, denied.text
    decision = await flow.http.patch(f'{route}/{request_id}/approval', headers=headers,
        json={'action': 'approved' if approved else 'rejected', 'comment': 'Решение клиента'})
    assert decision.status_code == 200, decision.text
    assert decision.json()['status'] == ('in_progress' if approved else 'cancelled')
    again = await flow.http.patch(f'{route}/{request_id}/approval', headers=headers, json={'action': 'approved'})
    assert again.status_code == 409
    if not approved: assert decision.json()['completed_at']


async def test_waiting_parts_completion_and_cancellation_guards(flow):
    request_id = await new_request(flow)
    await start(flow, request_id)
    assert (await status(flow, request_id, 'waiting_parts')).status_code == 200
    assert (await sync(flow, repair_body(flow, request_id)))['resolved_as'] == 'failed'
    assert (await status(flow, request_id, 'in_progress')).status_code == 200
    assert (await status(flow, request_id, 'completed')).status_code == 409
    async with flow.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Repair)) == 0
    other = await new_request(flow, 1)
    assert (await status(flow, other, 'cancelled', headers=auth(flow.owner, flow.org))).status_code == 422
    cancelled = await status(flow, other, 'cancelled', note='Дубликат', headers=auth(flow.owner, flow.org))
    assert cancelled.status_code == 200 and cancelled.json()['completed_at']


async def test_completion_timestamp_and_retry(flow):
    request_id = await new_request(flow)
    await start(flow, request_id)
    body = repair_body(flow, request_id)
    first = await sync(flow, body)
    assert first['resolved_as'] == 'applied', first
    detail = await flow.http.get(f'/api/service-requests/{request_id}', headers=flow.manager_headers)
    completed = detail.json()['completed_at']
    assert completed and detail.json()['status'] == 'completed'
    retry = await sync(flow, body)
    assert retry['resolved_as'] == 'already_synced' and retry['server_id'] == first['server_id']
    duplicate = await sync(flow, {**body, 'local_uuid': str(uuid.uuid4())})
    assert duplicate['resolved_as'] == 'failed'
    later = await flow.http.get(f'/api/service-requests/{request_id}', headers=flow.manager_headers)
    assert later.json()['completed_at'] == completed
    async with flow.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Repair)) == 1
        assert await db.scalar(select(func.count()).select_from(SyncOperation)) == 1
        assert await db.scalar(select(func.count()).select_from(ServiceRequestEvent).where(
            ServiceRequestEvent.event_type == 'repair.completed')) == 1


@pytest.mark.parametrize('same_key', [True, False])
async def test_two_syncs_waiting_for_equipment_lock(flow, same_key):
    request_id = await new_request(flow)
    await start(flow, request_id)
    body = repair_body(flow, request_id)
    second = body if same_key else {**body, 'local_uuid': str(uuid.uuid4())}
    tasks = []
    async with flow.sessions() as locker:
        await locker.scalar(select(Equipment).where(Equipment.id == flow.equipment[0].id).with_for_update())
        try:
            tasks = [asyncio.create_task(sync(flow, b)) for b in (body, second)]
            # Обе HTTP-транзакции должны реально дойти до ожидания row lock.
            for _ in range(100):
                async with flow.sessions() as observer:
                    waiting = await observer.scalar(text("SELECT count(*) FROM pg_stat_activity WHERE wait_event_type = 'Lock' AND query LIKE '%equipment%FOR UPDATE%'"))
                if waiting >= 2: break
                await asyncio.sleep(0.02)
            assert waiting >= 2, 'Не удалось воспроизвести пересечение транзакций'
        finally:
            await locker.rollback()
            results = await asyncio.wait_for(asyncio.gather(*tasks), 15)
    assert sorted(r['resolved_as'] for r in results) == (['already_synced', 'applied'] if same_key else ['applied', 'failed']), results
    async with flow.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Repair)) == 1


@pytest.mark.parametrize('conflict', [False, True])
async def test_other_active_request_or_version_conflict_preserves_equipment(flow, conflict):
    request_id = await new_request(flow)
    await start(flow, request_id)
    if not conflict: await new_request(flow)
    await changed(flow, Equipment, flow.equipment[0].id, status=EquipmentStatus.needs_repair,
                  version=flow.equipment[0].version + (1 if conflict else 0))
    result = await sync(flow, repair_body(flow, request_id))
    assert result['resolved_as'] == ('applied_with_conflict' if conflict else 'applied'), result
    async with flow.sessions() as db:
        eq = await db.get(Equipment, flow.equipment[0].id)
        assert eq.status == EquipmentStatus.needs_repair


async def test_client_approval_executes_postgres_lock(flow):
    request_id = await new_request(flow)
    await start(flow, request_id)
    waiting = await status(flow, request_id, 'waiting_approval', details={'approval_target': 'client'})
    assert waiting.status_code == 200, waiting.text
    response = await flow.http.patch(f'/api/client-portal/requests/{request_id}/approval',
        headers=flow.manager_headers, json={'action': 'approved'})
    assert response.status_code == 200, response.text
    assert response.json()['status'] == 'in_progress'


async def test_cached_pulse_approval_and_invalid_snapshot(flow):
    request_id = await new_request(flow)
    await start(flow, request_id)
    invalid = await status(flow, request_id, 'waiting_approval', details={
        'approval_target': 'internal', 'approval': {**APPROVAL, 'parts': [{'name': 'Двигатель', 'quantity': -1}]}})
    assert invalid.status_code == 422
    waiting = await status(flow, request_id, 'waiting_approval', details={'approval': APPROVAL})
    assert waiting.status_code == 200, waiting.text
    assert waiting.json()['approval_target'] == 'internal'


async def test_legacy_ticket_key_preserved_and_scope_checked(flow):
    # Старые данные до guest_request_receipts остаются поддержанными.
    async with flow.sessions() as db:
        ticket = Ticket(organization_id=flow.org.id, equipment_id=flow.equipment[0].id,
            idempotency_key=uuid.uuid4(), severity='not_working')
        db.add(ticket); await db.flush()
        request = ServiceRequest(organization_id=flow.org.id, equipment_id=flow.equipment[0].id,
            ticket_id=ticket.id, number=1, title='Историческая QR заявка', status='completed')
        db.add(request); await db.commit()
    repeated = await qr(flow, qr_body(ticket.idempotency_key))
    assert repeated.status_code == 201 and repeated.json()['service_request_id'] == str(request.id)
    denied = await qr(flow, qr_body(ticket.idempotency_key), index=1)
    assert denied.status_code == 409


async def test_concurrent_guest_photo_retry_and_foreign_qr(flow):
    first = await qr(flow)
    request_id = first.json()['service_request_id']
    content = BytesIO(); Image.new('RGB', (3, 3)).save(content, format='PNG')
    async def photo(index):
        return await flow.http.post(f'/api/public/equipment/{flow.equipment[index].public_qr_token}/requests/{request_id}/attachments',
            data={'client_id': 'same-photo'}, files={'file': ('photo.png', content.getvalue(), 'image/png')})
    responses = await asyncio.gather(photo(0), photo(0))
    assert all(r.status_code == 201 for r in responses), [r.text for r in responses]
    assert responses[0].json()['id'] == responses[1].json()['id']
    assert (await photo(1)).status_code == 404


async def test_client_approval_other_site_denied_and_concurrent_decision(flow):
    foreign = await new_request(flow, 1)
    await start(flow, foreign)
    assert (await status(flow, foreign, 'waiting_approval', details={'approval_target': 'client'})).status_code == 200
    denied = await flow.http.patch(f'/api/client-portal/requests/{foreign}/approval',
        headers=flow.manager_headers, json={'action': 'approved'})
    assert denied.status_code == 404, denied.text
    request_id = await new_request(flow)
    await start(flow, request_id)
    assert (await status(flow, request_id, 'waiting_approval', details={'approval_target': 'client'})).status_code == 200
    responses = await asyncio.gather(*[flow.http.patch(f'/api/client-portal/requests/{request_id}/approval',
        headers=flow.manager_headers, json={'action': action, 'comment': 'Решение'}) for action in ('approved', 'rejected')])
    assert sorted(r.status_code for r in responses) == [200, 409], [r.text for r in responses]
    async with flow.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(ServiceRequestEvent).where(
            ServiceRequestEvent.service_request_id == uuid.UUID(request_id),
            ServiceRequestEvent.event_type.in_(['approval.approved', 'approval.rejected']))) == 1
