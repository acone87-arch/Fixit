"""Inventory → existing Equipment → QR → request → repair → act/history, real PG."""
import asyncio
import uuid
from io import BytesIO

import pytest
from pypdf import PdfReader
from sqlalchemy import func, select

from app.models.core import Equipment, EquipmentInventoryBatch
from app.models.repair import Repair
from test_onboarding_postgres import pg, auth
from test_request_workflow_postgres import flow, qr_body, start, repair_body, sync

pytestmark = pytest.mark.asyncio


async def batch(f, quantity=2, **overrides):
    payload = dict(site_id=str(f.sites[0].id), quantity=quantity, idempotency_key=str(uuid.uuid4()))
    payload.update(overrides)
    response = await f.http.post('/api/equipment-inventory/batches', headers=auth(f.owner,f.org), json=payload)
    assert response.status_code == 201, response.text
    rows = (await f.http.get('/api/equipment', headers=auth(f.owner,f.org))).json()
    return payload, response.json(), [row for row in rows if row['inventory_batch_id'] == response.json()['id']]


def details(f, row, **overrides):
    return dict(equipment_type_id=f.kind.id, manufacturer='Karcher', model='BD 50',
        serial_number='INVENTORY-'+row['id'][:8], location='Этаж 2', expected_version=row['version'], **overrides)


async def complete(f, row, body=None, user=None):
    return await f.http.post(f"/api/equipment-inventory/{row['id']}/complete",
        headers=auth(user or f.owner, f.org), json=body or details(f,row))


async def test_batch_retries_pdf_and_empty_equipment_identities(pg):
    payload, created, rows = await batch(pg, quantity=9)
    assert len(rows) == 9
    assert len({row['public_qr_token'] for row in rows}) == 9
    assert all(row['inventory_pending'] and row['serial_number'] is None and row['equipment_type_id'] is None for row in rows)
    responses = await asyncio.gather(*[pg.http.post('/api/equipment-inventory/batches', headers=auth(pg.owner,pg.org), json=payload) for _ in range(4)])
    assert all(r.status_code == 201 and r.json()['id'] == created['id'] for r in responses)
    async with pg.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Equipment)) == 9
        assert await db.scalar(select(func.count()).select_from(EquipmentInventoryBatch)) == 1
    pdf = await pg.http.get(created['pdf_url'], headers=auth(pg.owner,pg.org))
    assert pdf.status_code == 200
    reader = PdfReader(BytesIO(pdf.content))
    assert len(reader.pages) == 2
    urls = [a.get_object()['/A']['/URI'] for page in reader.pages for a in page['/Annots']]
    assert {url.rsplit('/',1)[-1] for url in urls} == {row['public_qr_token'] for row in rows}
    for row in rows:
        passport = await pg.http.get(f"/api/equipment/{row['id']}/passport", headers=auth(pg.owner,pg.org))
        assert passport.status_code == 200 and passport.json()['inventory_pending']
    payload['quantity'] = 8
    assert (await pg.http.post('/api/equipment-inventory/batches', headers=auth(pg.owner,pg.org), json=payload)).status_code == 409


@pytest.mark.parametrize('quantity', [0, -1, 501])
async def test_invalid_batch_quantity_has_no_side_effects(pg, quantity):
    response = await pg.http.post('/api/equipment-inventory/batches', headers=auth(pg.owner,pg.org),
        json=dict(site_id=str(pg.sites[0].id), quantity=quantity, idempotency_key=str(uuid.uuid4())))
    assert response.status_code == 422
    async with pg.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(EquipmentInventoryBatch)) == 0


async def test_only_admin_can_batch_and_only_assigned_technician_can_complete(flow):
    f=flow
    payload, created, rows = await batch(f)
    row=rows[0]
    assert (await f.http.post('/api/equipment-inventory/batches', headers=auth(f.tech,f.org), json=payload)).status_code == 403
    assert (await f.http.get(created['pdf_url'], headers=auth(f.tech,f.org))).status_code == 403
    assert (await f.http.post(f"/api/equipment-inventory/{row['id']}/complete", headers=f.manager_headers, json=details(f,row))).status_code == 403
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
    assert (await f.http.post('/api/equipment-inventory/batches',headers=auth(f.owner,f.org),json={**payload,'idempotency_key':str(uuid.uuid4()),'site_id':str(f.sites[3].id)})).status_code == 404
    assert (await f.http.get('/api/equipment-inventory/batches/'+str(uuid.uuid4())+'/pdf',headers=auth(f.owner,f.org))).status_code == 404


async def test_completion_concurrency_and_duplicate_serial_rollback(pg):
    _,_,rows = await batch(pg)
    row=rows[0]
    body=details(pg,row)
    responses=await asyncio.gather(complete(pg,row,body), complete(pg,row,{**body,'model':'Other'}))
    assert sorted(r.status_code for r in responses) == [200,409]
    saved=next(r.json() for r in responses if r.status_code==200)
    duplicate=await complete(pg,rows[1],{**details(pg,rows[1]),'serial_number':saved['serial_number']})
    assert duplicate.status_code==409
    async with pg.sessions() as db:
        remaining=await db.get(Equipment,uuid.UUID(rows[1]['id']))
        assert remaining.inventory_pending and remaining.serial_number is None and remaining.version==1
    for changes in [{'serial_number':' '}, {'equipment_type_id':999999}, {'expected_version':99}]:
        assert (await complete(pg,rows[1],{**details(pg,rows[1]),**changes})).status_code in {409,422}


async def test_full_admin_edit_and_existing_service_chain(flow):
    f=flow
    _,created,rows=await batch(f)
    row=rows[0]
    # Empty labels must not produce incomplete service records through any intake.
    assert (await f.http.post(f"/api/public/equipment/{row['public_qr_token']}/tickets",json=qr_body())).status_code==409
    request_body={'equipment_id':row['id'],'title':'Не работает'}
    assert (await f.http.post('/api/service-requests',headers=auth(f.owner,f.org),json=request_body)).status_code==409
    assert (await f.http.post('/api/client-portal/requests',headers=f.manager_headers,json=request_body)).status_code==409
    done=await complete(f,row); assert done.status_code==200,done.text
    saved=done.json()
    assert (saved['id'],saved['public_qr_token'])==(row['id'],row['public_qr_token'])
    changes=dict(manufacturer='Новый производитель',model='Новая модель',serial_number='UPDATED-001',
        equipment_type_id=f.kind.id,location='Мойка',site_id=str(f.sites[0].id),status='working',expected_version=saved['version'])
    edited=await f.http.patch(f"/api/equipment/{row['id']}",headers=auth(f.owner,f.org),json=changes)
    assert edited.status_code==200,edited.text
    assert edited.json()['public_qr_token']==row['public_qr_token']
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
