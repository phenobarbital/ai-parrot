---
id: F001
query_id: Q013, Q030, Q031
type: read
intent: "How the semantic layer runs SQL today and every in-process DuckDB usage in package sources."
executed_at: 2026-11-11T22:45:00Z
duration_ms: 0
parent_id: null
depth: 1
lane_ids: [FC-003, FW-002]
---

# F001 — DuckDB today is only a *queried database*: one short-lived `duckdb.connect()` per query in `DuckDBSource`; nobody registers frames or returns Arrow

## Summary

*(FC-003)* The semantic `Executor` runs a `GovernedQuery` through `DatabaseQueryToolkit.get_source(driver).query(creds, sql)`
with credentials from `ConnectionResolver` (driver defaults overlaid with `PARROT_SEMANTIC_CONN_<NAME>_<KEY>`
env vars). It returns `(rows: list[dict], row_count, truncated, duration_ms, columns)` — dict rows, with
truncation detected by a `limit + 1` probe. For `driver == "duckdb"` the resolver defaults `read_only=True`.
The only `import duckdb` / `duckdb.connect` in package sources (tests and `build/` excluded) is
`parrot/tools/databasequery/sources/duckdb.py`: a new connection per call inside `asyncio.to_thread`,
`fetchall()` into dict rows, connection closed in `finally`; `read_only` is ignored for `:memory:`.
No source calls `con.register(...)`, `fetch_arrow_table()` or keeps a root connection with per-thread
cursors; no `require_extra("duckdb", ...)` call exists. Inside `ai-parrot-semantic/src` the word `duckdb`
appears only in `execution.py` (read-only default) and `engines/native.py` (`_FILTER_DIALECTS`).

*(FW-002)* `execution.py` has two classes: `ConnectionResolver` (credentials = driver defaults overlaid with `PARROT_SEMANTIC_CONN_<CONNECTION>_<KEY>` env vars; for `driver == "duckdb"` it sets `read_only=True` by default) and `Executor`, which calls `toolkit.get_source(governed.driver)` then `source.query(creds, governed.sql)` and returns row dicts, trimming to `governed.limit` and reporting `truncated`. Its only outgoing references (wiki_related) are `parrot/interfaces/database.py` and `parrot/tools/databasequery/toolkit.py`; its only inbound reference is `tests/test_execution.py`. The stock DuckDB source (`databasequery/sources/duckdb.py`) was repaired in TASK-4708 to open one per-call connection inside `asyncio.to_thread` and close it in `finally`. Nothing in this path registers Arrow tables or DataFrames, and results are `list[dict]`, not Arrow. A saved lesson records that the layer has no cross-connection check.

## Citations

- path: `packages/ai-parrot-semantic/src/parrot/semantic/execution.py`
  lines: 18-49
  symbol: `ConnectionResolver.resolve`
  excerpt: |
    PREFIX = "PARROT_SEMANTIC_CONN_"
    creds: dict[str, Any] = dict(get_default_credentials(driver) or {})
    ...
    if driver == "duckdb":
        # Governed SQL never writes: open DuckDB files read-only unless the host overrides it.
        creds.setdefault("read_only", True)
    return creds

- path: `packages/ai-parrot-semantic/src/parrot/semantic/execution.py`
  lines: 52-90
  symbol: `Executor.run_with_columns`
  excerpt: |
    class Executor:
        """Run governed SQL through a DatabaseQueryToolkit source."""
        async def run_with_columns(self, governed: GovernedQuery, *, connection: str
        ) -> tuple[list[dict], int, bool, int, list[str]]:
            source = self.toolkit.get_source(governed.driver)
            creds = self.resolver.resolve(connection, governed.driver)
            result = await source.query(creds, governed.sql)
            all_rows = list(result.rows or [])
            truncated = len(all_rows) > governed.limit
            rows = all_rows[: governed.limit]

- path: `packages/ai-parrot-semantic/src/parrot/semantic/execution.py`
  lines: 11-12
  symbol: `imports`
  excerpt: |
    from parrot.interfaces.database import get_default_credentials
    from parrot.tools.databasequery.toolkit import DatabaseQueryToolkit

- path: `packages/ai-parrot/src/parrot/tools/databasequery/sources/duckdb.py`
  lines: 32-32
  symbol: `DuckDBSource`
  excerpt: |
    class DuckDBSource(AbstractDatabaseSource):

