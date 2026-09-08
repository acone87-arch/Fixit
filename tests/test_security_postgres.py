"""P0.2: HTTP/JWT → настоящие router/service/ORM → PostgreSQL, без production."""
import asyncio
import uuid
from datetime import datetime, timezone
from io import BytesIO

import pytest
import pytest_asyncio
from PIL import Image
from sqlalchemy import func, select

from app.core.security import hash_password
from app.models.core import Equipment, EquipmentType, Task, Ticket, User, UserRole
from app.models.customer import ClientUserAccess, TechnicianClientAccess
from app.models.organization import Organization, OrganizationMembership
from app.models.repair import Repair, RepairAttachment, SyncOperation
from app.models.service_request import ServiceRequest
from app.models.warehouse import Part, Warehouse, WarehouseStock
from test_onboarding_postgres import pg, auth, PASSWORD, invite, accept

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def sec(pg, tmp_path, monkeypatch):
    from app.routers import repairs
    monkeypatch.setattr(repairs, 'UPLOAD_ROOT', tmp_path)
    async with pg.sessions() as db:
        foreign_org = await db.get(Organization, pg.sites[3].organization_id)
        pg.foreign_org = foreign_org
        foreign_kind=EquipmentType(organization_id=foreign_org.id,name='Чужой тип')
        db.add(foreign_kind);await db.flush()
        actors = {}
        for name, org, role in [('manager',pg.org,UserRole.client_site_user),
                ('director',pg.org,UserRole.client_admin),('tech2',pg.org,UserRole.technician),
                ('foreign_owner',foreign_org,UserRole.owner)]:
            account=User(full_name=name,email=name+'@example.com',role=role,hashed_password=hash_password(PASSWORD))
            db.add(account); await db.flush()
            db.add(OrganizationMembership(organization_id=org.id,user_id=account.id,role=role))
            actors[name]=account
        pg.actors=actors
        db.add_all([ClientUserAccess(organization_id=pg.org.id,user_id=actors['manager'].id,client_id=pg.client.id,site_id=pg.sites[0].id),
            ClientUserAccess(organization_id=pg.org.id,user_id=actors['director'].id,client_id=pg.client.id),
            TechnicianClientAccess(organization_id=pg.org.id,technician_id=actors['tech2'].id,client_id=pg.client.id)])
        equipment=[]
        for i,site in enumerate(pg.sites):
            eq=Equipment(organization_id=site.organization_id,site_id=site.id,equipment_type_id=foreign_kind.id if i==3 else pg.kind.id,
                name='Equipment '+str(i),serial_number='SEC-'+str(i))
            db.add(eq); equipment.append(eq)
        await db.flush(); pg.equipment=equipment
        pg.ticket=Ticket(organization_id=pg.org.id,equipment_id=equipment[0].id,severity='not_working',
            idempotency_key=uuid.uuid4(),assigned_technician_id=pg.tech.id,status='assigned')
        db.add(pg.ticket); await db.flush()
        pg.task=Task(organization_id=pg.org.id,equipment_id=equipment[0].id,ticket_id=pg.ticket.id,
            assigned_to=pg.tech.id,title='Исторический наряд',status='in_progress')
        db.add(pg.task)
        pg.warehouse=Warehouse(organization_id=pg.org.id,name='Мобильный',type='mobile',owner_user_id=pg.tech.id)
        pg.part=Part(organization_id=pg.org.id,name='Деталь',article='SEC-PART')
        pg.foreign_part=Part(organization_id=foreign_org.id,name='Чужая деталь',article='FOREIGN')
        db.add_all([pg.warehouse,pg.part,pg.foreign_part]);await db.flush()
        db.add(WarehouseStock(warehouse_id=pg.warehouse.id,part_id=pg.part.id,quantity=10))
        pg.repairs=[]
        for i,eq in enumerate(equipment):
            sr=ServiceRequest(organization_id=eq.organization_id,number=i+1,equipment_id=eq.id,
                title='Поломка',status='completed',assigned_technician_id=pg.tech.id)
            db.add(sr);await db.flush()
            repair=Repair(organization_id=eq.organization_id,local_uuid=uuid.uuid4(),equipment_id=eq.id,
                service_request_id=sr.id,technician_id=pg.tech.id,description='Результат',device_updated_at=datetime.now(timezone.utc))
            db.add(repair); pg.repairs.append(repair)
        await db.commit()
    yield pg


def png():
    stream=BytesIO();Image.new('RGB',(3,3),'blue').save(stream,format='PNG');return stream.getvalue()


