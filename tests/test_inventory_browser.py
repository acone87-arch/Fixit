"""Mobile primary inventory and admin editing using actual Pulse UI, HTTP and PG."""
import os
import uuid

import pytest
from sqlalchemy import select

from app.models.core import Equipment
from test_onboarding_postgres import pg, auth, invite, accept
from test_onboarding_browser import live
from test_inventory_postgres import batch, complete

pytestmark = [pytest.mark.asyncio,pytest.mark.skipif(os.getenv('FIXIT_RUN_BROWSER')!='1',reason='FIXIT_RUN_BROWSER=1 required')]


async def signed_page(browser, f, user, mobile=False):
    context=await browser.new_context(viewport={'width':390,'height':844} if mobile else {'width':1280,'height':900},
        service_workers='block',is_mobile=mobile,has_touch=mobile)
    authorization = user['Authorization'] if isinstance(user, dict) else auth(user,f.org)['Authorization']
    token=authorization.removeprefix('Bearer ')
    await context.add_init_script('localStorage.setItem("token", '+__import__('json').dumps(token)+');localStorage.setItem("fixit-install-dismissed","1");')
    return context, await context.new_page()


@pytest.mark.parametrize('mobile', [False, True], ids=['desktop', 'mobile-390'])
async def test_reprint_selection_download_and_site_change(live, tmp_path, mobile):
    from io import BytesIO
    from pypdf import PdfReader
    from playwright.async_api import async_playwright, expect
    f = live
    _, _, rows = await batch(f, 2)
    for row in rows:
        assert (await complete(f, row)).status_code == 200
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=os.getenv('FIXIT_CHROMIUM_PATH') or None)
        context, page = await signed_page(browser, f, f.owner, mobile)
        try:
            await page.goto('http://127.0.0.1:8765/#equipment')
            await page.locator('#equipment-qr-reprint').click()
            await page.locator('#qr-reprint-site').select_option(str(f.sites[0].id))
            choices = page.locator('#qr-reprint-list input[data-equipment-id]')
            await expect(choices).to_have_count(2)
            download = page.locator('#qr-reprint-download')
            await expect(download).to_be_disabled()
            await choices.first.check()
            await expect(page.locator('#qr-reprint-count')).to_have_text('Выбрано: 1')
            async with page.expect_download() as event:
                await download.click()
            saved = tmp_path / 'reprint.pdf'
            await (await event.value).save_as(saved)
            reader = PdfReader(BytesIO(saved.read_bytes()))
            urls = [a.get_object()['/A']['/URI'] for page_ in reader.pages for a in page_['/Annots']]
            assert len(urls) == 1
            await page.locator('#qr-reprint-all').check()
            await expect(page.locator('#qr-reprint-count')).to_have_text('Выбрано: 2')
            await choices.first.uncheck()
            await expect(page.locator('#qr-reprint-count')).to_have_text('Выбрано: 1')
            await page.locator('#qr-reprint-site').select_option(str(f.sites[1].id))
            await expect(page.locator('#qr-reprint-list')).to_contain_text('На этом объекте оборудования нет')
            await expect(download).to_be_disabled()
            assert await page.evaluate('document.documentElement.scrollWidth <= document.documentElement.clientWidth')
            await page.locator('#qr-reprint-close').click()
            await page.goto(f'http://127.0.0.1:8765/#clients/{f.client.id}/sites/{f.sites[0].id}')
            await page.locator('#site-qr-reprint').click()
            await expect(page.locator('#qr-reprint-site')).to_have_value(str(f.sites[0].id))
            await expect(page.locator('#qr-reprint-list input[data-equipment-id]')).to_have_count(2)
        finally:
            await context.close(); await browser.close()


async def test_new_site_batch_pdf_mobile_scan_fill_retry_and_next(live, tmp_path, monkeypatch):
    from playwright.async_api import async_playwright, expect
    f=live
    from app.routers import equipment as equipment_router
    from test_technician_result_postgres import photo_bytes
    monkeypatch.setattr(equipment_router, 'UPLOAD_ROOT', tmp_path/'uploads')
    await f.http.put(f'/api/clients/{f.client.id}/technicians',headers=auth(f.owner,f.org),json={'technician_ids':[str(f.tech.id)]})
    async with async_playwright() as p:
        browser=await p.chromium.launch(executable_path=os.getenv('FIXIT_CHROMIUM_PATH') or None)
        owner_context,page=await signed_page(browser,f,f.owner)
        try:
            await page.goto('http://127.0.0.1:8765/#equipment')
            await page.locator('#inventory-batches-btn').wait_for()
            await expect(page.locator('#inventory-batches-btn')).to_have_text('Создать партию оборудования и QR')
            await page.evaluate('(client) => openCreateSiteModal(client)',str(f.client.id))
            await page.locator('#f-site-name').fill('Новый объект для инвентаризации')
            await page.locator('#modal-save').click()
            await page.locator('#inventory-count').fill('2')
            await page.locator('#inventory-generate').click()
            download_button=page.locator('[data-inventory-pdf]').first
            await download_button.wait_for()
            async with page.expect_download() as event:
                await download_button.click()
            download=await event.value
            await download.save_as(tmp_path/'labels.pdf')
            assert (tmp_path/'labels.pdf').read_bytes().startswith(b'%PDF')
            async with f.sessions() as db:
                rows=(await db.scalars(select(Equipment).where(Equipment.inventory_pending.is_(True)).order_by(Equipment.inventory_number))).all()
            assert len(rows)==2
            tech_context,mobile=await signed_page(browser,f,f.tech,True)
            try:
                await mobile.goto(f'http://127.0.0.1:8765/e/{rows[0].public_qr_token}')
                await expect(mobile.locator('#inventory-type')).to_be_visible()
                assert await mobile.evaluate('document.documentElement.scrollWidth <= document.documentElement.clientWidth')
                await mobile.locator('#inventory-type').select_option(str(f.kind.id))
                await mobile.locator('#inventory-maker').fill('Мобильный производитель')
                await mobile.locator('#inventory-model').fill('Модель с телефона')
                await mobile.locator('#inventory-serial').fill('MOBILE-INVENTORY')
                await mobile.locator('#inventory-photo').set_input_files({'name':'machine.png','mimeType':'image/png','buffer':photo_bytes()})
                await mobile.evaluate('''() => { const original=window.fetch;let lost=false;window.fetch=async (...args)=>{const response=await original(...args);if(String(args[0]).endsWith('/complete')&&!lost){lost=true;throw new Error('Lost response after commit');}return response;}; }''')
                await mobile.locator('#inventory-save').click()
                await expect(mobile.locator('#inventory-error')).to_contain_text('Lost response')
                await mobile.locator('#inventory-save').click()
                await expect(mobile.locator('#inventory-next')).to_be_visible()
                await mobile.locator('#inventory-next').click()
                await mobile.locator('#admin-qr-manual').fill(f'http://127.0.0.1:8765/e/{rows[1].public_qr_token}')
                await mobile.locator('#admin-qr-open').click()
                await expect(mobile.locator('#inventory-serial')).to_have_value('')
                async with f.sessions() as db:
                    saved=await db.get(Equipment,rows[0].id)
                    assert not saved.inventory_pending and saved.public_qr_token==rows[0].public_qr_token
                    assert saved.serial_number=='MOBILE-INVENTORY'
                passport=await f.http.get(f'/api/equipment/{rows[0].id}/passport',headers=auth(f.owner,f.org))
                assert passport.json()['primary_photo'] is not None
            finally:
                await tech_context.close()
        finally:
            await owner_context.close(); await browser.close()


