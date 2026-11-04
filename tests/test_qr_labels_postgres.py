"""Label allocation and binding invariants against real PostgreSQL."""
import asyncio
import uuid
from io import BytesIO
import pytest
from pypdf import PdfReader
from sqlalchemy import func, select
from app.models.core import Equipment
from app.models.qr_label import QRLabel
from test_onboarding_postgres import auth, pg

pytestmark = pytest.mark.asyncio

async def batch(pg, quantity=2, **changes):
    data = dict(site_id=str(pg.sites[0].id), quantity=quantity, idempotency_key=str(uuid.uuid4()))
    data.update(changes)
    response = await pg.http.post('/api/equipment-inventory/batches', headers=auth(pg.owner, pg.org), json=data)
    assert response.status_code == 201, response.text
    labels = await pg.http.get('/api/qr-labels', headers=auth(pg.owner, pg.org))
    return data, response.json(), [row for row in labels.json() if row['batch_id'] == data['idempotency_key']]

async def equipment(pg, site=0, serial=None):
    response = await pg.http.post('/api/equipment', headers=auth(pg.owner, pg.org), json={
        'equipment_type_id': pg.kind.id, 'site_id': str(pg.sites[site].id), 'serial_number': serial})
    assert response.status_code == 201, response.text
    return response.json()

async def test_batch_creates_only_labels_retry_and_pdf(pg):
    payload, created, labels = await batch(pg)
    assert len(labels) == 2 and all(row['status'] == 'free' for row in labels)
    assert (await pg.http.get('/api/equipment', headers=auth(pg.owner, pg.org))).json() == []
    repeat = await pg.http.post('/api/equipment-inventory/batches', headers=auth(pg.owner, pg.org), json=payload)
    assert repeat.status_code == 201 and repeat.json()['id'] == created['id']
    pdf = await pg.http.get(created['pdf_url'], headers=auth(pg.owner, pg.org))
    assert pdf.status_code == 200
    links = [a.get_object()['/A']['/URI'] for a in PdfReader(BytesIO(pdf.content)).pages[0]['/Annots']]
    assert {link.rsplit('/',1)[1] for link in links} == {label['token'] for label in labels}
    guest = await pg.http.get('/api/public/equipment/' + labels[0]['token'])
    assert guest.status_code == 200 and guest.json()['inventory_pending'] is True

async def test_binding_existing_keeps_both_urls_and_prevents_reassignment(pg):
    original = await equipment(pg, serial='SAME-MACHINE')
    other = await equipment(pg, serial='OTHER')
    _, created, labels = await batch(pg)
    path = '/api/qr-labels/' + labels[0]['token'] + '/bind'
    body = {'equipment_id': original['id'], 'idempotency_key': str(uuid.uuid4())}
    for _ in range(2):
        bound = await pg.http.post(path, headers=auth(pg.owner, pg.org), json=body)
        assert bound.status_code == 200, bound.text
        assert bound.json()['equipment_id'] == original['id']
    refused = await pg.http.post(path, headers=auth(pg.owner, pg.org), json={**body,'equipment_id':other['id']})
    assert refused.status_code == 409
    for token in (labels[0]['token'], original['public_qr_token']):
        response = await pg.http.get('/api/public/equipment/' + token)
        assert response.status_code == 200 and response.json()['serial_number'] == 'SAME-MACHINE'
        lookup = await pg.http.get('/api/equipment/by-qr/' + token, headers=auth(pg.owner, pg.org))
        assert lookup.status_code == 200 and lookup.json()['id'] == original['id']
    batches = (await pg.http.get('/api/equipment-inventory/batches',headers=auth(pg.owner, pg.org))).json()
    assert batches[0]['completed'] == 1
    # Reprint uses the attached physical identity, not a newly generated QR.
    pdf = await pg.http.get(f"/api/equipment/{original['id']}/qr", headers=auth(pg.owner, pg.org))
    assert labels[0]['token'] in str(PdfReader(BytesIO(pdf.content)).pages[0]['/Annots'][0].get_object()['/A']['/URI'])

async def test_atomic_new_equipment_concurrent_retry_and_conflict(pg):
    _, _, labels = await batch(pg)
    path = '/api/qr-labels/' + labels[0]['token'] + '/bind'
    body = {'new_equipment': {'equipment_type_id': pg.kind.id, 'model':'QR demo'}, 'idempotency_key':str(uuid.uuid4())}
    responses = await asyncio.gather(*[pg.http.post(path,headers=auth(pg.owner,pg.org),json=body) for _ in range(2)])
    assert [r.status_code for r in responses] == [200,200], [r.text for r in responses]
    assert responses[0].json()['equipment_id'] == responses[1].json()['equipment_id']
    async with pg.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Equipment)) == 1
    changed = await pg.http.post(path,headers=auth(pg.owner,pg.org),json={**body,'new_equipment':{'equipment_type_id':pg.kind.id,'model':'Changed'}})
    assert changed.status_code == 409

