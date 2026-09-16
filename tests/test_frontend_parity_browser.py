"""Frontend parity routes through real Chromium, HTTP handlers and PostgreSQL."""
import os
from datetime import datetime, timezone
from io import BytesIO

import pytest
from PIL import Image

from app.models.service_request import ServiceRequest
from test_onboarding_browser import live
from test_onboarding_postgres import pg, PASSWORD, accept, auth, invite
from test_request_workflow_postgres import flow, new_request, qr

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(
    os.getenv("FIXIT_RUN_BROWSER") != "1",
    reason="FIXIT_RUN_BROWSER=1 не задан: браузерная приёмка не выполнялась",
)]


async def login(page, email):
    await page.goto("http://127.0.0.1:8765/")
    await page.locator("#login-email").fill(email)
    await page.locator("#login-password").fill(PASSWORD)
    await page.locator("#login-form button").click()
    from playwright.async_api import expect
    await expect(page.locator("#login-screen")).to_be_hidden()
    if await page.locator("#onboarding-continue").count():
        await page.locator("#onboarding-continue").click()


async def assert_no_horizontal_scroll(page):
    assert await page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")


async def test_qr_request_assignment_reaches_technician_and_cannot_be_reassigned(live, flow):
    from playwright.async_api import async_playwright, expect
    created = await qr(flow)
    request_id = created.json()["service_request_id"]
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        owner = await browser.new_page(viewport={"width": 390, "height": 844})
        technician = await browser.new_page(viewport={"width": 390, "height": 844})
        try:
            await login(owner, flow.owner.email)
            await owner.goto(f"http://127.0.0.1:8765/#requests/{request_id}")
            await expect(owner.locator("#request-assign-technician")).to_be_visible()
            await owner.locator("#request-assign-technician").click()
            await assert_no_horizontal_scroll(owner)
            await owner.locator("#assignment-technician").select_option(str(flow.tech.id))
            async with owner.expect_response(lambda response: response.url.endswith("/assign?technician_id=" + str(flow.tech.id)) and response.request.method == "PATCH") as result:
                await owner.locator("#assignment-save").click()
            assert (await result.value).status == 200
            await expect(owner.locator(".sr-assignment")).to_contain_text(flow.tech.full_name)
            await expect(owner.locator("#request-assign-technician")).to_have_count(0)

            await login(technician, flow.tech.email)
            await technician.goto("http://127.0.0.1:8765/#requests")
            await expect(technician.locator(f'[data-id="{request_id}"]')).to_be_visible()
            await assert_no_horizontal_scroll(technician)
        finally:
            await browser.close()


async def test_client_filters_search_and_authenticated_problem_photo(live, flow):
    from playwright.async_api import async_playwright, expect
    async with flow.sessions() as db:
        rows = [
            ServiceRequest(organization_id=flow.org.id, number=101, equipment_id=flow.equipment[0].id, title="Активная FP", status="new"),
            ServiceRequest(organization_id=flow.org.id, number=102, equipment_id=flow.equipment[0].id, title="Ждёт клиента FP", status="waiting_approval", approval_target="client"),
            ServiceRequest(organization_id=flow.org.id, number=103, equipment_id=flow.equipment[0].id, title="Ждёт сервис FP", status="waiting_approval", approval_target="internal"),
            ServiceRequest(organization_id=flow.org.id, number=104, equipment_id=flow.equipment[0].id, title="Завершена FP", status="completed", completed_at=datetime.now(timezone.utc)),
        ]
        db.add_all(rows)
        await db.commit()
        waiting_id = str(rows[1].id)
    second = await flow.http.post("/api/equipment", headers=auth(flow.owner, flow.org), json={
        "equipment_type_id": flow.kind.id, "site_id": str(flow.sites[0].id),
        "serial_number": "FP-SEARCH-900", "manufacturer": "SearchCo", "model": "Needle Model",
        "inventory_number": 907,
    })
    assert second.status_code == 201, second.text
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        page = await browser.new_page(viewport={"width": 390, "height": 844})
        try:
            await login(page, "manager@example.com")
            await page.goto("http://127.0.0.1:8765/#requests")
            await page.locator('[data-client-filter="active"]').click()
            await expect(page.locator(".client-request-list")).to_contain_text("Активная FP")
            await expect(page.locator(".client-request-list")).not_to_contain_text("Завершена FP")
            await page.locator('[data-client-filter="approval"]').click()
            await expect(page.locator(".client-request-list")).to_contain_text("Ждёт клиента FP")
            await expect(page.locator(".client-request-list")).not_to_contain_text("Ждёт сервис FP")
            await page.locator('[data-client-filter="completed"]').click()
            await expect(page.locator(".client-request-list")).to_contain_text("Завершена FP")

            await page.goto("http://127.0.0.1:8765/#equipment")
            await assert_no_horizontal_scroll(page)
            await page.locator("#client-equipment-search").fill("FP-SEARCH-900")
            await expect(page.locator(".client-equipment-card")).to_have_count(1)
            await expect(page.locator(".client-equipment-card")).to_contain_text("Needle Model")
            await page.locator("#client-equipment-search").fill(flow.sites[0].name)
            await expect(page.locator(".client-equipment-card")).to_have_count(2)

            await page.goto(f"http://127.0.0.1:8765/#requests/{waiting_id}")
            await page.locator("#client-attachment-add").click()
            image = BytesIO(); Image.new("RGB", (4, 4), color="blue").save(image, format="PNG")
            await page.locator("#attachment-file").set_input_files({"name": "problem.png", "mimeType": "image/png", "buffer": image.getvalue()})
            async with page.expect_response(lambda response: response.url.endswith(f"/service-requests/{waiting_id}/attachments") and response.request.method == "POST") as upload:
                await page.locator("#attachment-save").click()
            assert (await upload.value).status == 201
            await expect(page.locator(".sr-request-photo-grid")).to_be_visible()
        finally:
            await browser.close()