async def test_admin_edits_all_card_details_without_changing_qr(live):
    from playwright.async_api import async_playwright, expect
    f=live
    _,_,rows=await batch(f,1)
    done=await complete(f,rows[0]); assert done.status_code==200
    row=done.json()
    async with async_playwright() as p:
        browser=await p.chromium.launch(executable_path=os.getenv('FIXIT_CHROMIUM_PATH') or None)
        context,page=await signed_page(browser,f,f.owner,True)
        try:
            await page.goto('http://127.0.0.1:8765/#equipment')
            await page.locator('#inventory-batches-btn').wait_for()
            await page.evaluate('(id)=>openEquipmentPassport(id)',row['id'])
            await expect(page.locator('#passport-manage')).to_have_text('Редактировать карточку')
            await page.locator('#passport-manage').click()
            await page.locator('#inventory-type').select_option('new')
            await page.locator('#inventory-new-type').fill('Подметальная машина')
            await page.locator('#inventory-maker').fill('Изменённый производитель')
            await page.locator('#inventory-model').fill('Исправленная модель')
            await page.locator('#inventory-serial').fill('EDITED-SERIAL')
            await page.locator('#inventory-location').fill('Второй этаж')
            await page.locator('#inventory-location-details').fill('Прачечная, корпус 2, 1 этаж')
            await page.locator('#inventory-edit-site').select_option(str(f.sites[1].id))
            await page.locator('#inventory-status').select_option('mothballed')
            await page.locator('#inventory-save').click()
            await expect(page.locator('#passport-more')).to_be_visible()
            async with f.sessions() as db:
                saved=await db.get(Equipment,uuid.UUID(row['id']))
                assert saved.public_qr_token==uuid.UUID(row['public_qr_token'])
                assert saved.manufacturer=='Изменённый производитель' and saved.model=='Исправленная модель'
                assert saved.serial_number=='EDITED-SERIAL' and saved.location=='Второй этаж'
                assert saved.location_details=='Прачечная, корпус 2, 1 этаж'
                assert saved.equipment_type_id!=f.kind.id and saved.name=='Подметальная машина'
                assert saved.site_id==f.sites[1].id and saved.status.value=='mothballed'
        finally:
            await context.close(); await browser.close()


async def test_site_manager_completes_pending_card_from_mobile_qr(live):
    from playwright.async_api import async_playwright, expect
    f=live
    invitation=await invite(f)
    accepted=await accept(f,invitation,email='inventory-qr-manager@example.com')
    assert accepted.status_code==200,accepted.text
    manager_headers={'Authorization':'Bearer '+accepted.json()['access_token']}
    _,_,rows=await batch(f,1)
    row=rows[0]
    async with async_playwright() as p:
        browser=await p.chromium.launch(executable_path=os.getenv('FIXIT_CHROMIUM_PATH') or None)
        manager_context,page=await signed_page(browser,f,manager_headers,True)
        try:
            await page.goto(f"http://127.0.0.1:8765/e/{row['public_qr_token']}")
            await expect(page.locator('#inventory-type')).to_be_visible()
            await page.locator('#inventory-type').select_option(str(f.kind.id))
            await page.locator('#inventory-serial').fill('SITE-MANAGER-INVENTORY')
            await page.locator('#inventory-location').fill('Комната главного менеджера')
            await page.locator('#inventory-save').click()
            await expect(page.locator('#inventory-next')).to_be_visible()
            async with f.sessions() as db:
                saved=await db.get(Equipment,uuid.UUID(row['id']))
                assert not saved.inventory_pending
                assert saved.serial_number=='SITE-MANAGER-INVENTORY'
                assert saved.public_qr_token==uuid.UUID(row['public_qr_token'])
        finally:
            await manager_context.close(); await browser.close()
