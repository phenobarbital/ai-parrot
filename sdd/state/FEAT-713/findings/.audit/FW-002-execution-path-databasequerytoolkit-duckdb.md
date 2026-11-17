---
id: FW-002
query_id: Q002
type: wiki_query
intent: "Orient: how the semantic layer executes SQL and on which engines (DuckDB, database toolkit). Includes Q008 (wiki_related of execution.py)."
executed_at: 2026-11-11T22:40:00Z
duration_ms: 0
parent_id: null
depth: 1
---

# FW-002 — The semantic layer executes governed SQL only through `DatabaseQueryToolkit` sources with env-resolved named connections; DuckDB is a *queried database file* opened read-only, never an in-process engine over registered frames

## Summary

`execution.py` has two classes: `ConnectionResolver` (credentials = driver defaults overlaid with `PARROT_SEMANTIC_CONN_<CONNECTION>_<KEY>` env vars; for `driver == "duckdb"` it sets `read_only=True` by default) and `Executor`, which calls `toolkit.get_source(governed.driver)` then `source.query(creds, governed.sql)` and returns row dicts, trimming to `governed.limit` and reporting `truncated`. Its only outgoing references (wiki_related) are `parrot/interfaces/database.py` and `parrot/tools/databasequery/toolkit.py`; its only inbound reference is `tests/test_execution.py`. The stock DuckDB source (`databasequery/sources/duckdb.py`) was repaired in TASK-4708 to open one per-call connection inside `asyncio.to_thread` and close it in `finally`. Nothing in this path registers Arrow tables or DataFrames, and results are `list[dict]`, not Arrow. A saved lesson records that the layer has no cross-connection check.

## Citations

- wiki: `file:packages/ai-parrot-semantic/src/parrot/semantic/execution.py` (Q002 score=0.28)
- wiki: `file:packages/ai-parrot-semantic/tests/test_execution.py` (Q002 score=1.00)
- wiki: `file:sdd/tasks/completed/TASK-4708-semantic-duckdb-source-repair.md` (Q002 score=0.01)
- wiki: `mem-40bea21d8186` (Q002 score=0.13, category lesson)

- path: `packages/ai-parrot-semantic/src/parrot/semantic/execution.py`
  lines: 18-49
  symbol: `ConnectionResolver.resolve`
  excerpt: |
    PREFIX = "PARROT_SEMANTIC_CONN_"
    creds: dict[str, Any] = dict(get_default_credentials(driver) or {})
    if driver == "duckdb":
        # Governed SQL never writes: open DuckDB files read-only unless the host overrides it.
        creds.setdefault("read_only", True)

- path: `packages/ai-parrot-semantic/src/parrot/semantic/execution.py`
  lines: 52-90
  symbol: `Executor.run_with_columns`
  excerpt: |
    class Executor:
        """Run governed SQL through a DatabaseQueryToolkit source."""
        source = self.toolkit.get_source(governed.driver)
        creds = self.resolver.resolve(connection, governed.driver)
        result = await source.query(creds, governed.sql)
        truncated = len(all_rows) > governed.limit

- path: `packages/ai-parrot-semantic/src/parrot/semantic/execution.py`
  lines: 92
  symbol: `Executor.run`
  excerpt: |
    async def run(self, governed: GovernedQuery, *, connection: str) -> tuple[list[dict], int, bool, int]:

- path: `packages/ai-parrot/src/parrot/tools/databasequery/sources/duckdb.py`
  lines: 29-67
  symbol: `DuckDBSource`
  excerpt: |
    class DuckDBSource(AbstractDatabaseSource):          # :29 (as cited in TASK-4708's contract, verified at c431642e2)
        async def get_metadata(self, credentials: dict[str, Any], tables: list[str] | None=None) -> MetadataResult:   # :67

- path: `sdd/tasks/completed/TASK-4708-semantic-duckdb-source-repair.md`
  lines: 1-25
  symbol: `Scope`
  excerpt: |
    - Manually reapply branch b9f9983d67 behavior to current DuckDBSource: lazy duckdb import, one per-call connection in asyncio.to_thread, close in finally; preserve all existing source APIs.

## Notes

- Lesson `mem-40bea21d8186` (verified 2026-10-29 at e00c8de82): the named connection is read only from the ROOT model's policy (`toolkit.py:315,485`) and is otherwise only a compile-cache key component; no connection-mismatch error exists.
- The old FEAT-713 spec's `DatabaseRunner` targeted `SQLToolkit.execute_query`; the path that exists in the package it now lives in is `Executor` over `DatabaseQueryToolkit`. Its `DuckDBRunner` (root in-memory connection, Arrow `register`, per-thread cursor) has no counterpart: the existing DuckDB path needs a database *file* reachable through credentials.
- `DuckDBSource` line numbers are second-hand (from the task file's contract of 2026-10-25) — [cross-lane: type=read, intent=re-verify DuckDBSource class/line anchors and whether it accepts an in-memory database or an injected connection in packages/ai-parrot/src/parrot/tools/databasequery/sources/duckdb.py]
