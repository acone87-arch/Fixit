# Task deprecation plan

Fixit 2.0 exposes only **ServiceRequest / Заявка** to users. `Task` remains an
internal compatibility record and must not be dropped with a database migration
yet. The current physical dependencies are:

- `ServiceRequest.task_id` binds legacy staff work to the user-facing request;
- QR Ticket assignment creates or updates a Task and binds it to the resulting
  ServiceRequest;
- `Repair.task_id` preserves historical repair and service-act links;
- `/api/v1/sync/repairs` accepts `task_id` for existing technician devices and
  idempotent offline payloads;
- Task status updates still mirror selected ServiceRequest transitions.

## Future migration

1. Make ServiceRequest the source of assignment, status and completion for all
   new Ticket and dispatcher flows.
2. Make Repair reference ServiceRequest directly (backfill from `task_id`).
3. Continue accepting `task_id` in sync payloads as a deprecated compatibility
   field while clients move to `service_request_id`.
4. Remove Task write endpoints, then backfill/retire the legacy links in a
   separately reviewed migration after repair and service-act retention checks.

No Task data is deleted by the present UI consolidation.
