"""Inventory → existing Equipment → QR → request → repair → act/history, real PG."""
import asyncio
import uuid
from io import BytesIO

import pytest
from pypdf import PdfReader
from sqlalchemy import func, select

from app.models.core import Equipment, EquipmentInventoryBatch
from app.models.repair import Repair
from app.models.qr_label import QRLabel
from test_onboarding_postgres import pg, auth
from test_request_workflow_postgres import flow, qr_body, start, repair_body, sync

pytestmark = pytest.mark.asyncio


async def batch(f, quantity=2, **overrides):
    payload = dict(site_id=str(f.sites[0].id), quantity=quantity, idempotency_key=str(uuid.uuid4()))
    payload.update(overrides)
    response = await f.http.post('/api/equipment-inventory/batches', headers=auth(f.owner,f.org), json=payload)
    assert response.status_code == 201, response.text
    rows = (await f.http.get('/api/qr-labels', headers=auth(f.owner,f.org))).json()
    return payload, response.json(), [dict(row, id=row['token'], public_qr_token=row['token'],
        version=1, inventory_number=row['number'], inventory_pending=True, serial_number=None,
        equipment_type_id=None, location_details=None) for row in rows if row['batch_id'] == response.json()['id']]


def details(f, row, **overrides):
    return dict(equipment_type_id=f.kind.id, manufacturer='Karcher', model='BD 50',
        serial_number='INVENTORY-'+row['token'][:8], location='Этаж 2',
        location_details='Прачечная, корпус 2, 1 этаж', expected_version=row['version'], **overrides)


async def complete(f, row, body=None, user=None, headers=None):
    values = dict(body or details(f,row))
    values.pop('expected_version', None)
    values.pop('location', None)
    response = await f.http.post(f"/api/qr-labels/{row['token']}/bind",
        headers=headers or auth(user or f.owner, f.org), json={'new_equipment':values,
        'idempotency_key':row['token']})
    if response.status_code == 200:
        passport = await f.http.get(f"/api/equipment/{response.json()['equipment_id']}/passport",
            headers=auth(f.owner,f.org))
        row['id'] = passport.json()['id']
        return passport
    return response


async def test_batch_retries_pdf_and_empty_equipment_identities(pg):
    payload, created, rows = await batch(pg, quantity=9)
    assert len(rows) == 9
    assert len({row['public_qr_token'] for row in rows}) == 9
    assert all(row['inventory_pending'] and row['serial_number'] is None and row['equipment_type_id'] is None for row in rows)
    assert all(row['location_details'] is None for row in rows)
    responses = await asyncio.gather(*[pg.http.post('/api/equipment-inventory/batches', headers=auth(pg.owner,pg.org), json=payload) for _ in range(4)])
    assert all(r.status_code == 201 and r.json()['id'] == created['id'] for r in responses)
    async with pg.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Equipment)) == 0
        assert await db.scalar(select(func.count()).select_from(EquipmentInventoryBatch)) == 1
    pdf = await pg.http.get(created['pdf_url'], headers=auth(pg.owner,pg.org))
    assert pdf.status_code == 200
    reader = PdfReader(BytesIO(pdf.content))
    assert len(reader.pages) == 2
    urls = [a.get_object()['/A']['/URI'] for page in reader.pages for a in page['/Annots']]
    assert {url.rsplit('/',1)[-1] for url in urls} == {row['public_qr_token'] for row in rows}
    for row in rows:
        label = await pg.http.get(f"/api/qr-labels/{row['token']}", headers=auth(pg.owner,pg.org))
        assert label.status_code == 200 and label.json()['status'] == 'free'
    payload['quantity'] = 8
    assert (await pg.http.post('/api/equipment-inventory/batches', headers=auth(pg.owner,pg.org), json=payload)).status_code == 409


