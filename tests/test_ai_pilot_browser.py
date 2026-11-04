"""Settings → AI pilot with real HTTP/PG and synthetic provider only."""
import os
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models.core import UserRole
from app.models.organization import OrganizationMembership
from test_ai_integration_postgres import ai_flow, pg, flow, generate
from test_onboarding_browser import live
from test_onboarding_postgres import auth, PASSWORD
from test_request_workflow_postgres import repair_body, sync

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(os.getenv('FIXIT_RUN_BROWSER') != '1', reason='FIXIT_RUN_BROWSER=1 required')]


async def login(page, person):
    await page.goto('http://127.0.0.1:8765/')
    await page.locator('#login-email').fill(person.email)
    await page.locator('#login-password').fill(PASSWORD)
    await page.locator('#login-form button').click()
    await page.locator('#onboarding-continue').click(timeout=15000)
    await page.goto('http://127.0.0.1:8765/#profile')


@pytest.mark.parametrize('role,width,theme', [(UserRole.owner, 390, 'light'), (UserRole.admin, 1280, 'dark'), (UserRole.dispatcher, 390, 'dark')])
async def test_staff_settings_pilot_and_refresh_failure_recovery(live, ai_flow, role, width, theme):
    from playwright.async_api import async_playwright, expect
    f = ai_flow
    gid = (await generate(f)).json()['generation_id']
    for action in ['applied', 'helpful']:
        response = await f.http.post(f'/api/ai/generations/{gid}/feedback', headers=auth(f.tech, f.org), json={'action': action})
        assert response.status_code == 200
    assert (await sync(f, repair_body(f, f.request_id, ai_generation_id=gid)))['resolved_as'] == 'applied'
    async with f.sessions() as db:
        member = await db.scalar(select(OrganizationMembership).where(
            OrganizationMembership.organization_id == f.org.id, OrganizationMembership.user_id == f.owner.id))
        member.role = role
        await db.commit()
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page(viewport={'width': width, 'height': 900})
            await login(page, f.owner)
            await page.locator('#profile-theme').select_option(theme)
            await page.locator('#profile-ai-pilot').click()
            await expect(page.locator('#ai-pilot-configuration')).to_be_visible()
            await expect(page.locator('.ai-pilot-scope')).to_contain_text(f.org.name)
            await expect(page.locator('#ai-pilot-budget')).to_contain_text('300,00 ₽')
            await expect(page.locator('#ai-pilot-cost')).to_contain_text('0,12 ₽')
            await expect(page.locator('#ai-pilot-cost')).to_contain_text('Баланс и подтверждённые списания Yandex Cloud здесь не показаны')
            await expect(page.locator('.ai-pilot-stats article').nth(1).locator('strong')).to_have_text('1')
            await expect(page.locator('.ai-pilot-stats article').nth(2).locator('strong')).to_have_text('1')
            await expect(page.locator('.ai-pilot-stats article').nth(3).locator('strong')).to_have_text('100%')
            assert await page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            await page.screenshot(path=f'/tmp/fixit-ai-pilot-{role.value}-{width}.png', full_page=True)
            await page.context.set_offline(True)
            await page.get_by_role('button', name='Обновить', exact=True).click()
            await expect(page.locator('.ai-pilot-status')).to_contain_text('Не удалось загрузить')
            await expect(page.locator('#ai-pilot-cost')).to_have_count(0)
            await page.context.set_offline(False)
            await page.get_by_role('button', name='Обновить', exact=True).click()
            await expect(page.locator('#ai-pilot-cost')).to_be_visible()
            await page.reload()
            await expect(page.locator('#ai-pilot-cost')).to_be_visible()
            assert len(f.calls) == 1
            if width < 768:
                await page.locator('[data-mobile-route="more"]').click()
                await page.locator('#more-logout-btn').click()
            else:
                await page.locator('#logout-btn').click()
            await expect(page.locator('#login-screen')).to_be_visible()
            await expect(page.locator('#ai-pilot-cost')).to_have_count(0)
        finally:
            await browser.close()


async def test_technician_cannot_open_pilot_from_profile_or_direct_route(live, ai_flow):
    from playwright.async_api import async_playwright, expect
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page()
            await login(page, ai_flow.tech)
            await expect(page.locator('#profile-theme')).to_be_visible()
            await expect(page.locator('#profile-ai-pilot')).to_have_count(0)
            requests = []
            page.on('request', lambda request: requests.append(request.url))
            await page.goto('http://127.0.0.1:8765/#profile/ai')
            await expect(page.locator('#ai-pilot-screen')).to_contain_text('доступны администратору и диспетчеру')
            assert not any(url.endswith('/api/ai/pilot') for url in requests)
            assert not ai_flow.calls
        finally:
            await browser.close()


async def test_pilot_late_response_cannot_render_after_session_change_or_disposal():
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page()
            await page.set_content('<main id="content"></main>')
            await page.add_script_tag(content=Path('app/static/ai_pilot.js').read_text())
            await page.evaluate('''() => {
              window.session = 'org-a';
              window.cleanup = FixitAIPilot.mount(document.querySelector('#content'), {
                role: 'dispatcher', getSession: () => window.session,
                api: () => new Promise(resolve => {window.finish = resolve;})
              });
              window.session = 'org-b';
              window.finish({organization: {name: 'PRIVATE ORGANIZATION'}});
            }''')
            await page.wait_for_timeout(50)
            assert 'PRIVATE ORGANIZATION' not in await page.locator('body').inner_text()
            await page.evaluate('''() => {
              window.cleanup();
              window.session = 'org-a';
              window.cleanup = FixitAIPilot.mount(document.querySelector('#content'), {
                role: 'admin', getSession: () => window.session,
                api: () => new Promise(resolve => {window.finish = resolve;})
              });
              window.cleanup();
              window.finish({organization: {name: 'PRIVATE ORGANIZATION'}});
            }''')
            await page.wait_for_timeout(50)
            assert 'PRIVATE ORGANIZATION' not in await page.locator('body').inner_text()
        finally:
            await browser.close()


async def test_disabled_empty_pilot_has_no_fabricated_percentage_and_safe_org_name(live, ai_flow, monkeypatch):
    from app.config import settings
    from app.models.organization import Organization
    from playwright.async_api import async_playwright, expect
    f = ai_flow
    monkeypatch.setattr(settings, 'ai_enabled', False)
    name = 'Сервис <img src=x onerror="window.aiInjected=true">'
    async with f.sessions() as db:
        org = await db.get(Organization, f.org.id)
        org.name = name
        await db.commit()
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page(viewport={'width': 390, 'height': 844})
            await login(page, f.owner)
            await page.locator('#profile-ai-pilot').click()
            await expect(page.locator('#ai-pilot-configuration')).to_contain_text('Помощник выключен')
            await expect(page.locator('.ai-pilot-body')).to_contain_text('Запусков оформления результата в этом месяце пока нет')
            await expect(page.locator('.ai-pilot-stats article').nth(3).locator('strong')).to_have_text('—')
            await expect(page.locator('.ai-pilot-scope')).to_contain_text(name)
            await expect(page.locator('.ai-pilot-scope img')).to_have_count(0)
            assert not await page.evaluate('Boolean(window.aiInjected)')
            assert not f.calls
        finally:
            await browser.close()
