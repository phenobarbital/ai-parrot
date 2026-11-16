---
id: FC-012
query_id: Q012
type: grep
intent: "Find other parrot-owned tables (CREATE TABLE) that would be candidates for the migration registry."
executed_at: 2026-11-12T20:42:33Z
duration_ms: 900
parent_id: null
depth: 0
---

# FC-012 — ~160 CREATE TABLE sites; many navigator.* tables self-create at runtime in Python

## Summary

163 `CREATE TABLE` hits in package sources (excl. build/). Two populations: (a) **runtime self-provisioning** in Python —
`CREATE TABLE IF NOT EXISTS` executed by stores/handlers on first use (`navigator.ui_surfaces`, `ui_surface_shares`,
`crew_definitions`, `metric_definitions`, `studio_drafts`, `ai_skills_catalog`, `service_scheduler`,
`{schema}.infographic_recipes`, flows storage/checkpoint tables, autonomous `harness_ledger`, eval sink tables,
graphindex `{schema}.*`); several of these already carry ad-hoc "columns added after v1" ALTER lists
(graphindex pg_schema.py:345, persist_sqlite.py:107/196). (b) **SQL-only** tables whose DDL is never executed by code
(`navigator.users_bots`, `users_prompts`, `notification_templates`, `notification_batch_recipients`, ai_bots).
Some tables appear in both a runtime DDL and a studio migration (`navigator.studio_drafts`, `navigator.ai_skills_catalog`).

## Citations

- path: `packages/ai-parrot-server/src/parrot/handlers/models/ui_surfaces.py`
  lines: 110
  excerpt: |
    CREATE TABLE IF NOT EXISTS navigator.ui_surfaces (

- path: `packages/ai-parrot-server/src/parrot/handlers/crew/postgres_persistence.py`
  lines: 23
  excerpt: |
    """CREATE TABLE IF NOT EXISTS navigator.crew_definitions (

- path: `packages/ai-parrot-server/src/parrot/handlers/models/studio_drafts.py`
  lines: 45
  excerpt: |
    CREATE TABLE IF NOT EXISTS navigator.studio_drafts (

- path: `packages/ai-parrot-server/src/parrot/handlers/studio/storage/migrations/0005_studio_drafts_baseline.sql`
  lines: 4
  excerpt: |
    CREATE TABLE IF NOT EXISTS navigator.studio_drafts (

- path: `packages/ai-parrot-server/src/parrot/handlers/models/skills_catalog.py`
  lines: 34
  excerpt: |
    CREATE TABLE IF NOT EXISTS navigator.ai_skills_catalog (

- path: `packages/ai-parrot-server/src/parrot/handlers/models/metric_definitions.py`
  lines: 23
  excerpt: |
    """CREATE TABLE IF NOT EXISTS navigator.metric_definitions (

- path: `packages/ai-parrot-server/src/parrot/scheduler/models.py`
  lines: 24
  excerpt: |
    CREATE TABLE IF NOT EXISTS navigator.service_scheduler (

- path: `packages/ai-parrot/src/parrot/knowledge/graphindex/pg_schema.py`
  lines: 345
  excerpt: |
    #: Columns added after v1 shipped. ``CREATE TABLE IF NOT EXISTS`` silently

- path: `packages/ai-parrot-server/src/parrot/handlers/models/users_bots_creation.sql`
  lines: 7
  excerpt: |
    CREATE TABLE IF NOT EXISTS navigator.users_bots (

- path: `packages/ai-parrot/src/parrot/eval/sink.py`
  lines: 11
  excerpt: |
    Idempotent ``CREATE TABLE IF NOT EXISTS`` DDL so the sink self-provisions

- path: `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/store/postgres.py`
  symbol: `PostgresTaskMemoryStore.verify_schema`
  excerpt: |
    (wiki stub) "Check the database has the shape this build expects." — a read-only schema verifier pattern.

## Notes

Scope decision for synthesis: start with ai_bots only (per source) vs. a registry where each subsystem contributes a
set. Runtime self-create is the dominant pattern for newer tables; it handles CREATE but not column evolution — the
same drift problem ai_bots has. Not exhaustive (163 hits, top ~70 inspected); squawk/semantic/formdesigner tables are
in satellite distributions.
