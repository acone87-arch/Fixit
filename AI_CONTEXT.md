# Fixit — current AI context

Keep this file compact. It is a handoff snapshot, not a project diary.

## Verified baseline

- Repository: `acone87-arch/Fixit`
- Code baseline before these context-only docs: `87e3044f30a40b6d0cff0306e71f9aee83aca329`
- Verified against `main`: 2026-09-10
- Goal: **FIXIT PILOT READY**, no architecture rewrite.

## Current architecture

- FastAPI + PostgreSQL/Alembic; production deploy is triggered from `main`.
- Tenant chain: `Organization → Client → Site → Equipment`.
- `ServiceRequest` is canonical for active service workflow.
- `Repair` is canonical repair result and is linked to `ServiceRequest`; preserve one Repair per ServiceRequest and status/result synchronization.
- `Task` is legacy/read-only. `Ticket` is QR provenance/idempotency, not the active workflow owner.
- Technician experience is Fixit Pulse PWA; old `/tech` is retired/compatibility-only.
- Client Portal, pilot Site Manager/Director invites, equipment history, media flows, offline attachment sync and Web Push foundations exist.
- Alembic migrations currently extend through `20260905_0013_guest_attachment_client_id.py`.

## Critical invariants

1. Organization/Client/Site isolation is enforced server-side.
2. Existing production data must survive every change/migration.
3. QR/public/invite flows must not create unsafe duplicates or cross-tenant access.
4. Repair/ServiceRequest state and history must remain consistent.
5. Offline repair/media sync remains idempotent and retry-safe.
6. Stock mutations preserve current locking/consistency behavior.
7. Completed work, media and Equipment History must not be lost.

## Recent code changes

- `87e3044` — restore technician assignment dependencies.
- `80ec53e` — keep client detail available with legacy requests.
- `ddad856` — guide invited client users on first access.
- `930c0f6` — keep guest photo uploads backward compatible.
- `db1169d` — retry failed guest QR photos safely.

## Documentation warning

`README.md` contains historical/stale sections. In particular, statements that repair photo upload or Alembic migrations are not implemented are no longer authoritative. Prefer current code, migrations, tests, this file and `AGENTS.md`.

## Planned product task — not yet verified in main

Preliminary equipment labeling / bulk blank QR cards:

- Admin/site workflow: create/select a Site, enter equipment count, generate that many pre-created Equipment placeholders with unique QR codes.
- Download/print QR labels before visiting the site.
- On site: scan a label → open its placeholder card → add photo and equipment identity/details → save → attach that same label to the machine.
- Admin must also be able to edit/fix Equipment card data later.
- Reuse existing Equipment/QR/access model where safe; do not create a parallel QR architecture.
- Before implementation, inspect current Equipment creation/edit/public-QR flows and choose the smallest compatible extension.

## Definition of pilot-ready E2E

`Invite → Site Manager → Equipment → QR → ServiceRequest → technician assignment → Repair → works + parts + photos → Act → Equipment History → result visible to client`.

## Handoff rule

At the end of a meaningful task, update only the sections that changed. Do not append long logs. If nothing durable changed, leave this file untouched.