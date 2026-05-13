---
id: F016
query_id: Q016
type: glob
intent: Locate any existing storage/migrations layout to know where the new schema.sql should land and how migrations run.
executed_at: 2026-05-12T00:00:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F016 — NO migration framework exists; convention is **bare `.sql` files co-located with the module**

## Summary

There is **no `parrot/storage/migrations/` directory**, no Alembic config
(`alembic.ini` / `env.py` absent), and no migration runner script. The codebase
keeps initial DDL as plain `.sql` files co-located with the module that owns
the schema. The closest precedents are:
- `parrot/security/security_events.sql` — `CREATE TABLE IF NOT EXISTS ...` plus
  `CREATE INDEX` statements (most similar pattern; uses `IF NOT EXISTS` for
  idempotency).
- `parrot/handlers/creation.sql` — header note `"WARNING: Initial setup DDL
  only. DO NOT run against production."` then `DROP TABLE` + `CREATE TABLE` +
  `ALTER TABLE ADD COLUMN IF NOT EXISTS` migration block at the bottom.
- `parrot/handlers/models/users_bots_creation.sql`
- `parrot/pipelines/table.sql`
- `parrot_pipelines/table.sql`
- `parrot/advisors/catalog/example.sql`

No `.py` file in `parrot/` reads `security_events.sql` at runtime (verified by
`grep`). Migrations appear to be applied **out-of-band** by ops/manual DBA
processes. The only `migrations/` directory in the repo is `sdd/migrations/`,
which is an SDD bookkeeping folder, NOT a DB migration store.

**Resolution for OQ #2 (Schema migrations):** Drop `schema.sql` next to the
new store at `parrot/storage/security_reports/schema.sql` with
`CREATE TABLE IF NOT EXISTS` + `CREATE INDEX IF NOT EXISTS`. Optionally add a
small runner method on `PostgresS3SecurityReportStore` that executes the file
content on `start()` — this would be a NEW convention but a reasonable one
(makes the dev experience self-bootstrapping).

## Citations

- path: `packages/ai-parrot/src/parrot/security/security_events.sql`
  lines: 1-26
  symbol: closest precedent (idempotent DDL + indexes)
  excerpt: |
    -- Security events tracking table
    CREATE TABLE IF NOT EXISTS security_events (
        event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        ...
        metadata JSONB DEFAULT '{}',
        created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
    );
    CREATE INDEX idx_security_events_user_id ON security_events(user_id);
    CREATE INDEX idx_security_events_severity ON security_events(severity);
    CREATE INDEX idx_security_events_high_severity ON security_events(severity, created_at DESC)
    WHERE severity IN ('critical', 'high');

- path: `packages/ai-parrot/src/parrot/handlers/creation.sql`
  lines: 1-15
  symbol: alternate precedent — full creation + inline migration block
  excerpt: |
    -- WARNING: Initial setup DDL only. DO NOT run against production.
    -- For migrations, use the ALTER TABLE ADD COLUMN IF NOT EXISTS statements at the bottom.
    DROP TABLE IF EXISTS navigator.ai_bots CASCADE;
    CREATE TABLE IF NOT EXISTS navigator.ai_bots (...);

- path: `packages/ai-parrot/src/parrot/storage/`
  lines: directory listing
  symbol: NO migrations/ directory
  excerpt: |
    storage/
      __init__.py
      artifacts.py
      backends/
      chat.py
      dynamodb.py
      instrumented.py
      metrics.py
      models.py
      overflow.py
      s3_overflow.py
      (no migrations/)

## Notes

- No `alembic*` file anywhere in the repo (verified by `find`).
- No `read_text` / `execute` reference to `security_events.sql` in any Python
  source — this is a manual-apply pattern.
- Spec recommendation: `schema.sql` next to `store.py`, idempotent DDL only,
  optional `PostgresS3SecurityReportStore.bootstrap_schema()` that the
  SecurityAgent calls once on startup (guarded by a config flag for safety).
