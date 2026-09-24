---
id: F025
query_id: (probe)
type: read
intent: sqlglot 30.18.0 over the 32 .sql files: 26 parse, 6 fail whole-file; 20 CREATE TABLE / 329 columns / 4 PK / 3 FK / 15 ALTER recovered
executed_at: 2026-09-24T20:41:46+00:00
duration_ms: 0
parent_id: null
depth: 1
---

# F025 — sqlglot 30.18.0 over the 32 .sql files: 26 parse, 6 fail whole-file; 20 CREATE TABLE / 329 columns / 4 PK / 3 FK / 15 ALTER recovered

## Summary

Ran sqlglot.parse(text, read='postgres') per file. Totals: create_table 20, create_index 62, create_view 2, create_trigger 3, create_schema 1, create_database 1, ColumnDef 329, ForeignKey 3, PrimaryKey 4, Alter 15. Failures (ParseError aborts the WHOLE file): 4× packages/ai-parrot-server/src/parrot/handlers/models/*.sql (notification_batch…, notification_templ…, users_bots_creati…, users_prompts_cre…), packages/ai-parrot-advisors/src/parrot/advisors/catalog/example.sql (Jinja `{` at line 2), sdd/migrations/FEAT-add-prompt-config-ai-bots.sql. Non-fatal 'Falling back to parsing as a Command' for PL/pgSQL functions, DO $$ blocks and CREATE DATABASE. Gotchas: exp.PrimaryKey only counts table-level constraints — inline `id SERIAL PRIMARY KEY` is a ColumnConstraint and must be folded separately (explains 4 PK for 20 tables); statement-level splitting with per-statement try/except would recover the parseable CREATE TABLEs in the 6 failed files.

## Citations

- path: `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/migrations/001_task_memory.sql`
  lines: -
  excerpt: |
    6T 70c 4pk 3fk
- path: `sdd/migrations/FEAT-159-ontology-curation.sql`
  lines: -
  excerpt: |
    7T 73c 0pk 0fk
- path: `packages/ai-parrot-server/src/parrot/handlers/creation.sql`
  lines: -
  excerpt: |
    1T 47c 5alt
- path: `sdd/migrations/botmodel-recreate-table.sql`
  lines: -
  excerpt: |
    1T 42c 1alt
- path: `packages/ai-parrot-server/src/parrot/handlers/models/`
  lines: -
  excerpt: |
    4 files ParseError (whole-file failure)
- path: `packages/ai-parrot-advisors/src/parrot/advisors/catalog/example.sql`
  lines: -
  excerpt: |
    ParseError: Expected table name but got { (Jinja template)

## Notes

Postgres column recovery on parseable files ≈ 100%; whole-corpus recovery is bounded by the 6 file failures → the spike-1 threshold (≥95% columns) is reachable only with per-statement isolation. BigQuery/T-SQL corpora were not available in-repo.
