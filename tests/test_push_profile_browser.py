"""Real Chromium profile → real HTTP/PG; synthetic browser PushManager only."""
import json
import os

import pytest

from app.config import settings
from app.routers import push as push_router
from app.services import push_service
from test_onboarding_browser import live
from test_onboarding_postgres import pg, auth
from test_push_endpoint_security import synthetic_keys

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(os.getenv("FIXIT_RUN_BROWSER") != "1",
    reason="FIXIT_RUN_BROWSER=1 required for real profile Chromium acceptance")]


@pytest.mark.parametrize("viewport", [{"width": 390, "height": 844}, {"width": 1440, "height": 1000}])
async def test_profile_push_enable_disable_reconnect_and_vapid_rotation(live, monkeypatch, viewport):
    from playwright.async_api import async_playwright, expect
    monkeypatch.setattr(push_router, "configured", lambda: True)
    monkeypatch.setattr(push_service, "configured", lambda: True)
    monkeypatch.setattr(settings, "vapid_public_key", synthetic_keys()["p256dh"])
    keys = synthetic_keys()
    token = auth(live.owner, live.org)["Authorization"].removeprefix("Bearer ")
    setup = {"token": token, "keys": keys,
        "onboardingKey": f"fixit-onboarding-dismissed:{live.org.id}:{live.owner.id}"}
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        context = await browser.new_context(viewport=viewport, service_workers="block")
        await context.add_init_script("""(data => {
            localStorage.setItem('token', data.token);
            localStorage.setItem('fixit-install-dismissed', '1');
            localStorage.setItem(data.onboardingKey, '1');
            let permission = 'default', current = null, counter = 0;
            Object.defineProperty(window, 'Notification', {value: class {
                static get permission() { return permission; }
                static async requestPermission() { permission = 'granted'; return permission; }
            }});
            const manager = {
                async getSubscription() { return current; },
                async subscribe(options) {
                    const endpoint = 'https://fcm.googleapis.com/fcm/send/browser-synthetic-' + (++counter);
                    current = {endpoint, options, toJSON() { return {endpoint, keys: data.keys}; },
                        async unsubscribe() { current = null; return true; }};
                    return current;
                }
            };
            const registration = {pushManager: manager, update: async () => {}};
            navigator.serviceWorker.register = async () => registration;
            navigator.serviceWorker.getRegistration = async () => registration;
            navigator.serviceWorker.getRegistrations = async () => [registration];
            window.syntheticPush = {async staleKey() {
                current.options.applicationServerKey = new Uint8Array([1]);
            }};
        })(""" + json.dumps(setup) + ");")
        page = await context.new_page()
        try:
            await page.goto("http://127.0.0.1:8765/#profile")
            await page.locator("#profile-push-enable").click()
            await expect(page.locator("#profile-push-state")).to_contain_text("Уведомления включены")
            await page.locator("#profile-push-disable").click()
            await expect(page.locator("#profile-push-enable")).to_be_visible()
            await page.locator("#profile-push-enable").click()
            await expect(page.locator("#profile-push-state")).to_contain_text("Уведомления включены")
            # Exercise rotation with a changed browser endpoint using the actual
            # production function and HTTP APIs, without contacting push services.
            await page.evaluate("syntheticPush.staleKey()")
            assert await page.evaluate("enablePush()") == "enabled"
            await page.reload()
            await expect(page.locator("#profile-push-state")).to_contain_text("Уведомления выключены")
            # Reload resets the synthetic browser fixture; reconnect must remain usable.
            await page.locator("#profile-push-enable").click()
            await expect(page.locator("#profile-push-state")).to_contain_text("Уведомления включены")
            assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        finally:
            await context.close()
            await browser.close()
