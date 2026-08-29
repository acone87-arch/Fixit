# Client portal notification hooks

The portal deliberately uses `ServiceRequestEvent` as the integration source of truth. Future Push, Telegram and email adapters should subscribe to these existing event types without changing the ServiceRequest workflow:

- `request.created`
- `status.changed`
- `approval.requested` / `request.waiting_approval`
- `approval.approved`
- `approval.rejected`
- `repair.completed`
- `service_act.generated`

No notification delivery, contact export, or external messaging credentials are included in this change.
