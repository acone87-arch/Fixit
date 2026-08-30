# Task retirement status

Issue #4 completed Phase A of Task retirement.

- `ServiceRequest` is the only active work unit for dispatcher, client, guest,
  and technician flows.
- `/api/tasks` is a deprecated, read-only historical compatibility endpoint.
  It has no create, assignment, completion, cancellation, update, or delete
  handler.
- `ServiceRequest.task_id`, `Repair.task_id`, and `Repair.ticket_id` remain
  nullable historical links. They preserve unambiguous legacy repair, passport,
  and service-act history; no new Pulse payload emits them.
- Ticket remains a QR intake-provenance record for idempotency and the original
  reporter payload. Its linked `ServiceRequest` alone owns assignment and
  lifecycle. The admin Ticket API is read-only compatibility only.
- `/tech` redirects to Fixit Pulse. The unmounted `app/static-tech` assets and
  their IndexedDB schema stay only for rollback and for understanding old
  pending queues. The Pulse queue preserves that IndexedDB database and the
  server still accepts old payloads without allowing them to alter a canonical
  request through Task.

Future Phase B, only after data-retention review: archive/migrate old rows and
consider dropping legacy columns and tables. No historical data is deleted in
this phase.
