---
name: fixit-mobile-qa
description: Check Fixit admin and technician PWA mobile behavior, offline queue, photos, QR, install/push and responsive regressions. Use for frontend, PWA, service worker or offline sync changes.
---

# Mobile and offline acceptance

Start with `AGENTS.md`, `docs/PROFILE_PWA_PUSH_QR_ACCEPTANCE.md`, `app/static/` (active Pulse), `app/static/offline/` (active offline logic), `app/static-tech/` (legacy compatibility/rollback only) and relevant `tests/`.

1. Record exact changed assets and routes from `app/main.py`: active Pulse (admin/client/technician) uses `/` and `/static` from `app/static/`; guest uses `/guest`. Test `/tech` and `/tech/*` redirects to `/#requests` as legacy migration cases, with `/tech/sw.js` serving `app/static/offline/sw.js`. `app/static-tech/` is not mounted; preserve it for compatibility/rollback.
2. Exercise authenticated roles and guest context separately. Test 390x844 and 1440x1000, portrait layout, keyboard/focus, error/loading/empty states, wide fonts and themes. Reject horizontal scroll at 390px.
3. Check offline first-load limitations explicitly, then online→offline→queue→reload→online. Confirm `pendingRepairs` and `pendingAttachments` persist through SW updates; verify retries with the same `local_uuid` do not create duplicate Repair or media.
4. Exercise Chromium IndexedDB and Service Worker runtime where available. Verify background sync behavior, foreground fallback and eventual feedback. Never test destructive cache clearing against a real user's stored queue.
5. Validate camera QR/BarcodeDetector fallback, guest public QR, image/photo upload and delayed retries. Respect Safari/iOS lack of Background Sync; don't promise identical cross-browser behavior.
6. Validate PWA manifest, updateable shell/cache versions, HTTPS/permission boundaries, Web Push lifecycle and permissions only if affected.
7. Run targeted tests: `node tests/pulse_offline_engine_runtime_test.js`, `node tests/offline_attachment_sync_runtime_test.js`, `node tests/durable_queue_browser_test.js`, `node tests/technician_workflow_runtime_test.js`, plus relevant `pytest` modules. Run with real PostgreSQL/Chromium where needed.
8. Report a per-platform checklist with PASS/FAIL/NOT RUN and specific reproduction steps. Screenshots must not contain live user data or secrets.

Do not redesign the app, overwrite PWA storage, or treat mocked tests as proof of browser runtime.
