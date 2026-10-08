# Domain documentation conventions

- Layout: single-context repository, root `GLOSSARY.md` for canonical terms.
- Source of truth for implemented behavior: code + current tests + applied Alembic graph. A glossary is a navigation aid, not a replacement.
- Record consequential architecture decisions as dated Markdown files under `docs/adr/`, creating the directory only if a real ADR is needed.
- Before changing ServiceRequest/Repair/Task/Ticket semantics, first inspect `app/services/service_request_workflow.py`, `app/services/service_requests.py`, `app/services/sync_service.py`, and existing migration and regression tests.
- Before changing authorization, inspect `app/core/deps.py`, `app/services/access_policy.py`, `app/services/client_portal.py`, role-specific routers, and denial tests.
- Before changing offline behavior, inspect `app/static/offline/engine.js`, `app/static/sw.js`, `app/static-tech/db.js`, the frontend clients and browser runtime tests.
- Avoid conflating Client scope and Organization scope, or guest identity and authenticated technician identity.
- If implementation and old README sections disagree, document the divergence and prefer current code and verified tests.
