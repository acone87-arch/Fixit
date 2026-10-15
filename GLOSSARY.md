# Fixit domain glossary

Canonical terms, not an exhaustive data dictionary. Verify exact states and permissions in code and tests.

- **Organization** — tenant boundary for all business data and memberships.
- **OrganizationMembership** — a user's per-organization membership/role; do not confuse with global User.
- **Client** — customer of a service organization; may contain multiple Sites.
- **Site** — physical work object/location of a Client.
- **Equipment** — asset tied to a Site, with passport, inventory and QR identity.
- **ServiceRequest** — canonical current work request: assignment, workflow, approvals, history.
- **Repair** — canonical result of ServiceRequest completion; no duplicate on retries.
- **Ticket** — legacy/guest QR intake provenance, not an independent current workflow.
- **Task** — historical legacy record; not a new-work management workflow.
- **GuestRequestReceipt** — stable idempotent outcome keyed to a guest submit.
- **TechnicianClientAccess** — grant limiting a technician to authorized Clients (and their Sites as policy permits).
- **Client portal** — customer-scoped view; no tenant-wide access by default.
- **Fixit Pulse** — technician PWA, with offline queues and background/foreground sync.
- **pendingRepairs / pendingAttachments** — device-side durable offline operations, not disposable cache.
- **local_uuid** — idempotency key for offline repair sync.
- **Equipment version** — optimistic concurrency token used during sync conflict checks.
- **Warehouse stock** — concurrent PostgreSQL state; mutations need correct locks and invariants.
- **Public QR token** — opaque external identifier; never substitute an internal equipment UUID.

Read `app/services/service_request_workflow.py`, `app/services/access_policy.py`, `app/services/sync_service.py` and their tests before redefining these terms.
