---
id: F012
query_id: Q066
type: git_log
intent: "Commits that fixed governed DuckDB connections (read-only) and the DuckDB driver workaround of TASK-4478."
executed_at: 2026-11-11T22:36:00Z
duration_ms: 600
parent_id: null
depth: 0
lane_ids: [FG-006]
---

# F012 — DuckDB in the semantic layer goes through the databasequery DuckDB source; governed connections were made read-only on 2026-10-26

## Summary

Four commits in 60 days mention DuckDB. The relevant one is `ae7e21f16a`: it made governed DuckDB
connections read-only and disambiguated duplicate column names, touching the semantic executor **and** the
core DuckDB source of the database-query toolkit (`parrot/tools/databasequery/sources/duckdb.py`). So the
semantic layer already executes on DuckDB, through a file-backed, read-only databasequery source — not
through an in-process connection with Arrow-registered frames. The DuckDB end-to-end security gate is
`tests/test_e2e_governed.py` (TASK-4478). The "DuckDB driver workaround" is only an SDD note on the task
contract (`5daf5bdc00`, outside the 60-day code log).

## Citations



## Notes

- Design consequence for the revision: the old spec's `DatabaseRunner` targeted `SQLToolkit.execute_query`,
  while the shipped layer executes through the databasequery sources; and "read-only governed DuckDB" is a
  constraint the old `DuckDBRunner` (in-memory, `con.register`) never considered.
- [cross-lane: type=read, intent=read parrot/tools/databasequery/sources/duckdb.py and semantic/execution.py to state how a DuckDB connection is opened read-only and whether an in-memory / Arrow-registered variant exists]
