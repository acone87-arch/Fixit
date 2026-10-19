"""Fast route/ORM regressions; PostgreSQL tests cover row locks and authorization."""
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, select
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.database import Base
from app.models.core import Equipment, EquipmentInventoryBatch, EquipmentType, User, UserRole
from app.models.customer import Client, Site
from app.models.organization import Organization
from app.routers.equipment import delete_equipment, delete_pending_equipment
from app.routers.inventory import batch_out, batch_pdf, create_batch
from app.schemas.equipment import EquipmentBatchCreate, EquipmentPendingDelete


@compiles(JSONB, 'sqlite')
@compiles(ARRAY, 'sqlite')
def sqlite_test_json(_type, _compiler, **_kw):
    return 'JSON'


class AsyncRoutesSession:
    """Run route SQL against SQLite without pretending to test PostgreSQL locks."""
    def __init__(self, session):
        self.session = session

    def __getattr__(self, name):
        method = getattr(self.session, name)
        if name in {'add', 'add_all'}:
            return method

        async def call(*args, **kwargs):
            return method(*args, **kwargs)
        return call


@pytest.fixture
def inventory_db():
    engine = create_engine('sqlite://')
    @event.listens_for(engine, 'connect')
    def enable_foreign_keys(connection, _record):
        connection.execute('PRAGMA foreign_keys=ON')
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        org = Organization(name='Inventory test', slug='inventory-test')
        user = User(full_name='Admin', email='inventory@example.com', hashed_password='unused', role=UserRole.admin)
        session.add_all([org, user]); session.flush()
        client = Client(name='Client', organization_id=org.id)
        kind = EquipmentType(name='Machine', organization_id=org.id)
        session.add_all([client, kind]); session.flush()
        sites = [Site(name=name, organization_id=org.id, client_id=client.id) for name in ['A', 'B']]
        session.add_all(sites); session.commit()
        yield SimpleNamespace(db=AsyncRoutesSession(session), session=session, sites=sites, kind=kind,
            user=SimpleNamespace(id=user.id, organization_id=org.id, role=UserRole.admin))
    engine.dispose()


async def make_batch(f, quantity=10, site=None, key=None):
    result = await create_batch(EquipmentBatchCreate(site_id=(site or f.sites[0]).id,
        quantity=quantity, idempotency_key=key or uuid.uuid4()), f.db, f.user)
    rows = list(f.session.scalars(select(Equipment).where(Equipment.inventory_batch_id == result.id)
        .order_by(Equipment.inventory_number)))
    return result, rows


@pytest.mark.asyncio
async def test_second_batch_continues_numbers_on_same_site(inventory_db):
    f = inventory_db
    first, rows = await make_batch(f)
    assert [row.inventory_number for row in rows] == list(range(1, 11))
    _, more = await make_batch(f)
    assert [row.name for row in more] == [f'Оборудование №{n}' for n in range(11, 21)]
    _, other = await make_batch(f, 2, site=f.sites[1])
    assert [row.inventory_number for row in other] == [1, 2]
    retry, same = await make_batch(f, key=first.id)
    assert retry.id == first.id and [r.id for r in same] == [r.id for r in rows]
    _, final = await make_batch(f, 1)
    assert final[0].inventory_number == 21


@pytest.mark.asyncio
async def test_pending_qr_can_be_deleted_without_reusing_issued_numbers(inventory_db):
    f = inventory_db
    created, rows = await make_batch(f, 2)
    for row in rows:
        response = await delete_equipment(row.id, f.db, f.user)
        assert response.status_code == 204
    assert f.session.get(EquipmentInventoryBatch, created.id).quantity == 2
    _, more = await make_batch(f, 1)
    assert more[0].inventory_number == 3
    with pytest.raises(HTTPException) as error:
        await batch_pdf(created.id, f.db, f.user)
    assert error.value.status_code == 409


