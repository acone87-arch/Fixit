"""P0.3: нажатие согласования в настоящем Pulse → API → PostgreSQL."""
import os
from io import BytesIO
from PIL import Image
from pathlib import Path

import pytest
from app.models.core import Equipment
from app.models.customer import Site
from test_onboarding_postgres import pg, PASSWORD, auth
from test_onboarding_browser import live
from test_request_workflow_postgres import flow, new_request, start, APPROVAL

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(os.getenv('FIXIT_RUN_BROWSER') != '1',
    reason='FIXIT_RUN_BROWSER=1 не задан: браузерная приёмка не выполнялась')]


@pytest.mark.parametrize('target', ['internal', 'client'])
async def test_pulse_approval_payload_and_dispatcher_result(live, flow, target):
    from playwright.async_api import async_playwright, expect
    request_id = await new_request(flow)
    async with flow.sessions() as db:
        equipment = await db.get(Equipment, flow.equipment[0].id)
        equipment.location_details = 'Прачечная, корпус 2, 1 этаж, помещение 14 за техническим коридором'
        site = await db.get(Site, flow.sites[0].id)
        site.address = 'г. Уфа, ул. Кувыкина, 98, корпус эксплуатационно-технического обслуживания, вход со двора'
        await db.commit()
    await start(flow, request_id)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        page = await browser.new_page(viewport={'width': 390, 'height': 844})
        try:
            await page.goto('http://127.0.0.1:8765/')
            await page.locator('#login-email').fill(flow.tech.email)
            await page.locator('#login-password').fill(PASSWORD)
            await page.locator('#login-form button').click()
            await expect(page.locator('#login-screen')).to_be_hidden()
            await page.locator('#onboarding-continue').click(timeout=15000)
            await page.goto(f'http://127.0.0.1:8765/#requests/{request_id}')
            await expect(page.locator('.tech-request-place')).to_contain_text('г. Уфа, ул. Кувыкина, 98')
            await expect(page.locator('.tech-request-place')).to_contain_text('Прачечная, корпус 2, 1 этаж')
            await expect(page.locator('.tech-request-place a')).to_have_text('Маршрут')
            overflow = await page.evaluate("""() => ({
              width: document.documentElement.clientWidth,
              scrollWidth: document.documentElement.scrollWidth,
              offenders: [...document.querySelectorAll('*')]
                .map((element) => ({element, rect: element.getBoundingClientRect()}))
                .filter(({rect}) => rect.right > document.documentElement.clientWidth + 1)
                .slice(0, 12)
                .map(({element, rect}) => ({tag: element.tagName, className: element.className?.toString(), left: rect.left, right: rect.right, text: element.innerText?.slice(0, 70)}))
            })""")
            assert overflow['scrollWidth'] <= overflow['width'], str(overflow)
            await expect(page.locator('.tech-request-section').nth(0)).to_contain_text('Оборудование')
            # The workplace block must remain useful for every optional address/location combination.
            for address, location, expect_route in [
                ('г. Уфа, ул. Кувыкина, 98', None, True),
                (None, 'Складской корпус, дальняя зона, уровень 2', False),
                (None, None, False),
            ]:
                async with flow.sessions() as db:
                    equipment = await db.get(Equipment, flow.equipment[0].id)
                    equipment.location_details = location
                    site = await db.get(Site, flow.sites[0].id)
                    site.address = address
                    await db.commit()
                await page.reload()
                place = page.locator('.tech-request-place')
                if address:
                    await expect(place).to_contain_text(address)
                else:
                    await expect(place.locator('a[href^="https://maps.google.com/"]')).to_have_count(0)
                if location:
                    await expect(place).to_contain_text(location)
                else:
                    await expect(place.locator('.location-details')).to_have_count(0)
                await expect(place.locator('a[href^="https://maps.google.com/"]')).to_have_count(1 if expect_route else 0)
            await page.locator('#request-diagnostic').fill(APPROVAL['diagnostic'])
            await page.locator('#request-work').fill(APPROVAL['work'])
            await page.locator('#request-comment').fill(APPROVAL['comment'])
            await page.locator('#request-approval-target').select_option(target)
            if target == 'client':
                image = BytesIO(); Image.new('RGB', (4, 4), color='red').save(image, format='PNG')
                await page.locator('#request-gallery').set_input_files({'name': 'diagnostic.png', 'mimeType': 'image/png', 'buffer': image.getvalue()})
                await expect(page.locator('.tech-request-photo-count')).to_contain_text('Выбрано 1')
                await expect(page.locator('#request-approval-target')).to_have_value('client')
                await page.reload()
                await expect(page.locator('#request-approval-target')).to_have_value('client')
            async with page.expect_response(lambda r: r.url.endswith(f'/{request_id}/status') and r.request.method == 'PATCH') as result:
                await page.locator('#request-wait-approval').click()
            response = await result.value
            assert response.status == 200, await response.text()
            assert response.request.post_data_json['details']['approval_target'] == target
            await expect(page.locator('.tech-request-state-banner')).to_contain_text('Ожидается согласование')
            detail = await flow.http.get(f'/api/service-requests/{request_id}', headers=auth(flow.owner, flow.org))
            event = next(e for e in detail.json()['history'] if e['type'] == 'request.waiting_approval')
            assert event['details']['approval']['diagnostic'] == APPROVAL['diagnostic']
            assert event['details']['approval']['work'] == APPROVAL['work']
            if target == 'internal':
                owner_page = await browser.new_page()
                await owner_page.goto('http://127.0.0.1:8765/')
                await owner_page.locator('#login-email').fill(flow.owner.email)
                await owner_page.locator('#login-password').fill(PASSWORD)
                await owner_page.locator('#login-form button').click()
                await expect(owner_page.locator('#login-screen')).to_be_hidden()
                await owner_page.locator('#onboarding-continue').click(timeout=15000)
                await owner_page.goto(f'http://127.0.0.1:8765/#requests/{request_id}')
                await expect(owner_page.locator('.approval-context')).to_contain_text(APPROVAL['work'])
                await owner_page.locator('#approval-approve').click()
                await owner_page.locator('#approval-comment').fill('Согласовано сервисом')
                async with owner_page.expect_response(lambda r: r.url.endswith(f'/{request_id}/approval') and r.request.method == 'PATCH') as decision_result:
                    await owner_page.locator('.pulse-dialog button[type=submit]').click()
                decision = await decision_result.value
                assert decision.status == 200, await decision.text()
                await owner_page.close()
            else:
                client_page = await browser.new_page()
                await client_page.goto('http://127.0.0.1:8765/')
                await client_page.locator('#login-email').fill('manager@example.com')
                await client_page.locator('#login-password').fill(PASSWORD)
                await client_page.locator('#login-form button').click()
                await expect(client_page.locator('#login-screen')).to_be_hidden()
                await client_page.locator('#onboarding-continue').click(timeout=15000)
                await client_page.goto(f'http://127.0.0.1:8765/#requests/{request_id}')
                await expect(client_page.locator('.client-approval')).to_contain_text(APPROVAL['diagnostic'])
                await expect(client_page.locator('.client-approval')).to_contain_text(APPROVAL['work'])
                await expect(client_page.locator('.client-approval')).to_contain_text(APPROVAL['comment'])
                await client_page.wait_for_function("document.querySelector('[data-client-approval-photo] img')?.naturalWidth > 0")
                async def accept_dialog(dialog):
                    await dialog.accept('Согласовано')
                client_page.on('dialog', accept_dialog)
                async with client_page.expect_response(lambda r: r.url.endswith(f'/{request_id}/approval') and r.request.method == 'PATCH') as decision_result:
                    await client_page.locator('#client-approve').click()
                decision = await decision_result.value
                assert decision.status == 200, await decision.text()
                await expect(client_page.locator('.client-approval')).to_have_count(0)
                await client_page.close()
            await page.reload()
            await expect(page.locator('#request-complete')).to_be_visible()
            await expect(page.locator('#request-diagnostic')).to_have_value(APPROVAL['diagnostic'])
            await expect(page.locator('#request-work')).to_have_value(APPROVAL['work'])
        except Exception:
            Path('test-results').mkdir(exist_ok=True)
            for ci, context in enumerate(browser.contexts):
                for pi, active_page in enumerate(context.pages):
                    print('Диагностика приёмки', active_page.url, (await active_page.locator('body').inner_text())[:4000])
                    await active_page.screenshot(path=f'test-results/p03-approval-{target}-{ci}-{pi}.png', full_page=True)
            raise
        finally:
            await browser.close()
