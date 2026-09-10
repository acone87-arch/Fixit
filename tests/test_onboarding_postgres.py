"""P0.1: HTTP → реальные guards/router/ORM → PostgreSQL.

Запуск: FIXIT_TEST_DATABASE_URL=postgresql+asyncpg://.../fixit_test pytest -q tests/test_onboarding_postgres.py
Только loopback БД с именем *_test. Каждый тест создаёт отдельную schema и удаляет
только её. DDL текущих моделей не заменяет Alembic upgrade/restore-проверку P0.7.
Без явного URL тесты пропускаются; это не успешная интеграционная приёмка.
"""
import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.security import create_access_token, hash_password
from app.database import Base, get_db
from app.main import app
from app.models.core import EquipmentType, User, UserRole
from app.models.customer import Client, ClientInvite, ClientUserAccess, Site
from app.models.organization import Organization, OrganizationMembership

pytestmark = pytest.mark.asyncio
PASSWORD = 'pilot-integration-password'


@pytest_asyncio.fixture
async def pg():
    raw_url = os.getenv('FIXIT_TEST_DATABASE_URL')
    if not raw_url:
        pytest.skip('FIXIT_TEST_DATABASE_URL не задан: PostgreSQL integration не выполнен')
    url = make_url(raw_url)
    if (url.drivername != 'postgresql+asyncpg' or url.host not in {'localhost', '127.0.0.1', '::1'}
            or not (url.database or '').endswith('_test')):
        pytest.fail('Требуется отдельная loopback PostgreSQL БД *_test; production URL запрещён')
    schema = 'pilot_' + uuid.uuid4().hex
    admin = create_async_engine(url)
    async with admin.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(url, connect_args={'server_settings': {'search_path': schema}})
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    previous = app.dependency_overrides.copy()
    try:
        async with engine.begin() as connection:
            # У ClientInvite подмножество общего enum; явно сохраняем полный тип.
            await connection.execute(text("CREATE TYPE user_role AS ENUM ('owner','admin','dispatcher','technician','client_admin','client_site_user')"))
            await connection.run_sync(Base.metadata.create_all)
        org, foreign_org = Organization(name='Сервис A', slug='service-a'), Organization(name='Сервис B', slug='service-b')
        owner, tech, existing = [User(full_name=name, email=email, role=role,
            hashed_password=hash_password(PASSWORD), is_active=True) for name,email,role in [
            ('Владелец','owner@example.com',UserRole.owner),
            ('Техник','tech@example.com',UserRole.technician),
            ('Существующий','existing@example.com',UserRole.technician)]]
        async with sessions() as db:
            db.add_all([org, foreign_org, owner, tech, existing]); await db.flush()
            client = Client(organization_id=org.id, name='Клиент A')
            other = Client(organization_id=org.id, name='Клиент B')
            foreign = Client(organization_id=foreign_org.id, name='Чужой tenant')
            db.add_all([client, other, foreign]); await db.flush()
            sites = [Site(organization_id=o, client_id=c, name=n) for o,c,n in [
                (org.id,client.id,'Свой'),(org.id,client.id,'Другой Site'),
                (org.id,other.id,'Другой Client'),(foreign_org.id,foreign.id,'Другой tenant')]]
            kind = EquipmentType(organization_id=org.id, name='Поломойка')
            db.add_all(sites + [kind, OrganizationMembership(organization_id=org.id,user_id=owner.id,role=UserRole.owner),
                OrganizationMembership(organization_id=org.id,user_id=tech.id,role=UserRole.technician)])
            await db.commit()
        async def database():
            async with sessions() as session:
                yield session
        app.dependency_overrides[get_db] = database
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url='http://localhost') as http:
            yield SimpleNamespace(http=http, sessions=sessions, org=org, client=client,
                other=other, sites=sites, kind=kind, owner=owner, tech=tech, existing=existing)
    finally:
        app.dependency_overrides.clear(); app.dependency_overrides.update(previous)
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()


def auth(user, org):
    return {'Authorization': 'Bearer ' + create_access_token(user.id, org.id, user.role.value)}