@pytest.mark.asyncio
async def test_bulk_delete_is_atomic_scoped_and_updates_pdf(inventory_db):
    from io import BytesIO
    from pypdf import PdfReader
    f = inventory_db
    created, rows = await make_batch(f, 3)
    _, other = await make_batch(f, 1, site=f.sites[1])
    rows[0].inventory_pending = False
    rows[0].equipment_type_id = f.kind.id
    rows[0].serial_number = 'FILLED'
    f.session.commit()

    async def delete(ids, user=None):
        return await delete_pending_equipment(EquipmentPendingDelete(site_id=f.sites[0].id,
            equipment_ids=ids), f.db, user or f.user)

    for ids, user, code in [
        ([rows[1].id, rows[0].id], None, 409),
        ([rows[1].id, other[0].id], None, 404),
        ([rows[1].id, uuid.uuid4()], None, 404),
        ([rows[1].id], SimpleNamespace(organization_id=uuid.uuid4()), 404),
    ]:
        with pytest.raises(HTTPException) as error:
            await delete(ids, user)
        assert error.value.status_code == code
        assert f.session.get(Equipment, rows[1].id) is not None
    # Filled printed cards remain protected, including single-card deletion.
    with pytest.raises(HTTPException) as error:
        await delete_equipment(rows[0].id, f.db, f.user)
    assert error.value.status_code == 409
    assert (await delete([rows[1].id, rows[1].id])).status_code == 204
    counters = await batch_out(f.session.get(EquipmentInventoryBatch, created.id), f.db)
    assert (counters.quantity, counters.remaining, counters.deleted, counters.completed) == (3, 2, 1, 1)
    response = await batch_pdf(created.id, f.db, f.user)
    pdf = PdfReader(BytesIO(response.body))
    tokens = [annotation.get_object()['/A']['/URI'].rsplit('/', 1)[-1]
        for page in pdf.pages for annotation in page['/Annots']]
    assert tokens == [str(rows[0].public_qr_token), str(rows[2].public_qr_token)]
    retry, retry_rows = await make_batch(f, 3, key=created.id)
    assert retry.deleted == 1 and len(retry_rows) == 2  # retry never recreates removed cards


@pytest.mark.asyncio
async def test_delete_rejects_canonical_service_history(inventory_db):
    from app.models.service_request import ServiceRequest
    f = inventory_db
    _, rows = await make_batch(f, 2)
    f.session.add(ServiceRequest(organization_id=f.user.organization_id,
        equipment_id=rows[0].id, number=1, title='Existing request', status='new'))
    f.session.commit()
    with pytest.raises(HTTPException) as error:
        await delete_pending_equipment(EquipmentPendingDelete(site_id=f.sites[0].id,
            equipment_ids=[row.id for row in rows]), f.db, f.user)
    assert error.value.status_code == 409
    assert all(f.session.get(Equipment, row.id) is not None for row in rows)


@pytest.mark.asyncio
async def test_numbering_migration_preserves_existing_labels(inventory_db):
    import importlib.util
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    f = inventory_db
    _, rows = await make_batch(f, 10)
    identities = [(row.id, row.name, row.public_qr_token) for row in rows]
    f.sites[0].inventory_last_number = 0
    f.session.commit()
    spec = importlib.util.spec_from_file_location('qr_numbering_migration',
        'alembic/versions/20261019_0019_inventory_numbering.py')
    revision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision)
    with Operations.context(MigrationContext.configure(f.session.connection())):
        revision.downgrade()
        revision.upgrade()
        with pytest.raises(RuntimeError, match='Issued QR numbers'):
            revision.downgrade()
    f.session.commit()
    f.session.expire_all()
    assert f.sites[0].inventory_last_number == 10
    assert [(row.id, row.name, row.public_qr_token) for row in rows] == identities
    _, more = await make_batch(f, 2)
    assert [row.inventory_number for row in more] == [11, 12]


@pytest.mark.asyncio
async def test_bulk_delete_http_authorization_and_validation(inventory_db):
    import httpx
    from app.core.deps import get_current_user
    from app.database import get_db
    from app.main import app
    f = inventory_db
    _, rows = await make_batch(f, 2)
    previous = app.dependency_overrides.copy()
    current = f.user
    async def user():
        return current
    async def database():
        yield f.db
    app.dependency_overrides[get_current_user] = user
    app.dependency_overrides[get_db] = database
    payload = dict(site_id=str(f.sites[0].id), equipment_ids=[str(rows[0].id)])
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://localhost') as http:
            for role in [UserRole.technician, UserRole.dispatcher, UserRole.client_admin, UserRole.client_site_user]:
                current = SimpleNamespace(**{**vars(f.user), 'role': role})
                assert (await http.post('/api/equipment/pending/delete', json=payload)).status_code == 403
            current = f.user
            for ids in [[], ['invalid'], [str(uuid.uuid4())] * 501]:
                response = await http.post('/api/equipment/pending/delete', json={**payload, 'equipment_ids': ids})
                assert response.status_code == 422, response.text
            response = await http.post('/api/equipment/pending/delete', json=payload)
            assert response.status_code == 204, response.text
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
