"""Real Chromium IDB → HTTP → isolated PostgreSQL; lost responses after commit."""
import base64
import os
import uuid

import pytest
from sqlalchemy import func, select
from app.models.repair import Repair, RepairAttachment
from test_onboarding_postgres import pg, auth
from test_onboarding_browser import live
from test_request_workflow_postgres import flow, new_request, start, repair_body
from test_technician_result_postgres import result_flow, photo_bytes

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(os.getenv('FIXIT_RUN_BROWSER') != '1', reason='FIXIT_RUN_BROWSER=1 required')]


@pytest.mark.parametrize('legacy', [False, True], ids=['blob', 'data-url'])
async def test_offline_restart_lost_repair_and_photo_response(live, result_flow, legacy):
    from playwright.async_api import async_playwright
    f = result_flow
    request_id = await new_request(f); await start(f, request_id)
    payload = repair_body(f, request_id)
    token = auth(f.tech, f.org)['Authorization'].removeprefix('Bearer ')
    data_url = 'data:image/png;base64,' + base64.b64encode(photo_bytes()).decode()
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context(service_workers='block')
        page = await context.new_page()
        try:
            await page.goto('http://127.0.0.1:8765/')
            await page.evaluate('(token) => FixitOffline.configure({token})', token)
            await context.set_offline(True)
            await page.evaluate('''async ({payload, data_url, legacy}) => {
                const photo = legacy ? {data_url} : {file: await (await fetch(data_url)).blob()};
                await FixitOffline.enqueueRepair(payload, [photo]);
            }''', dict(payload=payload, data_url=data_url, legacy=legacy))
            await page.close()
            await context.set_offline(False)
            page = await context.new_page(); await page.goto('http://127.0.0.1:8765/')
            # Use genuine server responses, lose them only after the server committed.
            await page.evaluate('''() => {
                const original = window.fetch; let repair = true, photo = true;
                window.fetch = async (...args) => {
                    const response = await original(...args);
                    if (String(args[0]).endsWith('/sync/repairs') && repair) {repair=false;throw new Error('Lost repair response');}
                    if (String(args[0]).includes('/attachments') && photo) {photo=false;throw new Error('Lost photo response');}
                    return response;
                };
            }''')
            await page.evaluate('() => FixitOffline.sync()')
            assert (await page.evaluate('() => FixitOffline.queueStatus()'))['repairPending']
            await page.evaluate('() => FixitOffline.sync()')
            status = await page.evaluate('() => FixitOffline.queueStatus()')
            assert not status['repairPending'] and status['attachmentsPending'] == 1
            await page.reload()
            await page.evaluate('() => FixitOffline.sync()')
            assert (await page.evaluate('() => FixitOffline.queueStatus()'))['fullySynced']
            async with f.sessions() as db:
                assert await db.scalar(select(func.count()).select_from(Repair).where(Repair.local_uuid == uuid.UUID(payload['local_uuid']))) == 1
                assert await db.scalar(select(func.count()).select_from(RepairAttachment)) == 1
        finally:
            await browser.close()
