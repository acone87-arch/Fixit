# Pulse technician offline audit

The technician workspace in `app/static/app.js` currently persists its local ServiceRequest draft, including selected photos, through `RequestDraftStore`. It does **not** yet share the mature `pendingRepairs` / `pendingAttachments` queue and Background Sync implementation used by the dedicated technician PWA in `app/static-tech/`.

Until those flows are unified, Fixit Pulse must not be described as fully offline-first. The future consolidation should reuse the existing queue and idempotency contract rather than introduce a third sync implementation.
