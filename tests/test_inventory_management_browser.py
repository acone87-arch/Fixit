"""Actual QR selection and A4 PDF preview in desktop and mobile Chromium."""
import os
from io import BytesIO

import pytest
from pypdf import PdfReader

from test_onboarding_browser import live
from test_inventory_browser import signed_page
from test_inventory_postgres import batch, complete

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(os.getenv('FIXIT_RUN_BROWSER') != '1',
    reason='FIXIT_RUN_BROWSER=1 required')]


@pytest.mark.parametrize('mobile', [False, True], ids=['desktop-dark', 'mobile-light'])
async def test_select_free_labels_preview_download_and_filter_reset(live, mobile, tmp_path):
    from playwright.async_api import async_playwright, expect
    f = live
    _, _, labels = await batch(f, 12)
    assert (await complete(f, labels[0])).status_code == 200
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(executable_path=os.getenv('FIXIT_CHROMIUM_PATH') or None)
        context, page = await signed_page(browser, f, f.owner, mobile)
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        try:
            await page.goto('http://127.0.0.1:8765/#labels')
            await page.locator('#labels-select-free').wait_for()
            await page.evaluate('(theme) => applyAppearance(theme, "large")', 'light' if mobile else 'dark')
            await page.locator('#labels-select-free').click()
            await expect(page.locator('#labels-selected-count')).to_have_text('Выбрано: 11 · Листов A4: 2')
            choices = page.locator('[data-label-select]')
            await expect(choices).to_have_count(11)
            excluded = await choices.first.get_attribute('data-label-select')
            await choices.first.uncheck()
            await expect(page.locator('#labels-selected-count')).to_have_text('Выбрано: 10 · Листов A4: 2')
            await page.locator('#labels-preview').click()
            await expect(page.locator('#qr-print-start')).to_be_enabled(timeout=15000)
            await expect(page.locator('#qr-preview-canvas')).to_be_visible()
            await expect(page.locator('#qr-page-number')).to_have_text('Лист 1 из 2')
            await page.locator('#qr-page-next').click()
            await expect(page.locator('#qr-page-number')).to_have_text('Лист 2 из 2')
            await expect(page.locator('#qr-page-next')).to_be_disabled()
            assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            await page.screenshot(path=str(tmp_path / 'qr-preview.png'), full_page=True)
            async with page.expect_download() as event:
                await page.locator('#qr-print-download').click()
            saved = tmp_path / 'selected.pdf'
            await (await event.value).save_as(saved)
            pdf = PdfReader(BytesIO(saved.read_bytes()))
            assert len(pdf.pages) == 2
            tokens = [a.get_object()['/A']['/URI'].rsplit('/', 1)[-1]
                      for sheet in pdf.pages for a in sheet['/Annots']]
            assert len(tokens) == 10 and len(set(tokens)) == 10
            assert labels[0]['token'] not in tokens and excluded not in tokens
            await page.locator('#qr-print-close').click()
            await page.locator('#labels-site').select_option(str(f.sites[1].id))
            await expect(page.locator('#labels-selected-count')).to_have_text('Выбрано: 0 · Листов A4: 0')
            await expect(page.locator('#labels-preview')).to_be_disabled()
            assert not errors, errors
        finally:
            await context.close()
            await browser.close()
