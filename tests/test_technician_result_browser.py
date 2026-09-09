"""P0.4: настоящий Pulse/IndexedDB → HTTP → PG → PDF/клиент."""
import os
from io import BytesIO
from pathlib import Path

import pytest
from test_onboarding_postgres import pg, auth, PASSWORD
from test_onboarding_browser import live
from test_request_workflow_postgres import flow, qr, start, new_request, sync, repair_body
from test_technician_result_postgres import result_flow, photo_bytes, DIAGNOSTIC, WORK, DESCRIPTION, upload_result

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(os.getenv('FIXIT_RUN_BROWSER') != '1',
    reason='Браузерная приёмка не запускалась: FIXIT_RUN_BROWSER=1 не задан')]


async def login(browser, email):
    page = await browser.new_page(viewport={'width': 390, 'height': 844})
    await page.goto('http://127.0.0.1:8765/')
    await page.locator('#login-email').fill(email)
    await page.locator('#login-password').fill(PASSWORD)
    await page.locator('#login-form button').click()
    await page.locator('#onboarding-continue').click(timeout=15000)
    return page


async def test_technician_sees_original_guest_photo(live, result_flow):
    from playwright.async_api import async_playwright, expect
    f = result_flow
    response = await qr(f); request_id = response.json()['service_request_id']
    url = f'/api/public/equipment/{f.equipment[0].public_qr_token}/requests/{request_id}/attachments'
    uploaded = await f.http.post(url, data={'client_id': 'original'}, files={'file': ('problem.png', photo_bytes(), 'image/png')})
    assert uploaded.status_code == 201, uploaded.text
    await start(f, request_id)
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await login(browser, f.tech.email)
            await page.goto(f'http://127.0.0.1:8765/#requests/{request_id}')
            await expect(page.locator('[data-request-photo]')).to_have_count(1)
            await page.wait_for_function("document.querySelector('[data-request-photo] img')?.naturalWidth > 0")
            await page.locator('[data-request-photo]').click()
            await expect(page.locator('.image-lightbox')).to_be_visible()
        finally:
            await browser.close()


@pytest.mark.parametrize('conflict', [False, True])
async def test_client_opens_passport_and_complete_result(live, result_flow, conflict):
    from playwright.async_api import async_playwright, expect
    f = result_flow
    request_id = await new_request(f); await start(f, request_id)
    result = await sync(f, repair_body(f, request_id, description=DESCRIPTION, base_equipment_version=f.equipment[0].version - int(conflict)))
    assert result['resolved_as'] == ('applied_with_conflict' if conflict else 'applied'), result
    await upload_result(f, result['server_id'])
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await login(browser, 'manager@example.com')
            await page.goto('http://127.0.0.1:8765/#equipment')
            await page.locator(f'[data-client-equipment="{f.equipment[0].id}"]').click()
            await expect(page.locator('.equipment-passport')).to_be_visible()
            await expect(page.locator('#passport-manage')).to_have_count(0)
            await page.locator('[data-passport-tab="history"]').click()
            await expect(page.locator('.equipment-history-card')).to_have_count(1)
            await page.locator('[data-history-request]').click()
            await expect(page.locator('.request-result')).to_contain_text(WORK)
            if conflict:
                await expect(page.locator('.request-result')).to_contain_text('Требуется проверка состояния оборудования')
            await page.wait_for_function("document.querySelector('[data-result-photo] img')?.naturalWidth > 0")
            async with page.expect_download() as download:
                await page.locator('[data-result-act]').click()
            assert (await download.value).suggested_filename.endswith('.pdf')
        finally:
            await browser.close()


async def test_pulse_long_diagnosis_parts_photo_completion_and_reload(live, result_flow):
    from playwright.async_api import async_playwright, expect
    from pypdf import PdfReader
    f = result_flow
    request_id = await new_request(f)
    assigned = await f.http.patch(f'/api/service-requests/{request_id}/assign', headers=auth(f.owner, f.org),
        params={'technician_id': str(f.tech.id)})
    assert assigned.status_code == 200, assigned.text
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await login(browser, f.tech.email)
            await page.goto(f'http://127.0.0.1:8765/#requests/{request_id}')
            await page.locator('#request-next').click()
            await expect(page.locator('#request-next')).to_have_attribute('data-status', 'in_progress')
            await page.locator('#request-next').click()
            await page.locator('#request-diagnostic').fill(DIAGNOSTIC)
            await page.locator('#request-work').fill(WORK)
            await page.locator(f'[data-part-plus="{f.part.id}"]').click()
            await page.locator('#request-gallery').set_input_files({'name': 'result.png', 'mimeType': 'image/png', 'buffer': photo_bytes()})
            await expect(page.locator('.tech-request-photo-count')).to_contain_text('Выбрано 1')
            async with page.expect_response(lambda r: r.url.endswith('/api/v1/sync/repairs') and r.request.method == 'POST') as pending:
                await page.locator('#request-complete').click()
            response = await pending.value
            payload = await response.json()
            assert payload['results'][0]['resolved_as'] == 'applied', payload
            await expect(page.locator('.request-result')).to_contain_text(WORK)
            await page.wait_for_function("document.querySelector('[data-result-photo] img')?.naturalWidth > 0")
            await page.reload()
            await expect(page.locator('.request-result')).to_contain_text(DIAGNOSTIC.strip())
            await expect(page.locator('.request-result')).to_contain_text('Клапан')
            await expect(page.locator('#request-complete')).to_have_count(0)
            repair_id = payload['results'][0]['server_id']
            act = await f.http.get(f'/api/repairs/{repair_id}/act.pdf', headers=f.manager_headers)
            assert act.status_code == 200
            text = '\n'.join(page.extract_text() for page in PdfReader(BytesIO(act.content)).pages)
            assert WORK in text and 'PILOT-VALVE' in text
            detail = await f.http.get(f'/api/client-portal/requests/{request_id}', headers=f.manager_headers)
            assert DIAGNOSTIC.strip() in detail.json()['outcome']
            assert len(detail.json()['attachments']) == 1
            passport = await f.http.get(f'/api/equipment/{f.equipment[0].id}/passport', headers=f.manager_headers)
            assert len(passport.json()['history']) == 1
        except Exception:
            Path('test-results').mkdir(exist_ok=True)
            for context in browser.contexts:
                for page in context.pages:
                    print('P0.4 UI', (await page.locator('body').inner_text())[:4000])
                    await page.screenshot(path='test-results/p04-result.png', full_page=True)
            raise
        finally:
            await browser.close()
