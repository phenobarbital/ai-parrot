---
id: F017
query_id: Q017/Q021
type: read+grep
intent: `.sql` is scanned into file: pages; 32 tracked .sql files form the DDL-ingest corpus
executed_at: 2026-09-24T20:41:46+00:00
duration_ms: 0
parent_id: null
depth: 0
---

# F017 — `.sql` is scanned into file: pages; 32 tracked .sql files form the DDL-ingest corpus

## Summary

file_suffixes.py L38 lists '.sql'. `git ls-files '*.sql'` → 32 files: sdd/migrations 10, packages/parrot-formdesigner/migrations 5, packages/ai-parrot-server/src/parrot/handlers/models 4, packages/ai-parrot/tests/fixtures/bot_rows 2, packages/ai-parrot-pipelines/src/parrot_pipelines 2, tools/working_memory/task_memory/migrations 1, storage/security_reports 1, security 1, plus docker/matrix, examples, advisors catalog, observability clickhouse-init.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/file_suffixes.py`
  lines: 38
  excerpt: |
    ".sql",
- path: `packages/parrot-formdesigner/migrations/`
  lines: -
  excerpt: |
    5 migration files 001…008
- path: `sdd/migrations/`
  lines: -
  excerpt: |
    10 FEAT-*.sql migrations
- path: `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/migrations/001_task_memory.sql`
  lines: -
  excerpt: |
    6 CREATE TABLE, 70 columns, 4 PK, 3 FK (F025)
