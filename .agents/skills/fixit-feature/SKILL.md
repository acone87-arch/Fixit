---
name: fixit-feature
description: Implement scoped Fixit SaaS features safely. Use for a user-requested ServiceRequest, client portal, equipment, warehouse, profile or UI change that needs API, database and regression test parity.
---

# Fixit feature workflow

Read repository `AGENTS.md`, `GLOSSARY.md`, `docs/agents/domain.md` and current tests first. Respect the canonical service request workflow and tenant boundaries.

1. **Understand scope.** Inspect existing code and connected call sites. State the user's goal, roles, acceptance criteria, negative cases, API/UI/data impacts and explicit non-goals. For ambiguous product rules use upstream `grill-with-docs` if installed; otherwise ask only essential questions. Use `to-spec`/`to-tickets` only for work large enough to warrant them.
2. **Plan minimal vertical slice.** Locate router, service, model/schema, frontend assets and test files. Prefer extending existing seams; don't build a parallel Task/Ticket workflow, new framework, or unrelated refactor.
3. **Implement test-first when feasible.** Add or update a regression test for observable behavior including retries, incorrect role and cross-tenant/client access. Then make the smallest change; consider upstream `tdd` and `implement` if available.
4. **Migrations only when required.** Use new Alembic revision after existing head, backwards-compatible with previous app image. Verify upgrade from an isolated PostgreSQL DB; never run migration against production without explicit approval.
5. **UI parity.** Keep API and PWA/admin forms aligned. Verify 390x844 and desktop. Check empty/loading/error states, image previews, network loss, old SW/cache and delayed offline uploads where affected.
6. **Proof.** Run targeted pytest and JS/browser tests, then as much of the complete test suite as available. Do not misreport skipped/blocked tests. If dependencies are unavailable report the exact limitation.
7. **Deliver.** Give a concise description of modified files, acceptance evidence, migration/rollout risk and any remaining work. Create a feature PR when requested/authorized; NEVER merge `main` or deploy automatically.

Key entry points: `app/routers/service_requests.py`, `app/services/service_request_workflow.py`, `app/services/access_policy.py`, `app/static/app.js`, `app/static/offline/` (active Pulse), `app/static-tech/` (legacy compatibility/rollback only), `tests/`.

Useful validation when dependencies are present: `pytest -q`; `node tests/technician_workflow_runtime_test.js`; `node tests/pulse_offline_engine_runtime_test.js`; `node tests/durable_queue_browser_test.js`. PostgreSQL and Chromium-dependent tests require isolated infrastructure.
