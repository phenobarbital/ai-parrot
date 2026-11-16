---
id: FG-006
query_id: Q066
type: git_log
intent: "Commits that fixed governed DuckDB connections (read-only) and the DuckDB driver workaround of TASK-4478."
executed_at: 2026-11-11T22:36:00Z
duration_ms: 600
parent_id: null
depth: 0
---

# FG-006 — DuckDB in the semantic layer goes through the databasequery DuckDB source; governed connections were made read-only on 2026-10-26

## Summary

Four commits in 60 days mention DuckDB. The relevant one is `ae7e21f16a`: it made governed DuckDB
connections read-only and disambiguated duplicate column names, touching the semantic executor **and** the
core DuckDB source of the database-query toolkit (`parrot/tools/databasequery/sources/duckdb.py`). So the
semantic layer already executes on DuckDB, through a file-backed, read-only databasequery source — not
through an in-process connection with Arrow-registered frames. The DuckDB end-to-end security gate is
`tests/test_e2e_governed.py` (TASK-4478). The "DuckDB driver workaround" is only an SDD note on the task
contract (`5daf5bdc00`, outside the 60-day code log).

## Citations

- commit: `ae7e21f16a` — 2026-10-26 — fix(semantic-layer): read-only governed DuckDB connections, disambiguate duplicate column names (issue:d126cab02311)
  files: `packages/ai-parrot-semantic/src/parrot/semantic/execution.py`,
  `packages/ai-parrot-semantic/tests/test_execution.py`,
  `packages/ai-parrot/src/parrot/tools/databasequery/sources/duckdb.py`,
  `packages/ai-parrot/tests/test_semantic_duckdb_source.py`
- commit: `19cfe52154` — 2026-10-26 — feat(semantic-layer): TASK-4478 — engine-committed coder deliverable
  files: `packages/ai-parrot-semantic/tests/test_e2e_governed.py`
- commit: `ef85c50353` — 2026-10-27 — fix(semantic-layer): wire real PBAC guard in agent example, scope env and owner checks (issue:f0da823294fb)
- commit: `7c0c64bb60` — 2026-10-27 — fix(ci): remove conflicting --package flag from semantic-layer sync
  files: `.github/workflows/ci.yml`
- commit: `86da277f2a` — 2026-09-15 — fix(stores/kb): drop unused duckdb import and repair stale tests (unrelated to the semantic layer)
- commit: `5daf5bdc00` — (earlier) — sdd: FEAT-704 — DuckDB driver workaround note in TASK-4478 contract (SDD-only; seen in the parent session's log, not re-queried)

## Notes

- Design consequence for the revision: the old spec's `DatabaseRunner` targeted `SQLToolkit.execute_query`,
  while the shipped layer executes through the databasequery sources; and "read-only governed DuckDB" is a
  constraint the old `DuckDBRunner` (in-memory, `con.register`) never considered.
- [cross-lane: type=read, intent=read parrot/tools/databasequery/sources/duckdb.py and semantic/execution.py to state how a DuckDB connection is opened read-only and whether an in-memory / Arrow-registered variant exists]
