"""P0.3: нажатие согласования в настоящем Pulse → API → PostgreSQL."""
import os
from pathlib import Path

import pytest
from test_onboarding_postgres import pg, PASSWORD, auth
from test_onboarding_browser import live
from test_request_workflow_postgres import flow, new_request, start, APPROVAL

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(os.getenv('FIXIT_RUN_BROWSER') != '1',
    reason='FIXIT_RUN_BROWSER=1 не задан: браузерная приёмка не выполнялась')]


async def test_pulse_approval_payload_and_dispatcher_result(live, flow):
    from playwright.async_api import async_playwright, expect
    request_id = await new_request(flow)
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
            await page.locator('#request-diagnostic').fill(APPROVAL['diagnostic'])
            await page.locator('#request-work').fill(APPROVAL['work'])
            await page.locator('#request-comment').fill(APPROVAL['comment'])
            async with page.expect_response(lambda r: r.url.endswith(f'/{request_id}/status') and r.request.method == 'PATCH') as result:
                await page.locator('#request-wait-approval').click()
            response = await result.value
            assert response.status == 200, await response.text()
            assert response.request.post_data_json['details']['approval_target'] == 'internal'
            await expect(page.locator('.tech-request-state-banner')).to_contain_text('Ожидается согласование')
            detail = await flow.http.get(f'/api/service-requests/{request_id}', headers=auth(flow.owner, flow.org))
            event = next(e for e in detail.json()['history'] if e['type'] == 'request.waiting_approval')
            assert event['details']['approval']['diagnostic'] == APPROVAL['diagnostic']
            assert event['details']['approval']['work'] == APPROVAL['work']
            decision = await flow.http.patch(f'/api/service-requests/{request_id}/approval',
                headers=auth(flow.owner, flow.org), json={'action': 'approved'})
            assert decision.status_code == 200, decision.text
            await page.reload()
            await expect(page.locator('#request-complete')).to_be_visible()
            await expect(page.locator('#request-diagnostic')).to_have_value(APPROVAL['diagnostic'])
            await expect(page.locator('#request-work')).to_have_value(APPROVAL['work'])
        except Exception:
            Path('test-results').mkdir(exist_ok=True)
            await page.screenshot(path='test-results/p03-approval.png', full_page=True)
            raise
        finally:
            await browser.close()
