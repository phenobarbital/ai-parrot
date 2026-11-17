---
id: FC-011
query_id: Q016
type: grep
intent: "Find where navigator DDL / SQL migrations live (CREATE TABLE convention)."
executed_at: 2026-11-09T17:32:00Z
duration_ms: 900
parent_id: null
depth: 0
---

# FC-011 — Three coexisting DDL conventions for navigator.* tables: in-module auto-create, standalone *_creation.sql, and Studio's numbered migrations + ledger

## Summary

`grep -i "CREATE TABLE (IF NOT EXISTS )?navigator\."` over `packages/*/src` (excluding `build/`) finds:
(1) **in-module, auto-applied** DDL in Python stores — `handlers/models/ui_surfaces.py`,
`handlers/models/studio_drafts.py`, `handlers/models/skills_catalog.py`, `handlers/models/metric_definitions.py`,
`scheduler/models.py` (plus docstring-only DDL in core `models/bots.py`); (2) **standalone, hand-applied**
`*_creation.sql` files next to models — `handlers/models/users_prompts_creation.sql`,
`users_bots_creation.sql`, `notification_templates_creation.sql`, `notification_batches_creation.sql`,
`handlers/creation.sql`; (3) **numbered, ledgered** migrations for the Studio plane —
`handlers/studio/storage/migrations/0001_studio_migrations_ledger.sql` … `0008_ai_user_toolkit_overrides.sql`,
applied by `handlers/studio/storage/migrate.py` and tracked in `navigator.ai_studio_migrations`.
No crew-related DDL exists anywhere.

## Citations

- path: `packages/ai-parrot-server/src/parrot/handlers/studio/storage/migrations/0001_studio_migrations_ledger.sql`
  lines: 1
  symbol: `navigator.ai_studio_migrations (ledger)`
  excerpt: |
    CREATE TABLE IF NOT EXISTS navigator.ai_studio_migrations ...  (1 CREATE TABLE match)

- path: `packages/ai-parrot-server/src/parrot/handlers/studio/storage/migrations/0002_ai_agents.sql`
  lines: 1
  symbol: `navigator.ai_agents`
  excerpt: |
    (3 CREATE TABLE navigator.* matches — ai_agents plane)

- path: `packages/ai-parrot-server/src/parrot/handlers/studio/storage/migrate.py`
  lines: 182-185
  symbol: `migration runner`
  excerpt: |
    (references navigator.ai_studio_migrations — applies 000N_*.sql in order, records applied ids)

- path: `packages/ai-parrot-server/src/parrot/handlers/models/ui_surfaces.py`
  lines: 107-154
  symbol: `_DDL_STATEMENTS (in-module auto-create)`
  excerpt: |
    "CREATE SCHEMA IF NOT EXISTS navigator",
    CREATE TABLE IF NOT EXISTS navigator.ui_surfaces (...)

- path: `packages/ai-parrot-server/src/parrot/handlers/models/users_bots_creation.sql`
  lines: 1
  symbol: `standalone creation script`
  excerpt: |
    CREATE TABLE IF NOT EXISTS navigator.users_bots ...  (applied by hand)

- path: `packages/ai-parrot-server/src/parrot/scheduler/models.py`
  lines: 22
  symbol: `navigator.service_scheduler`
  excerpt: |
    (in-module CREATE TABLE navigator.service_scheduler)

## Notes

- The crew store lives next to `PgUISurfaceStore`-style stores (server package, `handlers/`), so the
  in-module auto-create idiom (FC-006) is the closest fit and needs no operator step; the Studio
  migrations runner is plane-specific (Studio storage) — reusing it would couple crews to Studio.
- Other repos' SQL migration dirs (`packages/parrot-formdesigner/migrations/`) are unrelated.
- File-level line numbers for the .sql hits were not individually read (grep counts only).