async def test_access_cross_site_and_serial_conflict_leave_label_free(pg):
    target = await equipment(pg, site=1)
    await equipment(pg, serial='DUPLICATE')
    _, _, labels = await batch(pg)
    path = '/api/qr-labels/' + labels[0]['token'] + '/bind'
    body = {'equipment_id':target['id'], 'idempotency_key':str(uuid.uuid4())}
    assert (await pg.http.post(path,headers=auth(pg.owner,pg.org),json=body)).status_code == 409
    assert (await pg.http.post(path,headers=auth(pg.tech,pg.org),json=body)).status_code == 403
    assert (await pg.http.get('/api/qr-labels',headers=auth(pg.tech,pg.org))).json() == []
    duplicate = {'new_equipment':{'equipment_type_id':pg.kind.id,'serial_number':'DUPLICATE'},'idempotency_key':str(uuid.uuid4())}
    assert (await pg.http.post(path,headers=auth(pg.owner,pg.org),json=duplicate)).status_code == 409
    state = await pg.http.get(path.removesuffix('/bind'),headers=auth(pg.owner,pg.org))
    assert state.json()['status'] == 'free'

async def test_legacy_empty_token_can_bind_without_reusing_placeholder(pg):
    async with pg.sessions() as db:
        legacy = Equipment(organization_id=pg.org.id, site_id=pg.sites[0].id,
            name='Оборудование №1', inventory_pending=True)
        db.add(legacy); await db.flush()
        token = legacy.public_qr_token
        db.add(QRLabel(token=token, organization_id=pg.org.id, site_id=legacy.site_id,
            legacy_equipment_id=legacy.id, number=1))
        await db.commit()
    existing = await equipment(pg)
    bound = await pg.http.post(f'/api/qr-labels/{token}/bind',headers=auth(pg.owner,pg.org),json={
        'equipment_id':existing['id'],'idempotency_key':str(uuid.uuid4())})
    assert bound.status_code == 200, bound.text
    visible = (await pg.http.get('/api/equipment',headers=auth(pg.owner,pg.org))).json()
    assert [item['id'] for item in visible] == [existing['id']]
    public = await pg.http.get(f'/api/public/equipment/{token}')
    assert public.status_code == 200 and public.json()['inventory_pending'] is False

async def test_selected_print_preserves_order_deduplicates_and_paginates(pg):
    _, _, labels = await batch(pg, quantity=10)
    tokens = [row['token'] for row in reversed(labels)]
    response = await pg.http.post('/api/qr-labels/print/pdf', headers=auth(pg.owner, pg.org),
        json={'tokens':tokens + [tokens[0]], 'free_only':True})
    assert response.status_code == 200, response.text
    assert response.headers['x-label-count'] == '10'
    assert response.headers['x-page-count'] == '2'
    reader = PdfReader(BytesIO(response.content))
    assert len(reader.pages) == 2
    assert [len(page['/Annots']) for page in reader.pages] == [8, 2]
    urls = [a.get_object()['/A']['/URI'].rsplit('/',1)[1] for page in reader.pages for a in page['/Annots']]
    assert urls == tokens
    assert round(float(reader.pages[0].mediabox.width)) == 595
    assert round(float(reader.pages[0].mediabox.height)) == 842
    async with pg.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Equipment)) == 0
        assert await db.scalar(select(func.count()).select_from(QRLabel).where(QRLabel.equipment_id.is_(None))) == 10

async def test_print_free_only_rechecks_binding_and_rejects_foreign_selection(pg):
    _, _, labels = await batch(pg)
    tokens = [row['token'] for row in labels]
    target = await equipment(pg)
    bound = await pg.http.post(f'/api/qr-labels/{tokens[0]}/bind', headers=auth(pg.owner,pg.org),
        json={'equipment_id':target['id'], 'idempotency_key':str(uuid.uuid4())})
    assert bound.status_code == 200
    endpoint = '/api/qr-labels/print/pdf'
    response = await pg.http.post(endpoint, headers=auth(pg.owner,pg.org), json={'tokens':tokens,'free_only':True})
    assert response.status_code == 409
    selected = await pg.http.post(endpoint, headers=auth(pg.owner,pg.org), json={'tokens':[tokens[1]],'free_only':True})
    assert selected.status_code == 200
    assert selected.headers['x-label-count'] == '1'
    mixed = await pg.http.post(endpoint, headers=auth(pg.owner,pg.org), json={'tokens':tokens})
    assert mixed.status_code == 200
    assert (await pg.http.post(endpoint,headers=auth(pg.tech,pg.org),json={'tokens':tokens})).status_code == 403
    assert (await pg.http.post(endpoint,json={'tokens':tokens})).status_code == 401
    async with pg.sessions() as db:
        foreign = QRLabel(organization_id=pg.sites[3].organization_id,site_id=pg.sites[3].id)
        db.add(foreign); await db.commit(); foreign_token = str(foreign.token)
    assert (await pg.http.post(endpoint,headers=auth(pg.owner,pg.org),json={'tokens':[tokens[1],foreign_token]})).status_code == 404
    for values in ([], tokens * 251, ['not-a-token']):
        assert (await pg.http.post(endpoint,headers=auth(pg.owner,pg.org),json={'tokens':values})).status_code == 422
