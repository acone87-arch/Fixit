# Fixit — agent rules

This file is the default context for Codex/AI work in this repository. Keep it short. Do not reconstruct the whole project before every task.

## Product goal

Fixit is a production SaaS/PWA for field service companies. The near-term goal is **FIXIT PILOT READY** without an architecture rewrite.

Critical E2E:
`Invite → Site Manager → Equipment → QR → ServiceRequest → assign technician → Repair → works + parts + photos → Act → Equipment History → result to client`.

## Sources of truth and invariants

- Tenant hierarchy: `Organization → Client → Site → Equipment`.
- Server-side access scope is authoritative. Never trust client-supplied organization/client/site ownership blindly.
- `ServiceRequest` is the canonical work/workflow entity.
- A `Repair` is linked to a `ServiceRequest`; keep the one-repair-per-request invariant and existing sync semantics.
- `Task` is legacy/read-only. Do not build new workflow on it.
- `Ticket` preserves QR-request provenance/idempotency; it is not the canonical assignment/workflow entity.
- Technician UI is **Fixit Pulse PWA**. Old `/tech` is retired/compatibility-only; do not add new product behavior there.
- Preserve Organization/Client/Site isolation, existing production data, equipment history, media, stock correctness and offline idempotency.
- QR/public flows must remain safe against duplicates and cross-tenant access.
- Production migrations must be forward-safe. Never solve a change by deleting/recreating production data.

## Token-efficient working method

Default: **one task, one model**. Do not create a multi-agent delegation loop unless the user explicitly asks for it or the task cannot reasonably be completed otherwise.

Before coding:
1. Read `AI_CONTEXT.md`.
2. Run `git status` and inspect the current diff.
3. Inspect recent commits only when they are relevant to the task.
4. Search for the exact route/model/function/UI symbol involved.
5. Open only files supported by a concrete hypothesis about the task.

Do **not** perform a full repository audit by default. Do **not** reread the whole `README.md` to recover current architecture; it may contain historical/stale sections. Use it only for a specific fact that is not covered here or in current code.

Expand scope only when evidence requires it: imports, shared schema/model, permission boundary, migration, sync path, state transition, or failing regression test.

## Risk boundaries that justify wider review

Use a broader review when a change touches any of these:
- tenant/access policy;
- `ServiceRequest ↔ Repair` relationship or state transitions;
- stock writes/locking;
- offline sync/idempotency;
- media authorization/storage;
- migrations or production deploy behavior;
- public QR/invite flows.

For low-risk UI/text/local CRUD work, stay local and avoid architecture rediscovery.

## Tests: choose targeted first

Prefer the smallest relevant existing regression test(s), then widen only if boundaries changed. Useful anchors include:

- Repair/ServiceRequest: `tests/test_canonical_repair_relationship.py`
- Client access/security: `tests/test_client_access_management.py`, `tests/test_client_portal_security.py`
- Client detail: `tests/test_client_detail_regression.py`
- Equipment history: `tests/test_equipment_service_history.py`
- Pilot onboarding/invites: `tests/test_pilot_client_onboarding.py`
- Media: `tests/test_media_security.py`
- Guest photo retry/upload: `tests/test_guest_photo_retry.py`, `tests/guest_photo_upload_runtime_test.js`
- Technician workflow: `tests/technician_workflow_runtime_test.js`
- Offline/media sync: `tests/offline_attachment_sync_runtime_test.js`, `tests/pulse_offline_engine_runtime_test.js`
- HTTP/public URL security: `tests/test_http_origin_security.py`, `tests/test_public_url_generation.py`

After coding:
1. Inspect the diff for unintended scope.
2. Run targeted tests.
3. Run broader regression/E2E only if a subsystem boundary changed or targeted tests expose a reason.
4. Update `AI_CONTEXT.md` only when durable project state, a blocker, an invariant, or the next planned task changed.

## Communication

Reasoning summaries, test results and final reports to the user should be in Russian and concise:
- что обнаружено;
- что изменено;
- какие тесты прошли/не прошли;
- оставшиеся риски;
- следующий шаг.

Do not output long internal reasoning, repeat the project history, or generate a new roadmap when an existing current task is already defined.