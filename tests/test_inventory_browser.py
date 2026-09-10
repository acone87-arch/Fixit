"""Mobile primary inventory and admin editing using actual Pulse UI, HTTP and PG."""
import os
import uuid

import pytest
from sqlalchemy import select

from app.models.core import Equipment
from test_onboarding_postgres import pg, auth
from test_onboarding_browser import live
from test_inventory_postgres import batch, complete

pytestmark = [pytest.mark.asyncio,pytest.mark.skipif(os.getenv('FIXIT_RUN_BROWSER')!='1',reason='FIXIT_RUN_BROWSER=1 required')]


async def signed_page(browser, f, user, mobile=False):
    context=await browser.new_context(viewport={'width':390,'height':844} if mobile else {'width':1280,'height':900},
        service_workers='block',is_mobile=mobile,has_touch=mobile)
    token=auth(user,f.org)['Authorization'].removeprefix('Bearer ')
    await context.add_init_script('localStorage.setItem("token", '+__import__('json').dumps(token)+');localStorage.setItem("fixit-install-dismissed","1");')
    return context, await context.new_page()


async def test_new_site_batch_pdf_mobile_scan_fill_retry_and_next(live, tmp_path):
    from playwright.async_api import async_playwright, expect
    f=live
    await f.http.put(f'/api/clients/{f.client.id}/technicians',headers=auth(f.owner,f.org),json={'technician_ids':[str(f.tech.id)]})
    async with async_playwright() as p:
        browser=await p.chromium.launch(executable_path=os.getenv('FIXIT_CHROMIUM_PATH') or None)
        owner_context,page=await signed_page(browser,f,f.owner)
        try:
            await page.goto('http://127.0.0.1:8765/#equipment')
            await page.locator('#inventory-batches-btn').wait_for()
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
                await mobile.locator('#inventory-type').select_option(str(f.kind.id))
                await mobile.locator('#inventory-maker').fill('Мобильный производитель')
                await mobile.locator('#inventory-model').fill('Модель с телефона')
                await mobile.locator('#inventory-serial').fill('MOBILE-INVENTORY')
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
            await page.locator('#passport-more').click()
            await page.locator('#passport-manage').click()
            await page.locator('#inventory-maker').fill('Изменённый производитель')
            await page.locator('#inventory-model').fill('Исправленная модель')
            await page.locator('#inventory-serial').fill('EDITED-SERIAL')
            await page.locator('#inventory-location').fill('Второй этаж')
            await page.locator('#inventory-edit-site').select_option(str(f.sites[1].id))
            await page.locator('#inventory-status').select_option('mothballed')
            await page.locator('#inventory-save').click()
            await expect(page.locator('#passport-more')).to_be_visible()
            async with f.sessions() as db:
                saved=await db.get(Equipment,uuid.UUID(row['id']))
                assert saved.public_qr_token==uuid.UUID(row['public_qr_token'])
                assert saved.manufacturer=='Изменённый производитель' and saved.model=='Исправленная модель'
                assert saved.serial_number=='EDITED-SERIAL' and saved.location=='Второй этаж'
                assert saved.site_id==f.sites[1].id and saved.status.value=='mothballed'
        finally:
            await context.close(); await browser.close()
