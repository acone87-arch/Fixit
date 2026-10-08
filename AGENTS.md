# Fixit — instructions for coding agents

Работай с Fixit как с действующим multi-tenant SaaS. Изменения должны быть минимальными, обратимо развёртываемыми и подтверждёнными тестами.

## Project map

- Backend: FastAPI, SQLAlchemy, PostgreSQL; `app/routers/`, `app/services/`, `app/models/`, `app/schemas/`.
- DB migrations: `alembic/versions/`; never rewrite or reorder applied revisions.
- Admin/client UI: `app/static/`; mobile technician PWA: `app/static-tech/` plus mounted offline assets in `app/static/offline/`; public guest: `app/static-guest/`.
- Tests: `tests/`, `scripts/test_location_workflow.py`; CI: `.github/workflows/`.
- Production and backups: `docs/PRODUCTION_RUNBOOK.md` and `scripts/deploy_pilot_release.sh`.
- The top-level README contains historical sections; verify claims against current code and migrations.

## Non-negotiable invariants

1. The tenant boundary is Organization. Organization → Client → Site → Equipment; never trust a client-supplied organization_id for authorization.
2. ServiceRequest is the canonical work item. Task is legacy/read-only; Ticket retains guest QR provenance. Do not restore Task/Ticket as parallel workflows.
3. A ServiceRequest has one canonical Repair. Preserve idempotent QR submissions, sync retries, stable receipts and version-based conflict handling.
4. All access checks run server-side. Preserve Client/Site scope and role checks, technician assignments, revocations, media ACL and public QR token separation.
5. Protect warehouse stock integrity, concurrent updates, PostgreSQL row locking and ordering. Never use SQLite as proof for PG-only behavior.
6. Preserve IndexedDB queues, service worker semantics, existing offline payload formats, guest upload retry and QR routes. Do not erase client storage as an easy fix.
7. No redesign, new framework, or unrelated feature without an explicit requirement.

## How to work

- Read `GLOSSARY.md`, `docs/agents/domain.md`, and relevant existing tests before changing business rules.
- For meaningful features, agree on a focused spec and acceptance criteria; use GitHub Issues for approved task tracking. See `docs/agents/issue-tracker.md`.
- Prefer an end-to-end vertical slice (router + service + DB if required + UI + regression tests). Keep changes isolated.
- For new behavior, write a failing regression test first where feasible; test negative ACL cases and retry/concurrency behavior.
- Verify targeted tests first, then full PostgreSQL/Chromium/JS gates if the environment permits. Record actual results and skipped/blocked checks; never claim unrun tests passed.
- For JS/PWA changes test at 390x844 and 1440x1000, and check Service Worker/IndexedDB with real browser runtime.
- Update related PWA shell/cache versions together when shipping changed assets; do not reset IndexedDB.
- For migrations use compatible expand/contract steps; never use stamp/downgrade on production.

## Delivery and safety

- Create a feature branch and PR; do not merge into `main`, push a release branch, run manual deploy or alter VPS/production data without explicit approval.
- `main` push triggers production deployment. PR checks are validation, not permission to deploy.
- Never commit credentials, real personal data, DB dumps, `.env` values, or production logs.
- Summarize changed files, tests actually executed, remaining risks, rollout/rollback considerations, and PR link.

## Project-specific skills

- `.agents/skills/fixit-feature/` — specification-to-PR feature workflow.
- `.agents/skills/fixit-mobile-qa/` — responsive and offline PWA acceptance.
- `.agents/skills/fixit-security/` — tenant, role, media, QR and warehouse boundary review.
- `.agents/skills/fixit-release/` — pre-release checks and manual-go/no-go; never auto-deploy.
- Third-party Matt Pocock skills are installed separately in Codex (not vendored); see `docs/agents/README.md`.