async def test_concurrent_batches_allocate_site_numbers_and_deletion_keeps_watermark(pg):
    await batch(pg, quantity=10)
    results = await asyncio.gather(*[batch(pg, quantity=10) for _ in range(2)])
    numbers = sorted(row['inventory_number'] for _, _, rows in results for row in rows)
    assert numbers == list(range(11, 31))
    # Issued numbers stay reserved even while labels remain free.
    _, _, more = await batch(pg, quantity=2)
    assert sorted(row['inventory_number'] for row in more) == [31, 32]
    _, _, other_site = await batch(pg, quantity=2, site_id=str(pg.sites[1].id))
    assert sorted(row['inventory_number'] for row in other_site) == [1, 2]


async def test_reprint_selected_equipment_preserves_identity_and_a4_layout(pg):
    _, _, rows = await batch(pg, quantity=10)
    for row in rows:
        assert (await complete(pg, row)).status_code == 200
    # Mix inventory and ordinarily registered equipment in one print selection.
    regular = await pg.http.post('/api/equipment', headers=auth(pg.owner, pg.org), json={
        'site_id': str(pg.sites[0].id), 'equipment_type_id': pg.kind.id,
        'serial_number': 'REPRINT-REGULAR', 'manufacturer': 'Nilfisk', 'model': 'SC401'})
    assert regular.status_code == 201, regular.text
    selected = [regular.json(), *rows[:8]]
    before = (await pg.http.get('/api/equipment', headers=auth(pg.owner, pg.org))).json()
    response = await pg.http.post('/api/equipment-inventory/reprint/pdf', headers=auth(pg.owner, pg.org),
        json={'site_id': str(pg.sites[0].id), 'equipment_ids': [row['id'] for row in selected] + [selected[0]['id']]})
    assert response.status_code == 200, response.text
    assert response.headers['content-type'] == 'application/pdf'
    assert response.headers['cache-control'] == 'no-store'
    reader = PdfReader(BytesIO(response.content))
    assert len(reader.pages) == 2
    assert round(float(reader.pages[0].mediabox.width)) == 595
    urls = [a.get_object()['/A']['/URI'] for page in reader.pages for a in page['/Annots']]
    assert [url.rsplit('/', 1)[-1] for url in urls] == [row['public_qr_token'] for row in selected]
    assert 'Nilfisk SC401' in reader.pages[0].extract_text()
    after = (await pg.http.get('/api/equipment', headers=auth(pg.owner, pg.org))).json()
    assert before == after
    async with pg.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(EquipmentInventoryBatch)) == 1


async def test_reprint_rejects_invalid_selection_and_cross_scope(flow):
    f = flow
    payload = {'site_id': str(f.sites[0].id), 'equipment_ids': [str(f.equipment[0].id)]}
    endpoint = '/api/equipment-inventory/reprint/pdf'
    async def post(body, headers=None):
        return await f.http.post(endpoint, headers=headers or auth(f.owner, f.org), json=body)
    assert (await post(payload, auth(f.tech, f.org))).status_code == 403
    assert (await post(payload, f.manager_headers)).status_code == 403
    assert (await f.http.post(endpoint, json=payload)).status_code == 401
    for ids in [[], [str(uuid.uuid4())] * 501, ['invalid']]:
        assert (await post({**payload, 'equipment_ids': ids})).status_code == 422
    for body in [
        {**payload, 'site_id': str(f.sites[3].id)},
        {**payload, 'site_id': str(f.sites[1].id)},
        {**payload, 'equipment_ids': [str(f.equipment[0].id), str(f.equipment[2].id)]},
        {**payload, 'equipment_ids': [str(uuid.uuid4())]},
    ]:
        assert (await post(body)).status_code == 404


@pytest.mark.parametrize('quantity', [0, -1, 501])
async def test_invalid_batch_quantity_has_no_side_effects(pg, quantity):
    response = await pg.http.post('/api/equipment-inventory/batches', headers=auth(pg.owner,pg.org),
        json=dict(site_id=str(pg.sites[0].id), quantity=quantity, idempotency_key=str(uuid.uuid4())))
    assert response.status_code == 422
    async with pg.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(EquipmentInventoryBatch)) == 0


