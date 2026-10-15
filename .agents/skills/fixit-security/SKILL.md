---
name: fixit-security
description: Audit or test Fixit's multi-tenant permissions, cross-client access, QR intake, media ACL, JWT membership and warehouse integrity. Use for security-sensitive code changes or pre-PR review.
---

# Security boundary review

Read `AGENTS.md` and `GLOSSARY.md`. Inspect actual policy code before asserting a role's permissions.

1. **Map trust boundaries:** OrganizationMembership and server-derived tenant; Client/Site and TechnicianClientAccess grants; public guest QR; token/session; media routes; warehouse mutations.
2. **Trace server enforcement:** `app/core/deps.py`, `app/services/access_policy.py`, `app/services/client_portal.py` plus the relevant router and service. A hidden frontend control is not authorization.
3. **Test denial paths:** two Organizations; two Clients in one Organization; users with and without Site/Client grants; inactive/revoked membership; attacker-supplied identifiers; client as technician and vice versa; old JWT after revoke.
4. **Check idempotency and integrity:** duplicate QR submission, upload retry, repair retry, cross-equipment receipt use, stock updates under concurrent requests, stable lock order and optimistic conflict result. Use PostgreSQL for transaction correctness.
5. **Review media:** read/write separation, author-delayed upload exceptions, public paths, file content type/size, signed/raw references and no cross-tenant enumeration.
6. **Secrets/privacy:** never print or commit auth tokens, customer photos, production DB rows or `.env`; use synthetic fixtures in tests.
7. **Evidence:** run relevant `tests/test_security_postgres.py`, `tests/test_client_portal_security.py`, `tests/test_media_security.py`, `tests/test_technician_access_policy.py`, `tests/test_client_access_management.py`, and applicable business-specific tests. Record exactly which ran.

Output severity-ranked findings with `file:line`, exploit preconditions, user impact, proof/test and smallest fix. If no findings, say which surfaces were actually reviewed and which were not.

Never make live-data changes or execute exploitation against production.
