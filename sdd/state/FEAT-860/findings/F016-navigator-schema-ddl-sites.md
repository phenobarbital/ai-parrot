---
id: F016
query_id: Q004
type: wiki_query
intent: "Find existing Postgres tables in the navigator schema and their model classes (pattern for navigator.crew_definitions)."
executed_at: 2026-11-09T17:13:06Z
duration_ms: 650
parent_id: null
depth: 0
merged_from: [FW-005]
---

# F016 — navigator.* DDL lives in sdd/migrations/*.sql + handlers/creation.sql; Studio has its own migrated schema

## Summary

The navigator schema is dominated by `navigator.ai_bots` (BotModel). Its DDL is spread over
`packages/ai-parrot-server/src/parrot/handlers/creation.sql` (initial setup only) and idempotent, hand-run
files in `sdd/migrations/` (e.g. `ai-bots-homologate-botmodel.sql`, `FEAT-593-ai-bots-tooling-columns.sql`,
`FEAT-752-…`). A second, newer convention exists for Agent Studio (FEAT-621): DDL only in
`handlers/studio/storage/migrations/*.sql`, applied by a `migrate.py` runner that is forbidden on the startup
path. `navigator.users_prompts` (TASK-1136) is another "author a DDL file" precedent. No
`crew_definitions` table appears anywhere.

## Citations

- path: `sdd/migrations/ai-bots-homologate-botmodel.sql`
  excerpt: |
    wiki score=32.19 — idempotent additive migration bringing navigator.ai_bots up to BotModel

- path: `packages/ai-parrot-server/src/parrot/handlers/creation.sql`
  lines: 1-1
  excerpt: |
    -- WARNING: Initial setup DDL only. DO NOT run against production.

- path: `sdd/migrations/FEAT-593-ai-bots-tooling-columns.sql`
  excerpt: |
    wiki score=25.73 — "Agent Studio tooling columns on navigator.ai_bots"

- path: `packages/ai-parrot-server/tests/studio/storage/test_storage_gates.py`
  excerpt: |
    wiki score=25.83 — "FEAT-621 release gates: AC1 (no startup/handler DDL, no migration at startup), AC17 (ai_bots untouched)"

- path: `sdd/tasks/completed/TASK-1136-user-prompts-ddl.md`
  excerpt: |
    wiki score=21.05 — "Author the navigator.users_prompts DDL file"

- path: `sdd/state/FEAT-162/findings/F016-schema-migrations-convention.md`
  excerpt: |
    wiki score=21.30 — prior research finding on the schema-migration convention

## Notes

Two competing DDL conventions exist (FW-006/FW-008): runtime `CREATE TABLE IF NOT EXISTS` (PostgresResultStorage,
FW-010) vs. migration-file-only (Studio, FW-008). The proposal must pick one for navigator.crew_definitions.
[cross-lane: type=grep, intent=CREATE TABLE navigator.* across packages/ (Q016) to confirm no crew table exists]