async def invite(pg, kind='site-manager', **overrides):
    payload = {'site_id': str(pg.sites[0].id)} if kind == 'site-manager' else {}
    payload.update(overrides)
    response = await pg.http.post(f'/api/client-portal/clients/{pg.client.id}/invites/{kind}',
        headers=auth(pg.owner, pg.org), json=payload)
    assert response.status_code == 201, response.text
    return response.json()


async def accept(pg, invitation, email='manager@example.com', **overrides):
    body = {'email': email, 'password': PASSWORD, 'full_name': 'Менеджер пилота'}
    body.update(overrides)
    return await pg.http.post('/api/join/' + invitation['join_url'].rsplit('/', 1)[1] + '/accept', json=body)


async def changed(pg, model, key, **values):
    async with pg.sessions() as db:
        row = await db.get(model, key)
        for name,value in values.items(): setattr(row, name, value)
        await db.commit()


async def test_new_manager_equipment_and_technician_access(pg):
    invitation = await invite(pg)
    response = await accept(pg, invitation, role='owner', site_id=str(pg.sites[2].id))
    assert response.status_code == 200, response.text
    headers = {'Authorization': 'Bearer ' + response.json()['access_token']}
    assert response.json()['role'] == 'client_site_user'
    sites = await pg.http.get('/api/sites', headers=headers)
    assert sites.status_code == 200, sites.text
    assert {x['id'] for x in sites.json()} == {str(pg.sites[0].id)}
    types = await pg.http.get('/api/equipment-types', headers=headers)
    assert types.status_code == 200 and types.json()[0]['id'] == pg.kind.id
    payload = {'site_id': str(pg.sites[0].id), 'equipment_type_id': pg.kind.id, 'serial_number': 'PILOT-001'}
    created = await pg.http.post('/api/equipment', headers=headers, json=payload)
    assert created.status_code == 201, created.text
    equipment_id = created.json()['id']
    for site in pg.sites[1:]:
        denied = await pg.http.post('/api/equipment', headers=headers, json={**payload,'site_id':str(site.id)})
        assert denied.status_code in {403,422}, denied.text
    denied = await pg.http.post('/api/equipment-types', headers=headers, json={'name':'Чужое право'})
    assert denied.status_code == 403
    technician = auth(pg.tech, pg.org)
    assert (await pg.http.get('/api/equipment', headers=technician)).json() == []
    grant = await pg.http.put(f'/api/clients/{pg.client.id}/technicians', headers=auth(pg.owner,pg.org), json={'technician_ids':[str(pg.tech.id)]})
    assert grant.status_code == 200, grant.text
    assert equipment_id in {x['id'] for x in (await pg.http.get('/api/equipment',headers=technician)).json()}
    revoke = await pg.http.put(f'/api/clients/{pg.client.id}/technicians', headers=auth(pg.owner,pg.org),json={'technician_ids':[]})
    assert revoke.status_code == 200
    assert (await pg.http.get('/api/equipment',headers=technician)).json() == []


async def test_existing_user_then_director_same_client(pg):
    first = await invite(pg)
    wrong = await accept(pg,first,pg.existing.email,password='wrong-password')
    assert wrong.status_code == 401
    accepted = await accept(pg,first,pg.existing.email)
    assert accepted.status_code == 200, accepted.text
    director = await invite(pg,'director')
    promoted = await accept(pg,director,pg.existing.email)
    assert promoted.status_code == 200, promoted.text
    headers = {'Authorization': 'Bearer ' + promoted.json()['access_token']}
    assert promoted.json()['role'] == 'client_admin'
    assert {x['id'] for x in (await pg.http.get('/api/sites',headers=headers)).json()} == {str(s.id) for s in pg.sites[:2]}
    async with pg.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Client)) == 3
        assert (await db.get(Client,pg.client.id)).adoption_status == 'active'
        assert await db.scalar(select(func.count()).select_from(User).where(User.email == pg.existing.email)) == 1


