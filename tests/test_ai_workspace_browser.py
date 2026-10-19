"""Pulse UI → HTTP → PostgreSQL; paid Yandex provider alone is replaced."""
import asyncio
import os
from pathlib import Path

import pytest

from app.services import ai_provider
from test_ai_integration_postgres import ai_flow, pg, flow
from test_onboarding_browser import live
from test_onboarding_postgres import PASSWORD

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(os.getenv('FIXIT_RUN_BROWSER') != '1', reason='FIXIT_RUN_BROWSER=1 required')]


async def open_request(browser, f, width=390):
    page = await browser.new_page(viewport={'width': width, 'height': 844})
    await page.goto('http://127.0.0.1:8765/')
    await page.locator('#login-email').fill(f.tech.email)
    await page.locator('#login-password').fill(PASSWORD)
    await page.locator('#login-form button').click()
    await page.locator('#onboarding-continue').click(timeout=15000)
    await page.goto(f'http://127.0.0.1:8765/#requests/{f.request_id}')
    await page.locator('#request-ai-format').wait_for()
    return page


async def prepare(page, note='Очистил фильтр.'):
    await page.locator('#request-ai-note').fill(note)
    await page.locator('#request-ai-consent').check()
    await page.locator('#request-ai-format').click()


@pytest.mark.parametrize('width', [390, 1280])
async def test_cancel_apply_reload_and_offline_manual_edit(live, ai_flow, width):
    from playwright.async_api import async_playwright, expect
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await open_request(browser, ai_flow, width)
            await page.locator('#request-work').fill('Исходный ручной текст')
            await prepare(page)
            apply = page.get_by_role('button', name='Применить в форму', exact=True)
            await expect(apply).to_be_visible()
            assert await page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            await page.screenshot(path=f'/tmp/fixit-ai-feedback-preview-{width}.png', full_page=True)
            await expect(page.locator('#request-work')).to_have_value('Исходный ручной текст')
            await page.get_by_role('button', name='Отмена', exact=True).click()
            await expect(page.locator('#request-work')).to_have_value('Исходный ручной текст')
            await page.locator('#request-ai-format').click()
            await apply.click()
            await expect(page.locator('#request-work')).to_have_value('Очистил фильтр.')
            await expect(page.locator('.ai-message')).to_contain_text('Текст применён')
            await page.reload()
            await expect(page.locator('#request-work')).to_have_value('Очистил фильтр.')
            await expect(page.locator('#request-ai-note')).to_have_value('Очистил фильтр.')
            await page.context.set_offline(True)
            await expect(page.locator('#request-ai-format')).to_be_disabled()
            await page.locator('#request-comment').fill('Дополнение без сети')
            await page.wait_for_timeout(200)
            await page.context.set_offline(False)
            await page.reload()
            await expect(page.locator('#request-comment')).to_have_value('Дополнение без сети')
            assert await page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            await page.screenshot(path=f'/tmp/fixit-ai-workspace-{width}.png', full_page=True)
        finally:
            await browser.close()


async def test_late_response_cannot_overwrite_manual_changes(live, ai_flow, monkeypatch):
    from playwright.async_api import async_playwright, expect
    entered, release = asyncio.Event(), asyncio.Event()
    async def delayed(note, config):
        entered.set()
        await release.wait()
        return await ai_flow.ai_provider(note, config)
    monkeypatch.setattr(ai_provider, 'generate', delayed)
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await open_request(browser, ai_flow)
            await prepare(page)
            await asyncio.wait_for(entered.wait(), 5)
            await page.locator('#request-work').fill('Новый ручной текст')
            release.set()
            await expect(page.locator('.ai-message')).to_contain_text('Форма изменилась')
            await expect(page.locator('#request-work')).to_have_value('Новый ручной текст')
            await expect(page.get_by_role('button', name='Применить в форму', exact=True)).to_have_count(0)
        finally:
            release.set()
            await browser.close()


async def test_preview_treats_html_as_text(live, ai_flow):
    from playwright.async_api import async_playwright, expect
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await open_request(browser, ai_flow)
            note = '<img src=x onerror="window.aiInjected=true">.'
            await prepare(page, note)
            await expect(page.get_by_role('button', name='Применить в форму', exact=True)).to_be_visible()
            await expect(page.locator('.ai-output')).to_contain_text(note)
            await expect(page.locator('.ai-output img')).to_have_count(0)
            assert not await page.evaluate('Boolean(window.aiInjected)')
        finally:
            await browser.close()


async def test_widget_uses_host_uuid_fallback_without_native_random_uuid():
    from playwright.async_api import async_playwright, expect
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page()
            await page.set_content('<section id="helper"></section>')
            await page.add_script_tag(content=Path('app/static/ai.js').read_text())
            await page.evaluate('''() => {
              Object.defineProperty(window.crypto, 'randomUUID', {value: undefined});
              window.uuidCalls = 0;
              window.FixitAIWorkspace.mount(document.querySelector('#helper'), {
                writable: true, note: 'Очистил фильтр.', requestId: 'demo', equipmentId: 'demo',
                uuid: () => { window.uuidCalls++; return '00000000-0000-4000-8000-000000000001'; },
                getSnapshot: () => ({work: ''}), onNote: () => {},
                onApply: async result => { window.accepted = result.work; return true; },
                api: async (path, options) => path.endsWith('capabilities')
                  ? {repair_draft: true, equipment_brief: false}
                  : {diagnostic: '', work: 'Очистил фильтр.', comment: '', questions: [], revision: JSON.parse(options.body).revision}
              });
            }''')
            await page.locator('#request-ai-consent').check()
            await page.locator('#request-ai-format').click()
            await page.get_by_role('button', name='Применить в форму', exact=True).click()
            await expect(page.locator('.ai-message')).to_contain_text('Текст применён')
            assert await page.evaluate('window.accepted') == 'Очистил фильтр.'
            assert await page.evaluate('window.uuidCalls') == 1
        finally:
            await browser.close()


async def test_applied_draft_survives_reload_and_links_only_after_offline_sync(live, ai_flow):
    from sqlalchemy import select
    from app.models.ai import AIGeneration
    from playwright.async_api import async_playwright, expect
    f = ai_flow
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await open_request(browser, f)
            await prepare(page)
            await page.get_by_role('button', name='Полезно', exact=True).click()
            await expect(page.locator('.ai-output')).to_contain_text('Оценка записана')
            await page.get_by_role('button', name='Применить в форму', exact=True).click()
            await expect(page.locator('.ai-message')).to_contain_text('Текст применён')
            async with f.sessions() as db:
                row = await db.scalar(select(AIGeneration))
                gid = row.id
                assert row.rating == 'helpful' and row.applied_at and row.repair_id is None
            await page.reload()
            await expect(page.locator('#request-work')).to_have_value('Очистил фильтр.')
            await page.context.set_offline(True)
            await page.locator('#request-complete').click()
            await expect(page.locator('.tech-request-sync')).to_contain_text('сохранена на устройстве')
            async with f.sessions() as db:
                assert (await db.get(AIGeneration, gid)).repair_id is None
            await page.context.set_offline(False)
            # Trigger the existing queue explicitly; no generation/feedback retry.
            await page.evaluate("window.dispatchEvent(new Event('online'))")
            for _ in range(80):
                async with f.sessions() as db:
                    row = await db.get(AIGeneration, gid)
                    repair_id = row.repair_id
                if repair_id:
                    break
                await asyncio.sleep(.1)
            assert repair_id, 'Canonical sync did not confirm AI provenance'
            assert len(f.calls) == 1
        finally:
            await browser.close()
