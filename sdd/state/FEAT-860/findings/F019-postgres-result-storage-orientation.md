---
id: F019
query_id: Q005
type: wiki_query
intent: "Orient on PostgresResultStorage (crew_executions) as the nearest Postgres crew storage pattern."
executed_at: 2026-11-09T17:13:06Z
duration_ms: 330
parent_id: null
depth: 0
merged_from: [FW-009]
---

# F019 — Postgres crew storage today is the FEAT-147/FEAT-307 ResultStorage family (results, not definitions)

## Summary

The query surfaces only execution-result storage: `PostgresResultStorage` (FEAT-147, read API FEAT-307), its
Redis/DocumentDB siblings behind a `ResultStorage` ABC + factory, the `CrewExecutionHistoryHandler`, and their
tests under `tests/bots/flows/core/storage/` and `tests/unit/`. The ResultStorage family is the closest
precedent for a pluggable Redis|Postgres crew backend (ABC + factory + per-backend class).

## Citations

- path: `packages/ai-parrot/src/parrot/bots/flows/core/storage/backends/postgres.py`
  lines: 28-28
  symbol: `PostgresResultStorage`
  excerpt: |
    wiki score=16.79 — "PostgresResultStorage — Postgres backend for crew/flow execution results (FEAT-147)."

- path: `packages/ai-parrot/src/parrot/bots/flows/core/storage/backends/base.py`
  symbol: `ResultStorage`
  excerpt: |
    wiki score=9.97 — "ResultStorage abstract base class for pluggable crew/flow result persistence."

- path: `packages/ai-parrot/src/parrot/bots/flows/core/storage/backends/factory.py`
  excerpt: |
    "Factory for resolving ResultStorage backends by name, instance, or env var."

- path: `tests/bots/flows/core/storage/test_postgres_backend.py`
  excerpt: |
    wiki score=33.85 — "Unit tests for PostgresResultStorage backend."

- path: `tests/unit/test_postgres_result_storage_read.py`
  excerpt: |
    wiki score=28.94 — "Unit tests for PostgresResultStorage read methods (FEAT-307)."

- path: `sdd/specs/crew-result-storage-backends.spec.md`
  excerpt: |
    FEAT-147 spec for the pluggable result storage backends

## Notes

Test files for this family live at the repo-root `tests/` tree, not under `packages/<dist>/tests/`.