async def test_only_admin_can_batch_and_site_manager_or_assigned_technician_can_complete(flow):
    f=flow
    payload, created, rows = await batch(f)
    row=rows[0]
    assert (await f.http.post('/api/equipment-inventory/batches', headers=auth(f.tech,f.org), json=payload)).status_code == 403
    assert (await f.http.get(created['pdf_url'], headers=auth(f.tech,f.org))).status_code == 403
    manager_done = await complete(f,row,headers=f.manager_headers)
    assert manager_done.status_code == 200, manager_done.text
    assert (await complete(f,row,headers=f.manager_headers)).status_code == 200
    assert (await complete(f,row,{**details(f,row), 'model':'Changed'},headers=f.manager_headers)).status_code == 409
    assert (await f.http.patch(f"/api/equipment/{row['id']}", headers=f.manager_headers,
        json={'model':'Changed','expected_version':1})).status_code == 403
    row=rows[1]
    assert (await complete(f,row,user=f.tech)).status_code == 403
    grant = await f.http.put(f'/api/clients/{f.client.id}/technicians', headers=auth(f.owner,f.org), json={'technician_ids':[str(f.tech.id)]})
    assert grant.status_code == 200
    assert (await complete(f,row,user=f.tech)).status_code == 200
    assert (await complete(f,row,user=f.tech)).status_code == 200  # response loss retry
    body=details(f,row); body['model']='Changed'
    assert (await complete(f,row,body,user=f.tech)).status_code == 409
    assert (await f.http.patch(f"/api/equipment/{row['id']}", headers=auth(f.tech,f.org), json={'model':'Changed','expected_version':2})).status_code == 403
    # Other client / other tenant and unknown batch must remain inaccessible.
    _, _, other = await batch(f, site_id=str(f.sites[2].id))
    assert (await complete(f,other[0],user=f.tech)).status_code == 403
    assert (await complete(f,other[0],headers=f.manager_headers)).status_code in {403,404}
    assert (await f.http.post('/api/equipment-inventory/batches',headers=auth(f.owner,f.org),json={**payload,'idempotency_key':str(uuid.uuid4()),'site_id':str(f.sites[3].id)})).status_code == 404
    assert (await f.http.get('/api/equipment-inventory/batches/'+str(uuid.uuid4())+'/pdf',headers=auth(f.owner,f.org))).status_code == 404


async def test_completion_concurrency_and_duplicate_serial_rollback(pg):
    _,_,rows = await batch(pg)
    row=rows[0]
    body=details(pg,row)
    responses=await asyncio.gather(complete(pg,row,body), complete(pg,row,{**body,'model':'Other'}))
    assert sorted(r.status_code for r in responses) == [200,409]
    saved=next(r.json() for r in responses if r.status_code==200)
    assert saved['location_details']=='Прачечная, корпус 2, 1 этаж'
    duplicate=await complete(pg,rows[1],{**details(pg,rows[1]),'serial_number':saved['serial_number']})
    assert duplicate.status_code==409
    async with pg.sessions() as db:
        remaining=await db.get(QRLabel,uuid.UUID(rows[1]['token']))
        assert remaining.equipment_id is None
    for changes in [{'serial_number':'x' * 256}, {'equipment_type_id':999999}]:
        assert (await complete(pg,rows[1],{**details(pg,rows[1]),**changes})).status_code in {409,422}