async def upload(sec, repair, actor, key='photo'):
    return await sec.http.post(f'/api/repairs/{repair.id}/attachments',headers=auth(actor,sec.org),
        data={'kind':'after','client_id':key},files={'file':('photo.png',png(),'image/png')})


def payload(sec, **changes):
    result={'local_uuid':str(uuid.uuid4()),'equipment_id':str(sec.equipment[0].id),'task_id':str(sec.task.id),
        'description':'Результат из очереди','device_updated_at':datetime.now(timezone.utc).isoformat(),
        'base_equipment_version':1,'parts_used':[]}
    result.update(changes);return result


async def sync(sec, item, actor=None):
    response=await sec.http.post('/api/v1/sync/repairs',headers=auth(actor or sec.tech,sec.org),
        json={'device_id':'security-test','repairs':[item]})
    assert response.status_code==200,response.text
    return response.json()['results'][0]


async def test_shared_user_disable_is_membership_only(sec):
    async with sec.sessions() as db:
        db.add(OrganizationMembership(organization_id=sec.foreign_org.id,user_id=sec.tech.id,role=UserRole.technician));await db.commit()
    response=await sec.http.patch(f'/api/users/{sec.tech.id}',headers=auth(sec.owner,sec.org),
        json={'is_active':False,'full_name':sec.tech.full_name,'phone':sec.tech.phone})
    assert response.status_code==200,response.text
    assert response.json()['is_active'] is False
    assert (await sec.http.get('/api/users/me',headers=auth(sec.tech,sec.org))).status_code==401
    assert (await sec.http.get('/api/users/me',headers=auth(sec.tech,sec.foreign_org))).status_code==200
    async with sec.sessions() as db:
        assert (await db.get(User,sec.tech.id)).is_active


async def test_shared_user_contacts_cannot_be_changed_by_other_tenant(sec):
    async with sec.sessions() as db:
        db.add(OrganizationMembership(organization_id=sec.foreign_org.id,user_id=sec.tech.id,role=UserRole.technician));await db.commit()
    response=await sec.http.patch(f'/api/users/{sec.tech.id}',headers=auth(sec.owner,sec.org),json={'full_name':'Подмена','phone':'123'})
    assert response.status_code==409,response.text
    async with sec.sessions() as db:
        assert (await db.get(User,sec.tech.id)).full_name==sec.tech.full_name


async def test_existing_email_requires_account_consent(sec):
    response=await sec.http.post('/api/users',headers=auth(sec.owner,sec.org),json={
        'full_name':'Подмена','email':sec.actors['foreign_owner'].email,'password':'attacker-password','role':'admin'})
    assert response.status_code==409,response.text
    async with sec.sessions() as db:
        assert not await db.scalar(select(OrganizationMembership).where(
            OrganizationMembership.organization_id==sec.org.id,OrganizationMembership.user_id==sec.actors['foreign_owner'].id))


@pytest.mark.parametrize('role',['manager','director'])
@pytest.mark.parametrize('resource',['/api/tasks','/api/warehouses','/api/parts','stock'])
async def test_client_cannot_read_internal_operations(sec,role,resource):
    path=f'/api/warehouses/{sec.warehouse.id}/stock' if resource=='stock' else resource
    response=await sec.http.get(path,headers=auth(sec.actors[role],sec.org))
    assert response.status_code==403,response.text


@pytest.mark.parametrize('role',['manager','director','tech2'])
async def test_reading_repair_does_not_authorize_upload(sec,role):
    own=await upload(sec,sec.repairs[0],sec.tech)
    assert own.status_code==201,own.text
    read=await sec.http.get(own.json()['download_url'],headers=auth(sec.actors[role],sec.org))
    assert read.status_code==200,read.text
    write=await upload(sec,sec.repairs[0],sec.actors[role],key='unauthorized')
    assert write.status_code==403,write.text
    async with sec.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(RepairAttachment))==1


async def test_author_delayed_photo_retry_and_revoked_membership(sec):
    first=await upload(sec,sec.repairs[0],sec.tech)
    second=await upload(sec,sec.repairs[0],sec.tech)
    assert first.status_code==second.status_code==201
    assert first.json()['id']==second.json()['id']
    revoked=await sec.http.delete(f'/api/users/{sec.tech.id}',headers=auth(sec.owner,sec.org))
    assert revoked.status_code==204,revoked.text
    assert (await upload(sec,sec.repairs[0],sec.tech,key='late')).status_code==401