async def test_site_edit_and_invite_revoke_are_persistent(live, flow):
    from playwright.async_api import async_playwright, expect
    pending = await invite(flow, invited_email="pending-fp@example.com")
    director_invite = await invite(flow, "director", invited_email="director-fp@example.com")
    accepted = await accept(flow, director_invite, email="director-fp@example.com")
    assert accepted.status_code == 200, accepted.text
    request_id = await new_request(flow)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        page = await browser.new_page(viewport={"width": 390, "height": 844})
        director = await browser.new_page(viewport={"width": 390, "height": 844})
        try:
            await login(page, flow.owner.email)
            await page.goto(f"http://127.0.0.1:8765/#clients/{flow.client.id}/sites/{flow.sites[0].id}")
            await page.locator("#client-site-edit").click()
            await assert_no_horizontal_scroll(page)
            await page.locator("#f-site-name").fill("Объект FP обновлён")
            await page.locator("#f-site-address").fill("Новый адрес FP")
            async with page.expect_response(lambda response: response.url.endswith(f"/sites/{flow.sites[0].id}") and response.request.method == "PATCH") as saved:
                await page.locator("#modal-save").click()
            assert (await saved.value).status == 200
            await page.reload()
            await expect(page.locator(".client-detail-hero")).to_contain_text("Объект FP обновлён")
            await expect(page.locator(".client-detail-hero")).to_contain_text("Новый адрес FP")

            await page.goto(f"http://127.0.0.1:8765/#clients/{flow.client.id}/users")
            row = page.locator(f'[data-invite-revoke="{pending["id"]}"]').locator("xpath=..")
            await expect(row).to_contain_text("pending-fp@example.com")
            async with page.expect_response(lambda response: response.url.endswith(f'/invites/{pending["id"]}/revoke') and response.request.method == "POST") as revoked:
                await page.locator(f'[data-invite-revoke="{pending["id"]}"]').click()
            assert (await revoked.value).status == 200
            await expect(page.locator(".invite-list")).to_contain_text("Отозвано")
            await expect(page.locator(f'[data-invite-revoke="{pending["id"]}"]')).to_have_count(0)

            await login(director, "director-fp@example.com")
            await director.goto(f"http://127.0.0.1:8765/#clients/{flow.client.id}/sites/{flow.sites[0].id}")
            await expect(director.locator("#client-site-edit")).to_have_count(0)
            await director.goto(f"http://127.0.0.1:8765/#requests/{request_id}")
            await expect(director.locator("#request-assign-technician")).to_have_count(0)
            await expect(director.locator("#request-add-attachment")).to_have_count(0)
            await expect(director.locator("#client-attachment-add")).to_be_visible()
            await assert_no_horizontal_scroll(director)
        finally:
            await browser.close()