async def test_full_admin_edit_and_existing_service_chain(flow):
    f=flow
    _,created,rows=await batch(f)
    row=rows[0]
    # Empty labels must not produce incomplete service records through any intake.
    assert (await f.http.post(f"/api/public/equipment/{row['public_qr_token']}/tickets",json=qr_body())).status_code==404
    request_body={'equipment_id':row['id'],'title':'Не работает'}
    assert (await f.http.post('/api/service-requests',headers=auth(f.owner,f.org),json=request_body)).status_code==422
    assert (await f.http.post('/api/client-portal/requests',headers=f.manager_headers,json=request_body)).status_code==404
    done=await complete(f,row); assert done.status_code==200,done.text
    saved=done.json()
    assert (saved['id'],saved['public_qr_token'])==(row['id'],row['public_qr_token'])
    changes=dict(manufacturer='Новый производитель',model='Новая модель',serial_number='UPDATED-001',
        equipment_type_id=f.kind.id,location='Мойка',location_details='Прачечная, корпус 2, 1 этаж',site_id=str(f.sites[0].id),status='working',expected_version=saved['version'])
    edited=await f.http.patch(f"/api/equipment/{row['id']}",headers=auth(f.owner,f.org),json=changes)
    assert edited.status_code==200,edited.text
    assert edited.json()['public_qr_token']==row['public_qr_token']
    assert edited.json()['location_details']=='Прачечная, корпус 2, 1 этаж'
    assert (await f.http.patch(f"/api/equipment/{row['id']}",headers=auth(f.owner,f.org),json=changes)).status_code==409
    assert (await f.http.patch(f"/api/equipment/{row['id']}",headers=auth(f.owner,f.org),json={'public_qr_token':str(uuid.uuid4())})).status_code==422
    public=await f.http.get(f"/api/public/equipment/{row['public_qr_token']}")
    assert public.json()['model']=='Новая модель' and not public.json()['inventory_pending']
    ticket=await f.http.post(f"/api/public/equipment/{row['public_qr_token']}/tickets",json=qr_body())
    assert ticket.status_code==201,ticket.text
    request_id=ticket.json()['service_request_id']
    async with f.sessions() as db:
        f.equipment=[await db.get(Equipment,uuid.UUID(row['id']))]
    await start(f,request_id)
    result=await sync(f,repair_body(f,request_id))
    assert result['resolved_as']=='applied',result
    act=await f.http.get(f"/api/repairs/{result['server_id']}/act.pdf",headers=auth(f.owner,f.org))
    assert act.status_code==200
    assert 'UPDATED-001' in ''.join(page.extract_text() for page in PdfReader(BytesIO(act.content)).pages)
    passport=(await f.http.get(f"/api/equipment/{row['id']}/passport",headers=auth(f.owner,f.org))).json()
    assert passport['history'][0]['service_request_id']==request_id
    assert passport['history'][0]['has_service_act']
    assert (await f.http.delete(f"/api/equipment/{row['id']}",headers=auth(f.owner,f.org))).status_code==409
    assert (await f.http.get('/api/equipment-inventory/batches',headers=auth(f.owner,f.org))).json()[0]['completed']==1


async def test_optional_serial_create_complete_and_clear(pg):
    for value in [None, '', '   ']:
        response = await pg.http.post('/api/equipment', headers=auth(pg.owner, pg.org), json={
            'site_id': str(pg.sites[0].id), 'equipment_type_id': pg.kind.id,
            'serial_number': value, 'location_details': 'Корпус 2, этаж 1'})
        assert response.status_code == 201, response.text
        assert response.json()['serial_number'] is None
    _, _, rows = await batch(pg)
    for row in rows:
        body = details(pg, row)
        del body['serial_number']
        response = await complete(pg, row, body)
        assert response.status_code == 200, response.text
        assert response.json()['serial_number'] is None
        assert not response.json()['inventory_pending']
        assert (await complete(pg, row, body)).status_code == 200
    row = response.json()
    original_token = row['public_qr_token']
    for value in ['REAL-SN-123', None]:
        response = await pg.http.patch(f"/api/equipment/{row['id']}", headers=auth(pg.owner, pg.org),
            json={'serial_number': value, 'expected_version': row['version']})
        assert response.status_code == 200, response.text
        row = response.json()
        assert row['serial_number'] == value
        assert row['public_qr_token'] == original_token
