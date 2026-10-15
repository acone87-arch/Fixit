---
name: fixit-release
description: Prepare a safe Fixit GitHub PR or production release readiness review, including CI, Alembic compatibility, backup/restore and rollback evidence. Use before merges, migrations or VPS deployment.
---

# Release readiness: no automatic deploy

Read `AGENTS.md`, `docs/PRODUCTION_RUNBOOK.md`, `.github/workflows/deploy.yml`, `.github/workflows/pilot-onboarding.yml`, `scripts/deploy_pilot_release.sh` and the proposed diff.

1. Resolve precise source branch, base SHA, PR head SHA and all changed files. Determine migration chain and potential compatibility with the previous application image.
2. Demand real acceptance evidence: targeted and full pytest on isolated PostgreSQL, browser/JS runtime and IndexedDB/SW gates. Capture pass/fail/skip honestly. Check current CI status for the **exact** candidate SHA.
3. Check tenant/media permissions, ServiceRequest↔Repair idempotency, QR/inventory, workflow states, offline queues and mobile layout if changed.
4. For any DB change, validate `alembic upgrade head` on clean and upgrade test DBs, ensure safe rollback of app binaries even if migration has run. Never propose production downgrade or blanket `alembic stamp`.
5. Confirm documented DB + media backup/restore drill, retained volumes, health/TLS checks, security of secrets and deployment preconditions from runbook.
6. Present explicit GO/NO-GO summary, changed paths, test evidence, unresolved risks and planned recovery steps. Docs-only PRs may not need browser interaction, but release pipeline still defines the gate.
7. Creating/opening a PR is not a deployment. `main` pushes trigger production deploy. Do not merge, push to `main` or release branch, run workflow_dispatch, access VPS or modify data without separate explicit approval from the user.

Never claim CI succeeded if its run is pending or not checked.