@pytest.mark.parametrize('index',[1,2,3])
async def test_manager_cannot_read_foreign_equipment_or_media(sec,index):
    own=await upload(sec,sec.repairs[index],sec.owner) if index<3 else None
    headers=auth(sec.actors['manager'],sec.org)
    for url in [f'/api/equipment/{sec.equipment[index].id}/passport',f'/api/repairs/{sec.repairs[index].id}/act.pdf']:
        r=await sec.http.get(url,headers=headers);assert r.status_code in {403,404},r.text
    if own:
        assert own.status_code==201,own.text
        r=await sec.http.get(own.json()['download_url'],headers=headers);assert r.status_code in {403,404},r.text


@pytest.mark.parametrize('mode',['no-context','wrong-ticket','other-tech-ticket','foreign-ticket','cancelled-task','mixed-ticket','foreign-part'])
async def test_legacy_sync_rejects_untrusted_context(sec,mode):
    item=payload(sec)
    if mode=='no-context':item['task_id']=None
    elif mode=='wrong-ticket':item.update(task_id=None,ticket_id=str(uuid.uuid4()))
    elif mode=='other-tech-ticket':
        item.update(task_id=None,ticket_id=str(sec.ticket.id))
        async with sec.sessions() as db:
            t=await db.get(Ticket,sec.ticket.id);t.assigned_technician_id=sec.actors['tech2'].id;await db.commit()
    elif mode=='foreign-ticket':
        item.update(task_id=None,ticket_id=str(sec.ticket.id))
        async with sec.sessions() as db:
            t=await db.get(Ticket,sec.ticket.id);t.organization_id=sec.foreign_org.id;await db.commit()
    elif mode=='cancelled-task':
        async with sec.sessions() as db:
            t=await db.get(Task,sec.task.id);t.status='cancelled';await db.commit()
    elif mode=='mixed-ticket':item['ticket_id']=str(uuid.uuid4())
    elif mode=='foreign-part':item['parts_used']=[{'part_id':str(sec.foreign_part.id),'quantity':-1}]
    result=await sync(sec,item)
    assert result['resolved_as']=='failed',result
    async with sec.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Repair))==4
        assert await db.scalar(select(func.count()).select_from(SyncOperation))==0
        assert (await db.get(Equipment,sec.equipment[0].id)).version==1


@pytest.mark.parametrize('context',['task','ticket'])
async def test_valid_legacy_queue_and_owner_scoped_retry(sec,context):
    item=payload(sec)
    if context=='ticket':item.update(task_id=None,ticket_id=str(sec.ticket.id))
    first=await sync(sec,item);assert first['resolved_as']=='applied',first
    retry=await sync(sec,item);assert retry['resolved_as']=='already_synced',retry
    assert retry['server_id']==first['server_id']
    stolen=await sync(sec,item,sec.actors['tech2'])
    assert stolen['resolved_as']=='failed' and stolen['server_id'] is None,stolen


async def test_null_site_grant_never_promotes_site_manager(sec):
    async with sec.sessions() as db:
        grant=await db.scalar(select(ClientUserAccess).where(ClientUserAccess.user_id==sec.actors['manager'].id))
        grant.site_id=None;await db.commit()
    r=await sec.http.get('/api/sites',headers=auth(sec.actors['manager'],sec.org))
    assert r.status_code==403,r.text


async def test_director_cannot_attach_another_clients_user(sec):
    async with sec.sessions() as db:
        grant=await db.scalar(select(ClientUserAccess).where(ClientUserAccess.user_id==sec.actors['manager'].id))
        grant.client_id=sec.other.id;grant.site_id=sec.sites[2].id;await db.commit()
    r=await sec.http.post('/api/client-portal/access',headers=auth(sec.actors['director'],sec.org),json={
        'user_id':str(sec.actors['manager'].id),'client_id':str(sec.client.id),'site_id':str(sec.sites[0].id)})
    assert r.status_code in {403,409},r.text
    r=await sec.http.get('/api/sites',headers=auth(sec.actors['manager'],sec.org))
    assert r.status_code==200 and {s['id'] for s in r.json()}=={str(sec.sites[2].id)},r.text


async def test_deleted_access_cannot_be_restored_by_pending_invite(sec):
    invitation=await invite(sec)
    async with sec.sessions() as db:
        key=await db.scalar(select(ClientUserAccess.id).where(ClientUserAccess.user_id==sec.actors['manager'].id))
    r=await sec.http.delete(f'/api/client-portal/access/{key}',headers=auth(sec.owner,sec.org));assert r.status_code==204,r.text
    r=await accept(sec,invitation,email=sec.actors['manager'].email)
    assert r.status_code==403,r.text