@pytest.mark.parametrize('reason', ['expired','revoked','reused','organization','client','site','inviter'])
async def test_invalid_invites_do_not_create_access(pg, reason):
    invitation = await invite(pg)
    key = uuid.UUID(invitation['id'])
    if reason == 'expired': await changed(pg,ClientInvite,key,expires_at=datetime.now(timezone.utc)-timedelta(seconds=1))
    elif reason == 'revoked':
        response = await pg.http.post(f'/api/client-portal/invites/{key}/revoke',headers=auth(pg.owner,pg.org))
        assert response.status_code == 200
    elif reason == 'reused': assert (await accept(pg,invitation)).status_code == 200
    else:
        model, obj = {'organization':(Organization,pg.org),'client':(Client,pg.client),'site':(Site,pg.sites[0]),'inviter':(User,pg.owner)}[reason]
        await changed(pg,model,obj.id,is_active=False)
    response = await accept(pg,invitation,email='unexpected@example.com')
    assert response.status_code == 404, response.text
    async with pg.sessions() as db:
        assert await db.scalar(select(User.id).where(User.email=='unexpected@example.com')) is None


async def test_wrong_email_and_wrong_invite_site(pg):
    invitation = await invite(pg,invited_email='specific@example.com')
    assert (await accept(pg,invitation)).status_code == 403
    for site in pg.sites[2:]:
        response = await pg.http.post(f'/api/client-portal/clients/{pg.client.id}/invites/site-manager',
            headers=auth(pg.owner,pg.org),json={'site_id':str(site.id)})
        assert response.status_code == 422


async def test_concurrent_accept_same_token_commits_once(pg):
    invitation = await invite(pg)
    results = await asyncio.gather(accept(pg,invitation),accept(pg,invitation))
    assert sorted(r.status_code for r in results) == [200,404], [r.text for r in results]
    async with pg.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(ClientUserAccess)) == 1


async def test_inactive_technician_membership_cannot_be_granted(pg):
    async with pg.sessions() as db:
        membership = await db.scalar(select(OrganizationMembership).where(OrganizationMembership.user_id==pg.tech.id))
        membership.is_active=False; await db.commit()
    response = await pg.http.put(f'/api/clients/{pg.client.id}/technicians',headers=auth(pg.owner,pg.org),json={'technician_ids':[str(pg.tech.id)]})
    assert response.status_code == 422, response.text


@pytest.mark.parametrize('revoked', ['user','membership','access'])
async def test_pending_invite_cannot_restore_revoked_identity(pg, revoked):
    first = await invite(pg)
    assert (await accept(pg,first,pg.existing.email)).status_code == 200
    pending = await invite(pg)
    async with pg.sessions() as db:
        if revoked == 'user': row = await db.get(User,pg.existing.id)
        else:
            model = OrganizationMembership if revoked == 'membership' else ClientUserAccess
            row = await db.scalar(select(model).where(model.user_id==pg.existing.id))
        row.is_active=False; await db.commit()
    response = await accept(pg,pending,pg.existing.email)
    assert response.status_code == 403, response.text


async def test_concurrent_different_invites_same_existing_user(pg):
    first, second = await invite(pg), await invite(pg)
    results = await asyncio.gather(accept(pg, first, pg.existing.email),accept(pg, second, pg.existing.email))
    assert [r.status_code for r in results] == [200,200], [r.text for r in results]
    async with pg.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(ClientUserAccess).where(ClientUserAccess.user_id==pg.existing.id))==1


async def test_concurrent_new_account_separate_invites_is_retryable(pg):
    first, second = await invite(pg), await invite(pg)
    results = await asyncio.gather(accept(pg,first),accept(pg,second))
    assert all(r.status_code in {200,409} for r in results), [r.text for r in results]
    assert any(r.status_code==200 for r in results)
    async with pg.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(User).where(User.email=='manager@example.com'))==1
        assert await db.scalar(select(func.count()).select_from(ClientUserAccess))==1


async def test_concurrent_fleet_replacement_is_consistent(pg):
    from app.models.customer import TechnicianClientAccess
    url=f'/api/clients/{pg.client.id}/technicians'
    results=await asyncio.gather(*[pg.http.put(url,headers=auth(pg.owner,pg.org),json={'technician_ids':[str(pg.tech.id)]}) for _ in range(2)])
    assert all(r.status_code==200 for r in results),[r.text for r in results]
    async with pg.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(TechnicianClientAccess))==1
