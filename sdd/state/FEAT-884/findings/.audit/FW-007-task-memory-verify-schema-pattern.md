---
id: FW-007
query_id: Q006
type: wiki_query
intent: "Find existing schema-bootstrap / CREATE TABLE IF NOT EXISTS / verify_schema patterns parrot already uses."
executed_at: 2026-11-12T20:41:43Z
duration_ms: 1900
parent_id: null
depth: 0
---

# FW-007 — Third in-repo pattern: task-memory store has a packaged migration + version check at startup (verify_schema / apply_migrations)

## Summary

`sym:…/task_memory/store/postgres.py#PostgresTaskMemoryStore.verify_schema` (score 1.00, L612-642): called at
enabled-backend startup, reads the recorded migration version, raises `TaskMemoryUnavailable` if none ("run
apply_migrations() at deployment"), if the DB records a newer version than `MIGRATION_VERSION` ("upgrade the
application"), or if any of `REQUIRED_TABLES` is missing. `PostgresTaskMemoryStore.apply_migrations` (score 1.00)
"Apply the packaged migration explicitly". So parrot already has **three** independent schema mechanisms: Studio's
ledger runner (FW-006), task-memory's version check + explicit apply, and hand-applied loose SQL for ai_bots
(FW-005) — plus `creation.sql` as a destructive bootstrap (FW-004). None is exposed through `parrot self`.

## Citations

- path: `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/store/postgres.py`
  lines: 612-642
  symbol: `PostgresTaskMemoryStore.verify_schema`
  excerpt: |
    async def verify_schema(self) -> None:
        """Check the database has the shape this build expects.
        Called at enabled-backend startup, not per operation. A missing table is reported by name, so an
        operator sees "you did not run the migration" rather than a confusing error inside the first append."""
            if version is None:
                raise TaskMemoryUnavailable(... "run apply_migrations() at deployment before enabling durable task memory")
            if version > MIGRATION_VERSION:

- path: `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/store/postgres.py`
  lines: n/a (wiki symbol hit)
  symbol: `PostgresTaskMemoryStore.apply_migrations`
  excerpt: |
    Apply the packaged migration explicitly.

## Notes

The verify-at-startup / apply-at-deploy split matches navauth's G6 (startup warns, never DDLs) and Studio's
"Never called at startup". Other hits on Q006 were out of scope (eventbus FEAT-319 DDL retrofit test, querysource
table destination, flowtask components).