async def test_concurrent_revoke_and_accept_never_restores_member(sec):
    invitation=await invite(sec)
    revoke, accepted=await asyncio.gather(
        sec.http.delete(f'/api/users/{sec.actors["manager"].id}',headers=auth(sec.owner,sec.org)),
        accept(sec,invitation,email=sec.actors['manager'].email))
    assert revoke.status_code==204,revoke.text
    assert accepted.status_code in {200,403},accepted.text
    assert (await sec.http.get('/api/sites',headers=auth(sec.actors['manager'],sec.org))).status_code==401
    async with sec.sessions() as db:
        grants=(await db.scalars(select(ClientUserAccess).where(ClientUserAccess.user_id==sec.actors['manager'].id))).all()
        assert grants and not any(g.is_active for g in grants)


async def test_concurrent_access_delete_and_accept_preserves_revocation(sec):
    invitation=await invite(sec)
    async with sec.sessions() as db:
        key=await db.scalar(select(ClientUserAccess.id).where(ClientUserAccess.user_id==sec.actors['manager'].id))
    revoke,accepted=await asyncio.gather(
        sec.http.delete(f'/api/client-portal/access/{key}',headers=auth(sec.owner,sec.org)),
        accept(sec,invitation,email=sec.actors['manager'].email))
    assert revoke.status_code==204,revoke.text
    assert accepted.status_code in {200,403},accepted.text
    assert (await sec.http.get('/api/sites',headers=auth(sec.actors['manager'],sec.org))).status_code==403


async def test_concurrent_owner_deletion_preserves_one_admin(sec):
    async with sec.sessions() as db:
        member=await db.scalar(select(OrganizationMembership).where(OrganizationMembership.user_id==sec.actors['tech2'].id))
        member.role=UserRole.admin;await db.commit()
    results=await asyncio.gather(
        sec.http.delete(f'/api/users/{sec.actors["tech2"].id}',headers=auth(sec.owner,sec.org)),
        sec.http.delete(f'/api/users/{sec.owner.id}',headers=auth(sec.actors['tech2'],sec.org)))
    assert sorted(r.status_code for r in results) in ([204,401],[204,403]),[r.text for r in results]
    async with sec.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(OrganizationMembership).where(
            OrganizationMembership.organization_id==sec.org.id,OrganizationMembership.is_active.is_(True),
            OrganizationMembership.role.in_([UserRole.owner,UserRole.admin])))==1


async def test_admin_cannot_disable_self_via_patch(sec):
    r=await sec.http.patch(f'/api/users/{sec.owner.id}',headers=auth(sec.owner,sec.org),json={'is_active':False})
    assert r.status_code==409,r.text
    assert (await sec.http.get('/api/users/me',headers=auth(sec.owner,sec.org))).status_code==200


async def test_global_account_survives_last_membership_deletion(sec):
    r=await sec.http.delete(f'/api/users/{sec.tech.id}',headers=auth(sec.owner,sec.org));assert r.status_code==204,r.text
    async with sec.sessions() as db:
        assert (await db.get(User,sec.tech.id)).is_active
    assert (await sec.http.get('/api/users/me',headers=auth(sec.tech,sec.org))).status_code==401


@pytest.mark.parametrize('revoked',['client','site'])
async def test_disabled_client_or_site_revokes_existing_scope(sec,revoked):
    from app.models.customer import Client, Site
    async with sec.sessions() as db:
        row=await db.get(Client,sec.client.id) if revoked=='client' else await db.get(Site,sec.sites[0].id)
        row.is_active=False;await db.commit()
    assert (await sec.http.get('/api/sites',headers=auth(sec.actors['manager'],sec.org))).status_code==403


async def test_new_internal_user_still_works_and_returns_membership(sec):
    r=await sec.http.post('/api/users',headers=auth(sec.owner,sec.org),json={
        'email':'new-staff@example.com','full_name':'Новый техник','password':PASSWORD,'role':'technician'})
    assert r.status_code==201,r.text
    assert r.json()['organization_id']==str(sec.org.id) and r.json()['role']=='technician'
    login=await sec.http.post('/api/auth/login',json={'email':'new-staff@example.com','password':PASSWORD})
    assert login.status_code==200,login.text


async def test_canonical_sync_still_completes_and_retries_for_author(sec):
    async with sec.sessions() as db:
        sr=ServiceRequest(organization_id=sec.org.id,number=20,equipment_id=sec.equipment[0].id,
            title='Новый ремонт',status='in_progress',assigned_technician_id=sec.tech.id)
        db.add(sr);await db.commit()
    item=payload(sec,task_id=None,service_request_id=str(sr.id))
    first=await sync(sec,item);assert first['resolved_as']=='applied',first
    again=await sync(sec,item);assert again['resolved_as']=='already_synced',again
    assert (await sync(sec,item,sec.actors['tech2']))['resolved_as']=='failed'
    async with sec.sessions() as db:
        assert (await db.get(ServiceRequest,sr.id)).status=='completed'
        assert await db.scalar(select(func.count()).select_from(Repair).where(Repair.service_request_id==sr.id))==1


