"""P0.1: настоящий Chromium → Pulse → HTTP → ORM → изолированный PostgreSQL.

Запускается в pilot-onboarding.yml. Ни API, ни auth, ни service worker не мокируются.
Данные и пароли синтетические; production не используется. Проверка миграций — P0.7.
"""
import asyncio
import os
from pathlib import Path

import pytest
import pytest_asyncio
import uvicorn
from sqlalchemy import func, select

from app.main import app
from app.models.core import User
from app.models.customer import Client
from test_onboarding_postgres import pg, invite, auth, PASSWORD

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(os.getenv('FIXIT_RUN_BROWSER') != '1',
    reason='FIXIT_RUN_BROWSER=1 не задан: браузерная приёмка не выполнялась')]


@pytest_asyncio.fixture
async def live(pg):
    server = uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=8765,log_level='warning',lifespan='off'))
    task = asyncio.create_task(server.serve())
    try:
        for _ in range(100):
            if server.started: break
            if task.done(): await task
            await asyncio.sleep(0.05)
        assert server.started, 'Тестовый API не запустился'
        yield pg
    finally:
        server.should_exit=True
        await asyncio.wait_for(task,timeout=10)


async def join(page, invitation, email, password=PASSWORD):
    await page.goto(invitation['join_url'])
    await page.locator('#join-name').fill('Менеджер приёмки')
    await page.locator('#join-email').fill(email)
    await page.locator('#join-password').fill(password)
    await page.locator('#join-form').get_by_role('button', name='Продолжить', exact=True).click()


@pytest.mark.parametrize('mobile', [False, True], ids=['desktop', 'mobile-viewport'])
async def test_site_manager_first_equipment_in_browser(live, mobile):
    from playwright.async_api import async_playwright, expect
    invitation = await invite(live)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        context = await browser.new_context(viewport={'width':390,'height':844} if mobile else {'width':1280,'height':900},
                                            is_mobile=mobile,has_touch=mobile)
        page = await context.new_page()
        try:
            await join(page,invitation,'browser-manager@example.com')
            await page.locator('#onboarding-continue').click(timeout=15000)
            await page.locator('#join-welcome-primary').click()
            await expect(page.locator('#f-type')).to_contain_text('Поломойка')
            await expect(page.locator('#f-type')).not_to_contain_text('Новый тип')
            await expect(page.locator('#f-site option')).to_have_count(1)
            await expect(page.locator('#f-site')).to_have_value(str(live.sites[0].id))
            serial = 'BROWSER-MOBILE' if mobile else 'BROWSER-DESKTOP'
            await page.locator('#f-serial').fill(serial)
            await page.locator('#f-manufacturer').fill('Тестовый производитель')
            await page.locator('#f-model').fill('PILOT')
            async with page.expect_response(lambda r: r.url.endswith('/api/equipment') and r.request.method=='POST') as result:
                await page.locator('#modal-save').click()
            response = await result.value
            assert response.status==201, await response.text()
            equipment_id = (await response.json())['id']
            await expect(page.locator('.modal')).to_contain_text(serial)
            # JWT берётся из проверенного browser login; REST-проверки продолжают ту же сессию.
            token = await page.evaluate("localStorage.getItem('token')")
            headers={'Authorization':'Bearer '+token}
            for site in live.sites[1:]:
                denied = await live.http.post('/api/equipment',headers=headers,json={
                    'equipment_type_id':live.kind.id,'site_id':str(site.id),'serial_number':'DENIED'})
                assert denied.status_code in {403,422}
            assigned = await live.http.put(f'/api/clients/{live.client.id}/technicians',headers=auth(live.owner,live.org),
                json={'technician_ids':[str(live.tech.id)]})
            assert assigned.status_code==200,assigned.text
            fleet = await live.http.get('/api/equipment',headers=auth(live.tech,live.org))
            assert fleet.status_code==200 and equipment_id in {item['id'] for item in fleet.json()}
        except Exception:
            Path('test-results').mkdir(exist_ok=True)
            await page.screenshot(path=f'test-results/manager-{mobile}.png',full_page=True)
            raise
        finally:
            await context.close(); await browser.close()


async def test_existing_user_director_joins_existing_client_in_browser(live):
    from playwright.async_api import async_playwright, expect
    invitation=await invite(live,'director')
    async with async_playwright() as playwright:
        browser=await playwright.chromium.launch()
        page=await browser.new_page()
        try:
            await join(page,invitation,live.existing.email,password='incorrect-password')
            await expect(page.locator('#login-error')).to_contain_text('Неверный пароль')
            await page.locator('#join-password').fill(PASSWORD)
            await page.locator('#join-form').get_by_role('button', name='Продолжить', exact=True).click()
            await page.locator('#onboarding-continue').click(timeout=15000)
            await page.locator('#join-welcome-primary').click()
            await expect(page.locator('#client-detail-panel')).to_contain_text('Другой Site')
            await expect(page.locator('#client-detail-panel')).not_to_contain_text('Другой Client')
            async with live.sessions() as db:
                assert await db.scalar(select(func.count()).select_from(Client))==3
                assert await db.scalar(select(func.count()).select_from(User).where(User.email==live.existing.email))==1
                assert (await db.get(Client,live.client.id)).adoption_status=='active'
        except Exception:
            Path('test-results').mkdir(exist_ok=True)
            await page.screenshot(path='test-results/director.png',full_page=True)
            raise
        finally:
            await browser.close()