- path: `packages/ai-parrot/src/parrot/tools/databasequery/sources/duckdb.py`
  lines: 77-86
  symbol: `DuckDBSource._read_only`
  excerpt: |
    def _read_only(credentials: dict[str, Any]) -> bool:
        value = credentials.get("read_only", False)
        return bool(value) and DuckDBSource._database(credentials) != ":memory:"

- path: `packages/ai-parrot/src/parrot/tools/databasequery/sources/duckdb.py`
  lines: 110-156
  symbol: `DuckDBSource._execute_sync`
  excerpt: |
    try:
        import duckdb
    except ModuleNotFoundError as exc:
        ...
    connection = duckdb.connect(database=database, read_only=read_only)
    try:
        cursor = connection.execute(sql, params) if params is not None else connection.execute(sql)
        raw_rows = cursor.fetchall()
        rows = [dict(zip(columns, row, strict=True)) for row in raw_rows]
    finally:
        connection.close()

- path: `packages/ai-parrot/src/parrot/tools/databasequery/sources/duckdb.py`
  lines: 158-174
  symbol: `DuckDBSource._execute`
  excerpt: |
    return await asyncio.to_thread(self._execute_sync, self._database(credentials), sql, params,
                                   one=one, read_only=self._read_only(credentials))

- path: `packages/ai-parrot-semantic/src/parrot/semantic/engines/native.py`
  lines: 20-20
  symbol: `_FILTER_DIALECTS`
  excerpt: |
    _FILTER_DIALECTS = frozenset({"duckdb", "postgres"})

- wiki: `file:packages/ai-parrot-semantic/src/parrot/semantic/execution.py` (Q002 score=0.28)

- wiki: `file:packages/ai-parrot-semantic/tests/test_execution.py` (Q002 score=1.00)

- wiki: `file:sdd/tasks/completed/TASK-4708-semantic-duckdb-source-repair.md` (Q002 score=0.01)

- wiki: `mem-40bea21d8186` (Q002 score=0.13, category lesson)

- path: `packages/ai-parrot-semantic/src/parrot/semantic/execution.py`
  lines: 92
  symbol: `Executor.run`
  excerpt: |
    async def run(self, governed: GovernedQuery, *, connection: str) -> tuple[list[dict], int, bool, int]:

- path: `sdd/tasks/completed/TASK-4708-semantic-duckdb-source-repair.md`
  lines: 1-25
  symbol: `Scope`
  excerpt: |
    - Manually reapply branch b9f9983d67 behavior to current DuckDBSource: lazy duckdb import, one per-call connection in asyncio.to_thread, close in finally; preserve all existing source APIs.

## Notes

*(FC-003)*
- The semantic layer executes through **`DatabaseQueryToolkit`** (`parrot.tools.databasequery`), not through
  `SQLToolkit` (`parrot.bots.database.toolkits.sql`) which the old FEAT-713 spec chose for its
  `DatabaseRunner`. Two different execution stacks exist in core.
- A fresh `:memory:` connection per query means frames cannot be handed to `DuckDBSource`: there is no
  place to register an Arrow table that survives into the query. A frame-backed DuckDB runtime is new code.
- 25 test files under `packages/ai-parrot-semantic/tests/` mention duckdb (fixtures, e2e gate); they were
  located by name only, not opened.
- Grep scope excluded `tests/` and `build/`; `packages/ai-parrot/build/lib.*` holds stale copies of core
  modules and must be ignored when grepping.
*(FW-002)*
- Lesson `mem-40bea21d8186` (verified 2026-10-29 at e00c8de82): the named connection is read only from the ROOT model's policy (`toolkit.py:315,485`) and is otherwise only a compile-cache key component; no connection-mismatch error exists.
- The old FEAT-713 spec's `DatabaseRunner` targeted `SQLToolkit.execute_query`; the path that exists in the package it now lives in is `Executor` over `DatabaseQueryToolkit`. Its `DuckDBRunner` (root in-memory connection, Arrow `register`, per-thread cursor) has no counterpart: the existing DuckDB path needs a database *file* reachable through credentials.
- `DuckDBSource` line numbers are second-hand (from the task file's contract of 2026-10-25) — [cross-lane: type=read, intent=re-verify DuckDBSource class/line anchors and whether it accepts an in-memory database or an injected connection in packages/ai-parrot/src/parrot/tools/databasequery/sources/duckdb.py]