async def test_legacy_cannot_bypass_canonical_assignment(sec):
    async with sec.sessions() as db:
        sr=ServiceRequest(organization_id=sec.org.id,number=20,equipment_id=sec.equipment[0].id,
            task_id=sec.task.id,title='Переназначенная',status='in_progress',assigned_technician_id=sec.actors['tech2'].id)
        db.add(sr);await db.commit()
    result=await sync(sec,payload(sec));assert result['resolved_as']=='failed',result


async def test_cross_tenant_stock_reference_is_rejected_before_consumption(sec):
    # Неполный legacy FK не должен позволять списывать чужую запчасть даже при старой некорректной строке stock.
    async with sec.sessions() as db:
        db.add(WarehouseStock(warehouse_id=sec.warehouse.id,part_id=sec.foreign_part.id,quantity=10));await db.commit()
    result=await sync(sec,payload(sec,parts_used=[{'part_id':str(sec.foreign_part.id),'quantity':1}]))
    assert result['resolved_as']=='failed',result
    async with sec.sessions() as db:
        stock=await db.get(WarehouseStock,(sec.warehouse.id,sec.foreign_part.id));assert stock.quantity==10


@pytest.mark.parametrize('index',[1,2,3])
async def test_manager_cannot_move_equipment_or_change_foreign_media(sec,index):
    headers=auth(sec.actors['manager'],sec.org)
    moved=await sec.http.patch(f'/api/equipment/{sec.equipment[0].id}',headers=headers,json={'site_id':str(sec.sites[index].id)})
    assert moved.status_code in {403,422},moved.text
    photo=await sec.http.post(f'/api/equipment/{sec.equipment[index].id}/photo',headers=headers,
        files={'file':('photo.png',png(),'image/png')})
    assert photo.status_code in {403,404},photo.text
    summary=await sec.http.get(f'/api/clients/{sec.sites[index].client_id}/summary',headers=headers)
    if index>1: assert summary.status_code==404,summary.text


async def test_foreign_tenant_media_has_positive_owner_control(sec):
    foreign_headers=auth(sec.actors['foreign_owner'],sec.foreign_org)
    response=await sec.http.post(f'/api/repairs/{sec.repairs[3].id}/attachments',headers=foreign_headers,
        data={'kind':'after','client_id':'foreign-photo'},files={'file':('photo.png',png(),'image/png')})
    assert response.status_code==201,response.text
    photo=response.json()['download_url']
    for path in [photo,f'/api/repairs/{sec.repairs[3].id}/act.pdf',f'/api/equipment/{sec.equipment[3].id}/passport']:
        own=await sec.http.get(path,headers=foreign_headers);assert own.status_code==200,own.text
        for actor in [sec.owner,sec.actors['manager'],sec.actors['director'],sec.actors['tech2']]:
            denied=await sec.http.get(path,headers=auth(actor,sec.org));assert denied.status_code in {403,404},denied.text


async def test_client_reads_own_service_act_and_author_photos(sec):
    uploaded=await upload(sec,sec.repairs[0],sec.tech);assert uploaded.status_code==201,uploaded.text
    for actor in [sec.actors['manager'],sec.actors['director']]:
        for path in [uploaded.json()['download_url'],f'/api/repairs/{sec.repairs[0].id}/act.pdf',f'/api/equipment/{sec.equipment[0].id}/passport']:
            r=await sec.http.get(path,headers=auth(actor,sec.org));assert r.status_code==200,r.text


async def test_site_reassignment_does_not_allow_old_pending_invite_to_restore_scope(sec):
    invitation=await invite(sec)
    async with sec.sessions() as db:
        key=await db.scalar(select(ClientUserAccess.id).where(ClientUserAccess.user_id==sec.actors['manager'].id))
    r=await sec.http.patch(f'/api/client-portal/access/{key}',headers=auth(sec.owner,sec.org),json={'site_id':str(sec.sites[1].id)})
    assert r.status_code==200,r.text
    r=await accept(sec,invitation,email=sec.actors['manager'].email)
    assert r.status_code==403,r.text


async def test_manager_client_counts_respect_site_scope(sec):
    r=await sec.http.get('/api/clients',headers=auth(sec.actors['manager'],sec.org));assert r.status_code==200,r.text
    assert len(r.json())==1
    assert r.json()[0]['site_count']==1 and r.json()[0]['equipment_count']==1,r.text
