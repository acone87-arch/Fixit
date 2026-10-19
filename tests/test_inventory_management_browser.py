"""Chromium exercises actual inventory UI and HTTP routes with in-memory ORM data.

This deliberately does not replace PostgreSQL concurrency acceptance tests.
"""
import json
import os
from pathlib import Path
import re

import httpx
import pytest

from app.core.deps import get_current_user
from app.database import get_db
from app.main import app
from test_inventory_management import inventory_db, make_batch

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(os.getenv('FIXIT_RUN_BROWSER') != '1',
    reason='FIXIT_RUN_BROWSER=1 required')]


def js_function(source, name):
    start = re.search(r'(?:async )?function ' + re.escape(name) + r'\(', source).start()
    following = re.search(r'\n(?:async )?function ', source[start + 1:])
    return source[start:] if not following else source[start:start + 1 + following.start()]


@pytest.mark.parametrize('mobile', [False, True], ids=['desktop-dark', 'mobile-light'])
async def test_select_cancel_delete_and_refresh_equipment(inventory_db, mobile, tmp_path):
    from playwright.async_api import async_playwright, expect
    f = inventory_db
    await make_batch(f, 10)
    _, more = await make_batch(f, 2)
    more[0].inventory_pending = False
    more[0].serial_number = 'FILLED'
    more[0].equipment_type_id = f.kind.id
    f.session.commit()
    previous = app.dependency_overrides.copy()
    async def user():
        return f.user
    async def database():
        yield f.db
    app.dependency_overrides[get_current_user] = user
    app.dependency_overrides[get_db] = database
    state = dict(me={'role': 'admin'}, equipmentTypes=[{'id': f.kind.id, 'name': f.kind.name}],
        sites=[{'id': str(s.id), 'client_id': str(s.client_id), 'name': s.name, 'is_active': True} for s in f.sites],
        clients=[{'id': str(f.sites[0].client_id), 'name': 'Client'}])
    app_js = Path('app/static/app.js').read_text(encoding='utf-8')
    inventory_js = Path('app/static/inventory.js').read_text(encoding='utf-8')
    functions = '\n'.join(js_function(app_js, name) for name in [
        'esc', 'toast', 'openModal', 'closeModal', 'renderEquipment', 'readableClientName'])
    functions += '\n' + js_function(inventory_js, 'openPendingEquipmentDelete')
    script = 'const state = ' + json.dumps(state) + ';\n' + '''
        const EQUIPMENT_STATUS = {}; const badge = () => '<span>Работает</span>';
        const ensureCustomers = async () => {}; const ensureEquipmentTypes = async () => {};
        const stopAdminQrScan = () => {}; const openCreateEquipmentModal = () => {};
        async function api(path, options = {}) {
          const response = await fetch('/api' + path, {...options, headers: {'Content-Type': 'application/json'}});
          if (!response.ok) throw new Error((await response.json()).detail);
          return response.status === 204 ? null : response.json();
        }
    ''' + functions
    errors = []
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://localhost') as http:
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch()
                context = await browser.new_context(viewport={'width': 390, 'height': 844} if mobile else {'width': 1440, 'height': 1000})
                page = await context.new_page()
                page.on('pageerror', lambda error: errors.append(str(error)))
                async def bridge(route):
                    response = await http.request(route.request.method,
                        route.request.url.replace('http://inventory.test', ''),
                        content=route.request.post_data, headers={'Content-Type': 'application/json'})
                    await route.fulfill(status=response.status_code, body=response.content,
                        content_type=response.headers.get('content-type', 'text/plain'))
                await page.route('http://inventory.test/', lambda route: route.fulfill(body='<div id="content"></div><div id="toast-root"></div>', content_type='text/html'))
                await page.route('http://inventory.test/api/**', bridge)
                await page.goto('http://inventory.test/')
                # Remove the optional web-font import to keep the test offline.
                css = Path('app/static/styles.css').read_text(encoding='utf-8').split('\n', 1)[1]
                await page.add_style_tag(content=css)
                await page.evaluate('(theme) => document.documentElement.dataset.theme = theme', 'light' if mobile else 'dark')
                await page.add_script_tag(content=script)
                await page.evaluate('renderEquipment(document.getElementById("content"))')
                if mobile:
                    await page.locator('#equipment-site-trigger').click()
                    await page.locator(f'#equipment-site-menu [data-site-value="{f.sites[0].id}"]').click()
                else:
                    await page.locator('#equipment-location-filter').select_option(str(f.sites[0].id))
                assert await page.locator('#equipment-rows tr strong').all_text_contents() == [
                    *[f'Оборудование №{n}' for n in range(1, 11)], 'Оборудование №12', 'Machine']
                await page.locator('#inventory-delete-pending').click()
                choices = page.locator('#inventory-delete-list input[data-equipment-id]')
                await expect(choices).to_have_count(11)
                submit = page.locator('#inventory-delete-submit')
                await expect(submit).to_be_disabled()
                await page.locator('#inventory-delete-all').check()
                await expect(page.locator('#inventory-delete-count')).to_have_text('Выбрано: 11')
                await page.locator('#inventory-delete-site').select_option(str(f.sites[1].id))
                await expect(choices).to_have_count(0)
                await expect(submit).to_be_disabled()
                await page.locator('#inventory-delete-site').select_option(str(f.sites[0].id))
                await expect(choices).to_have_count(11)
                await choices.first.check()
                page.once('dialog', lambda dialog: dialog.dismiss())
                await submit.click()
                await expect(choices).to_have_count(11)
                # Check the large-card and modal layouts in both supported viewports.
                assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                await page.screenshot(path=str(tmp_path / 'delete-pending.png'), full_page=True)
                page.once('dialog', lambda dialog: dialog.accept())
                await submit.click()
                await expect(page.locator('.modal-backdrop')).to_have_count(0)
                await expect(page.locator('#equipment-rows tr')).to_have_count(11)
                await expect(page.locator('#equipment-location-filter')).to_have_value(str(f.sites[0].id))
                assert not errors, errors
                await context.close()
                await browser.close()
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
