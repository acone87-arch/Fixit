# Fixit agent skills: Codex setup

This repository contains four small project-local skills in `.agents/skills/` and the root `AGENTS.md` policy. They are reviewed text files, not installed executables.

## Recommended third-party skill set

External source: https://github.com/mattpocock/skills (review its contents before installing/updating). Recommended for Fixit: `grill-with-docs`, `to-spec`, `to-tickets`, `implement`, `tdd`, `diagnosing-bugs`, `code-review`, `pr`, `domain-modeling`, and `setup-matt-pocock-skills`. Use `prototype` when investigating mobile UX, not as a replacement for accepted UI.

Codex installation from the upstream README (run in your OWN Codex terminal, not on the production VPS):

~~~bash
codex plugin marketplace add mattpocock/skills
codex plugin add mattpocock-skills@mattpocock
~~~

Restart/refresh Codex if needed. If the installed Codex version lacks plugin commands, update Codex or use the upstream `npx skills@latest add mattpocock/skills` approach, selecting the Codex agent. Do not install both to avoid duplicate skill names. Verify installed skills before use.

The upstream `/setup-matt-pocock-skills` is an interactive configuration skill. This repo already seeds `docs/agents/issue-tracker.md`, `docs/agents/domain.md`, and `GLOSSARY.md`; run setup only if you wish to inspect/adjust those choices. Do not overwrite the root `AGENTS.md` or existing project instructions.

## Our local skills

- `fixit-feature`: focused requirements → code → tests → PR workflow.
- `fixit-security`: multi-tenant, client scope, QR, media and warehouse authorization review.
- `fixit-mobile-qa`: responsive UI, offline sync, PWA and Service Worker acceptance.
- `fixit-release`: safe pre-release checklist; requires human permission for merge/deployment.

Suggested first test: ask Codex to use `fixit-security` to review the current ServiceRequest attachment read/write boundary without making changes, report exact files and tests, and open no PR until approved.

## Agent operating contract

Use GitHub Issues for approved work, `GLOSSARY.md` for canonical domain terms, and `docs/adr/` for ADRs only when architecture decisions are made. If a third-party skill proposes large changes, the root `AGENTS.md` constraints take priority. Installing a skill is not permission to deploy, modify live data or run unknown scripts.

All secrets stay outside Git; work on a feature branch. CI runs on pull requests; only merges/pushes to `main` may trigger production deployment.
