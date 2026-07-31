---
type: Wiki Overview
title: 'Feature Specification: database-toolkit-parity'
id: doc:sdd-specs-database-toolkit-parity-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: FEAT-105 (databasetoolkit-clash) migrated `DatabaseQueryTool` into the new
relates_to:
- concept: mod:parrot.conf
  rel: mentions
- concept: mod:parrot.interfaces.database
  rel: mentions
- concept: mod:parrot.security
  rel: mentions
- concept: mod:parrot.tools.abstract
  rel: mentions
- concept: mod:parrot.tools.databasequery
  rel: mentions
- concept: mod:parrot.tools.databasequery.base
  rel: mentions
- concept: mod:parrot.tools.databasequery.sources
  rel: mentions
- concept: mod:parrot.tools.toolkit
  rel: mentions
---

# Feature Specification: database-toolkit-parity

**Feature ID**: FEAT-136
**Date**: 2026-04-29
**Author**: Jesus Lara
**Status**: draft
**Target version**: next minor

---

## 1. Motivation & Business Requirements

### Problem Statement

FEAT-105 (databasetoolkit-clash) migrated `DatabaseQueryTool` into the new
`DatabaseQueryToolkit` (backed by `AbstractToolkit` + per-driver
`AbstractDatabaseSource` classes). The migration achieved structural goals
(naming, `AbstractToolkit` pattern, DDL guard via `parrot.security`), but
the toolkit is missing several capabilities that the original tool provides:

1. **No `test_connection` tool.** `DatabaseQueryTool.test_connection()`
   (tool.py:1107-1145) runs `SELECT 1` to verify connectivity. The toolkit
   offers no equivalent, so agents cannot verify a database is reachable
   before attempting queries.

2. **No `save_result` tool.** `DatabaseQueryTool.save_query_result()`
   (tool.py:1147-1206) exports query results to CSV, JSON, or Excel files
   and returns a downloadable URL. The toolkit has no file-export capability.

3. **No per-table metadata tool.** The current `get_database_metadata`
   returns the full schema. There is no way to request metadata for a single
   table by name without also fetching every other table — wasteful on
   large catalogues. A focused `get_table_metadata(driver, table, …)`
   would be more practical for LLM-driven exploration.

4. **`validate_database_query` is over-qualified.** The method name includes
   "database" redundantly (the toolkit is already database-scoped). Rename
   to `validate_query` for consistency with the source-layer method
   (`AbstractDatabaseSource.validate_query()`). Additionally, the current
   `credentials` parameter is accepted but never used — it should be removed.

5. **Pydantic result models are not surfaced.** `QueryResult`, `RowResult`,
   and `MetadataResult` exist in `base.py` and are returned by every source
   implementation, but the toolkit immediately calls `.model_dump()` on them,
   discarding the typed objects. Callers (including save_result) cannot
   benefit from the structured types. The toolkit should return the model
   instances and let `AbstractToolkit._post_execute` handle serialisation
   for the LLM.

6. **No row-limit enforcement.** `DatabaseQueryTool._add_row_limit()`
   (tool.py:692-739) injects dialect-specific `LIMIT` / `|> limit()` /
   `size` clauses. The toolkit delegates everything to the source layer
   which does not enforce limits, risking unbounded result sets.

7. **Unused imports in tool.py.** The legacy tool still carries imports
   (`os`, `TYPE_CHECKING`, `lazy_import`) that are partially cleaned up
   but the file still re-declares `QueryValidator` and `DriverInfo` locally
   instead of importing from `parrot.security` and
   `parrot.tools.databasequery.sources`.

8. **Source-layer credential resolution is a PG-only stub.** Every source's
   `get_default_credentials()` delegates to
   `parrot.interfaces.database.get_default_credentials(driver)`, which only
   supports PostgreSQL (returns `querysource.conf.default_dsn` for `pg` aliases,
   `None` for everything else). All non-PG sources effectively return `{}`
   — meaning the toolkit **cannot connect without explicit credentials** to
   MySQL, BigQuery, MongoDB, Atlas, DocumentDB, InfluxDB, Oracle, MSSQL,
   Elastic, ClickHouse, or DuckDB.

   Meanwhile, `DatabaseQueryTool._get_default_credentials()` (tool.py:533-675)
   has a rich 140-line method that reads `navconfig.config` env vars for
   **every** driver (e.g. `MYSQL_HOST`, `BIGQUERY_CREDENTIALS`,
   `MONGODB_HOST`, `INFLUX_TOKEN`, `DOCUMENTDB_HOSTNAME`, etc.). This is a
   critical functional regression: the toolkit path is broken for 11 of 13
   drivers when no credentials are provided.

   The fix is to migrate the per-driver credential logic from `tool.py` into
   each source's `get_default_credentials()` override, since each source
   already knows its driver-specific env var names. The interface function
   stays as a thin DSN-only helper. Then `DatabaseQueryTool` can also
   delegate to the sources, removing its own 140-line duplicate.

### Goals

- **G1** — Add `test_connection` tool to `DatabaseQueryToolkit`.
- **G2** — Add `save_result` tool to `DatabaseQueryToolkit` (CSV, JSON,
  Excel export with downloadable URL).
- **G3** — Add `get_table_metadata` tool for single-table schema lookup.
- **G4** — Rename `validate_database_query` → `validate_query` and remove
  the unused `credentials` parameter.
- **G5** — Return typed Pydantic models (`QueryResult`, `RowResult`,
  `MetadataResult`, `ValidationResult`) from toolkit methods instead of
  calling `.model_dump()` inline. Move serialisation to `_post_execute`.
- **G6** — Add `max_rows` parameter to `execute_database_query` and
  `fetch_database_row`; implement dialect-aware row-limit injection in
  the source layer (or a shared helper).
- **G7** — Clean up `tool.py` unused imports; reuse `parrot.security.QueryValidator`
  and `sources.normalize_driver` instead of local duplicates.
- **G8** — Expand `parrot.interfaces.database.get_default_credentials(driver)`
  to return a full credential `dict[str, Any]` for every supported driver
  (not just a DSN string for PG). This becomes the single source of truth
  for env-var-based credential resolution. Each source's
  `get_default_credentials()` calls the interface and applies driver-specific
  post-processing (e.g. DocumentDB adds SSL, Atlas normalizes DSN scheme).
  `DatabaseQueryTool._get_default_credentials()` also delegates to the
  interface, eliminating its 140-line inline dict.

### Non-Goals (explicitly out of scope)

- Removing `DatabaseQueryTool` — it remains as the legacy `AbstractTool`
  entry point. FEAT-105 G6 already guarantees backward compatibility.
- Adding new database drivers — driver parity is already complete.
- Changing the `dq_` tool prefix — already settled in FEAT-105.
- Output format negotiation (`pandas`, `arrow`, `native`) — the toolkit
  returns structured dicts/models; DataFrame conversion belongs in the
  agent layer or a future feature.

---

## 2. Architectural Design

### Overview

Extend `DatabaseQueryToolkit` with three new public async methods
(`test_connection`, `save_result`, `get_table_metadata`) and refactor one
existing method (`validate_database_query` → `validate_query`). Shift
`.model_dump()` from individual methods to a `_post_execute` hook so that
internal code can work with typed models while the LLM still receives
plain dicts.

Add a `max_rows` parameter to query methods and implement a shared
`add_row_limit()` helper in `base.py` that sources can call before
executing queries.

Migrate the per-driver default credential resolution from the legacy tool's
monolithic `_get_default_credentials()` into each source's
`get_default_credentials()` override, reading from `navconfig.config` env
vars. This closes the critical 11-of-13-driver credential gap in the toolkit
and removes 140 lines of duplicate code from `tool.py`.

### Component Diagram

```
DatabaseQueryToolkit (toolkit.py)
  ├── get_database_metadata(driver, credentials?, tables?)  → MetadataResult
  ├── get_table_metadata(driver, table, credentials?)       → MetadataResult     [NEW]
  ├── validate_query(driver, query)                         → ValidationResult   [RENAMED]
  ├── execute_database_query(driver, query, creds?, params?, max_rows?)  → QueryResult
  ├── fetch_database_row(driver, query, creds?, params?)    → RowResult
  ├── test_connection(driver, credentials?)                 → dict               [NEW]
  ├── save_result(result, filename?, file_format?)          → dict               [NEW]
  │
  ├── _post_execute(name, result, **kw) → dict              [NEW override]
  └── cleanup()                                             [existing, excluded]

base.py
  ├── add_row_limit(query, max_rows, driver) → str          [NEW shared helper]
  └── (existing models: QueryResult, RowResult, MetadataResult, ValidationResult)

AbstractDatabaseSource (base.py)
  └── test_connection(credentials) → bool                   [NEW abstract method]
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractToolkit` | inherits | `_post_execute` override for model→dict |
| `AbstractToolkit.exclude_tools` | uses | `save_result` excluded if no `output_dir` configured |
| `AbstractDatabaseSource` | extends | New `test_connection()` method on ABC |
| `parrot.security.QueryValidator` | uses | Unchanged — already wired in |
| `parrot.tools.databasequery.sources` | uses | `normalize_driver()`, `get_source_class()` |
| `parrot.conf.STATIC_DIR` | uses | For `save_result` output directory |

### Data Models

No new Pydantic models. Existing models in `base.py` are reused as-is:

```python
# base.py (unchanged)
class ValidationResult(BaseModel): ...   # line 85
class MetadataResult(BaseModel): ...     # line 133
class QueryResult(BaseModel): ...        # line 147
class RowResult(BaseModel): ...          # line 165
```

### New Public Interfaces

```python
# toolkit.py — new methods
class DatabaseQueryToolkit(AbstractToolkit):

    async def get_table_metadata(
        self,
        driver: str,
        table: str,
        credentials: Optional[dict[str, Any]] = None,
    ) -> MetadataResult:
        """Get schema metadata for a single table or collection."""

    async def validate_query(
        self,
        driver: str,
        query: str,
    ) -> ValidationResult:
        """Validate a query for safety and syntax (renamed from validate_database_query)."""

    async def test_connection(
        self,
        driver: str,
        credentials: Optional[dict[str, Any]] = None,
    ) -> dict:
        """Test database connectivity. Returns status dict."""

    async def save_result(
        self,
        result: dict,
        filename: Optional[str] = None,
        file_format: str = "csv",
    ) -> dict:
        """Save a query result dict to CSV, JSON, or Excel file."""
```

```python
# base.py — new helper
def add_row_limit(query: str, max_rows: int, driver: str) -> str:
    """Inject dialect-specific row limit into a query string."""

# base.py — new abstract method
class AbstractDatabaseSource(ABC):
    async def test_connection(self, credentials: dict[str, Any]) -> bool:
        """Verify connectivity by running a trivial query."""
```

---

## 3. Module Breakdown

### Module 1: Row-limit helper and test_connection ABC method (base.py)

- **Path**: `packages/ai-parrot/src/parrot/tools/databasequery/base.py`
- **Responsibility**:
  - Add `add_row_limit(query, max_rows, driver)` free function — ported
    from `DatabaseQueryTool._add_row_limit()` (tool.py:692-739).
  - Add `async def test_connection(self, credentials) -> bool` to
    `AbstractDatabaseSource` with a default implementation that calls
    `self.query(credentials, "SELECT 1")` and checks for success.
    Non-SQL sources override it.
- **Depends on**: `sources.normalize_driver` (for dialect detection in
  `add_row_limit`).

### Module 2: Credential resolution — interface + source migration

- **Path**:
  - `packages/ai-parrot/src/parrot/interfaces/database.py` (expand interface)
  - All files in `packages/ai-parrot/src/parrot/tools/databasequery/sources/`
- **Responsibility**:

  **Step 2a — Expand `parrot.interfaces.database.get_default_credentials()`.**

  The current function (database.py:490-508) is a PG-only stub that returns
  `Optional[str]`. Expand it to:
  - Accept all supported drivers.
  - Return `dict[str, Any]` (full credential dict), not just a DSN string.
  - Read from `navconfig.config` env vars, using the same var names and
    fallback values as `DatabaseQueryTool._get_default_credentials()` (the
    authoritative reference at tool.py:554-660).
  - Return `{}` (not raise) when env vars are not set.
  - Signature change: `def get_default_credentials(driver: str) -> dict[str, Any]`

  Per-driver env var reference (from tool.py):

  | Driver | Env vars | Notes |
  |---|---|---|
  | `pg` | `PG_HOST`, `PG_PORT`, `PG_DATABASE`, `PG_USER`, `PG_PWD`/`PG_PASSWORD` | Also return `dsn` from `querysource.conf.default_dsn` |
  | `mysql` | `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_DATABASE`, `MYSQL_USER`, `MYSQL_PASSWORD` | |
  | `bigquery` | `BIGQUERY_CREDENTIALS`/`BIGQUERY_CREDENTIALS_PATH`, `BIGQUERY_PROJECT_ID` | `credentials` value is a resolved `Path` |
  | `sqlite` | `SQLITE_DATABASE` | Fallback `:memory:` |
  | `oracle` | `ORACLE_HOST`, `ORACLE_PORT`, `ORACLE_SERVICE_NAME`, `ORACLE_USER`, `ORACLE_PASSWORD` | |
  | `mssql` | `MSSQL_HOST`, `MSSQL_PORT`, `MSSQL_DATABASE`, `MSSQL_USER`, `MSSQL_PASSWORD` | |
  | `clickhouse` | `CLICKHOUSE_HOST`, `CLICKHOUSE_PORT`, `CLICKHOUSE_DATABASE`, `CLICKHOUSE_USER`, `CLICKHOUSE_PASSWORD` | New — not in legacy tool |
  | `duckdb` | (none) | Defaults to `:memory:` |
  | `influx` | `INFLUX_HOST`, `INFLUX_PORT`, `INFLUX_DATABASE`, `INFLUX_USERNAME`, `INFLUX_PASSWORD`, `INFLUX_TOKEN` (from `querysource.conf`), `INFLUX_ORG` | |
  | `mongo` | `MONGODB_HOST`, `MONGODB_PORT`, `MONGODB_DATABASE`, `MONGODB_USER`, `MONGODB_PASSWORD` | Add `dbtype: "mongodb"` |
  | `atlas` | `ATLAS_HOST`, `ATLAS_PORT`, `ATLAS_DATABASE`, `ATLAS_USER`, `ATLAS_PASSWORD` | Add `dbtype: "atlas"` |
  | `documentdb` | `DOCUMENTDB_HOSTNAME`, `DOCUMENTDB_PORT`, `DOCUMENTDB_DATABASE`, `DOCUMENTDB_USERNAME`, `DOCUMENTDB_PASSWORD`, `DOCUMENTDB_USE_SSL`, `DOCUMENTDB_COLLECTION` | Add `ssl`, `tlsCAFile`, `dbtype: "documentdb"` |
  | `elastic` | `ELASTICSEARCH_HOST`, `ELASTICSEARCH_PORT`, `ELASTICSEARCH_INDEX`, `ELASTICSEARCH_USER`, `ELASTICSEARCH_PASSWORD`, `ELASTICSEARCH_PROTOCOL`, `ELASTICSEARCH_CLIENT_TYPE` | |

  **Step 2b — Update each source's `get_default_credentials()` override.**

  Each source calls the expanded interface and applies any driver-specific
  post-processing:

  | Source | Post-processing needed |
  |---|---|
  | `PostgresSource` | Also include `dsn` key from `querysource.conf.default_dsn` |
  | `DocumentDBSource` | `setdefault("ssl", True)`, `setdefault("tlsCAFile", ...)` |
  | `AtlasSource` | Normalize DSN to `mongodb+srv://` scheme |
  | All others | Call interface, return as-is (strip `None` values) |

  Implementation pattern:
  ```python
  async def get_default_credentials(self) -> dict[str, Any]:
      from parrot.interfaces.database import get_default_credentials
      return get_default_credentials("mysql")
  ```

- **Depends on**: Module 1 (base.py changes)

### Module 3: Source-layer test_connection overrides

- **Path**: All files in `packages/ai-parrot/src/parrot/tools/databasequery/sources/`
- **Responsibility**: Override `test_connection` on non-SQL sources where
  `SELECT 1` is not valid (MongoDB → `ping`, Elastic → cluster health,
  InfluxDB → `buckets()`).
- **Depends on**: Module 1

### Module 4: Toolkit refactor (toolkit.py)

- **Path**: `packages/ai-parrot/src/parrot/tools/databasequery/toolkit.py`
- **Responsibility**:
  - Rename `validate_database_query` → `validate_query`, remove `credentials` param.
  - Add `get_table_metadata(driver, table, credentials?)` — delegates to
    `source.get_metadata(creds, tables=[table])`.
  - Add `test_connection(driver, credentials?)` — delegates to
    `source.test_connection(creds)`.
  - Add `save_result(result, filename?, file_format?)` — converts result dict
    back to DataFrame via `pd.DataFrame(result["rows"])`, writes to
    `output_dir`, returns file info dict.
  - Add `max_rows` parameter to `execute_database_query` and
    `fetch_database_row`; call `add_row_limit()` before delegating to source.
  - Stop calling `.model_dump()` in each tool method — return model instances.
  - Override `_post_execute` to call `.model_dump()` on any `BaseModel` result,
    so the LLM still receives plain dicts.
  - Accept `output_dir` / `static_dir` in `__init__` kwargs for `save_result`.
  - Update `exclude_tools` if needed.
- **Depends on**: Module 1, Module 2, Module 3

### Module 5: Legacy tool cleanup (tool.py)

- **Path**: `packages/ai-parrot/src/parrot/tools/databasequery/tool.py`
- **Responsibility**:
  - Remove the local `QueryValidator` class (lines 314-448) — import from
    `parrot.security` instead.
  - Remove the local `DriverInfo` class (lines 29-199) — import
    `normalize_driver` from `parrot.tools.databasequery.sources` and
    `QueryLanguage` from `parrot.security`.
  - Remove `get_default_credentials` free function (lines 202-208) —
    unused after source layer handles defaults.
  - Refactor `_get_default_credentials()` (lines 533-675) to delegate to
    `parrot.interfaces.database.get_default_credentials(driver)` (now expanded
    to all drivers). Merge result with `provided_credentials`. This removes
    ~140 lines of duplicated credential dicts. The DSN resolution for PG
    can also come from the interface dict's `dsn` key.
  - Remove `_validate_query_safety()` — use `QueryValidator` directly.
  - Clean up unused imports (`Enum`, redundant `json`, `Path`, etc.).
  - Keep `DatabaseQueryTool._execute()` functional — it remains the legacy
    entry point.
- **Depends on**: Module 2 (sources must have full credentials first),
  Module 4 (to verify toolkit is complete before trimming legacy)

### Module 6: Update __init__.py exports and tests

- **Path**: `packages/ai-parrot/src/parrot/tools/databasequery/__init__.py`
  and `tests/`
- **Responsibility**:
  - Export `add_row_limit` from `__init__.py` if useful to external callers.
  - Add unit tests for each new toolkit method.
  - Add unit tests for source-level `get_default_credentials()` (verify each
    source reads from the expected env vars when configured).
  - Add a deprecation test that `validate_database_query` still works
    (if we keep a compat alias) or verify it's gone.
- **Depends on**: Module 4, Module 5

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_add_row_limit_sql` | M1 | Injects `LIMIT N` for SQL drivers |
| `test_add_row_limit_flux` | M1 | Injects `\|> limit(n: N)` for InfluxDB |
| `test_add_row_limit_elastic` | M1 | Sets `size` in JSON body for Elastic |
| `test_add_row_limit_already_present` | M1 | Does not double-limit |
| `test_pg_source_default_creds` | M2 | PostgresSource reads PG_HOST etc. from navconfig |
| `test_mysql_source_default_creds` | M2 | MySQLSource reads MYSQL_HOST etc. from navconfig |
| `test_bigquery_source_default_creds` | M2 | BigQuerySource reads BIGQUERY_CREDENTIALS etc. |
| `test_mongo_source_default_creds` | M2 | MongoSource reads MONGODB_HOST etc. from navconfig |
| `test_elastic_source_default_creds` | M2 | ElasticSource reads ELASTICSEARCH_HOST etc. |
| `test_influx_source_default_creds` | M2 | InfluxSource reads INFLUX_HOST, INFLUX_TOKEN etc. |
| `test_documentdb_source_default_creds` | M2 | DocumentDBSource reads DOCUMENTDB_HOSTNAME + SSL |
| `test_source_default_creds_empty_when_no_env` | M2 | Sources return {} when no env vars set |
| `test_source_test_connection_pg` | M3 | PostgresSource.test_connection returns True |
| `test_source_test_connection_mongo` | M3 | MongoSource.test_connection uses ping |
| `test_toolkit_validate_query` | M4 | Renamed method works, no credentials param |
| `test_toolkit_get_table_metadata` | M4 | Returns metadata for single table |
| `test_toolkit_test_connection` | M4 | Delegates to source.test_connection |
| `test_toolkit_save_result_csv` | M4 | Writes CSV, returns file info |
| `test_toolkit_save_result_excel` | M4 | Writes Excel, returns file info |
| `test_toolkit_save_result_json` | M4 | Writes JSON, returns file info |
| `test_toolkit_max_rows` | M4 | execute_database_query injects limit |
| `test_post_execute_serializes_models` | M4 | BaseModel results become dicts |
| `test_legacy_tool_still_works` | M5 | DatabaseQueryTool._execute unchanged |
| `test_legacy_tool_delegates_creds` | M5 | _get_default_credentials delegates to source layer |
| `test_legacy_tool_no_local_queryvalidator` | M5 | Uses parrot.security import |

### Integration Tests

| Test | Description |
|---|---|
| `test_toolkit_roundtrip_pg` | get_metadata → execute_query → save_result on PG |
| `test_toolkit_test_connection_unreachable` | Returns error dict for bad host |

### Test Data / Fixtures

```python
@pytest.fixture
def toolkit():
    return DatabaseQueryToolkit(output_dir="/tmp/test_dq_output")

@pytest.fixture
def sample_query_result():
    return {
        "driver": "pg",
        "rows": [{"id": 1, "name": "test"}],
        "row_count": 1,
        "columns": ["id", "name"],
        "execution_time_ms": 12.5,
    }
```

---

## 5. Acceptance Criteria

- [ ] `dq_test_connection` tool exists and returns `{"status": "success"}` or `{"status": "error", "message": ...}`
- [ ] `dq_save_result` tool writes CSV/JSON/Excel and returns `{"file_path": ..., "file_url": ...}`
- [ ] `dq_get_table_metadata` tool returns metadata for a single table without fetching the full catalogue
- [ ] `dq_validate_query` tool exists (old `dq_validate_database_query` name is removed)
- [ ] `validate_query` does NOT accept a `credentials` parameter
- [ ] `execute_database_query` and `fetch_database_row` accept `max_rows: int` and inject dialect-specific limits
- [ ] Toolkit methods return Pydantic model instances internally; `_post_execute` serialises them to dicts for the LLM
- [ ] `tool.py` no longer contains a local `QueryValidator` class — imports from `parrot.security`
- [ ] `tool.py` no longer contains a local `DriverInfo` class — imports from `parrot.tools.databasequery.sources`
- [ ] `parrot.interfaces.database.get_default_credentials(driver)` returns `dict[str, Any]` for all supported drivers (PG, MySQL, BigQuery, SQLite, Oracle, MSSQL, ClickHouse, DuckDB, Influx, Mongo, Atlas, DocumentDB, Elastic)
- [ ] Every source's `get_default_credentials()` delegates to the interface and applies driver-specific post-processing
- [ ] `PostgresSource` returns both DSN and param dict (host/port/db/user/pw)
- [ ] `MySQLSource`, `BigQuerySource`, `MongoSource`, `ElasticSource`, `InfluxSource`, `OracleSource`, `MSSQLSource`, `DocumentDBSource` return non-empty credential dicts when env vars are set
- [ ] `DatabaseQueryTool._get_default_credentials()` delegates to the source layer — no longer contains inline credential dicts
- [ ] `DatabaseQueryTool._execute()` still works (legacy compat)
- [ ] All new unit tests pass: `pytest tests/tools/test_database_toolkit_parity.py -v`
- [ ] No breaking changes to `DatabaseQueryToolkit.get_tools()` output (tool names may change for renamed method)

---

## 6. Codebase Contract

### Verified Imports

```python
# Toolkit base class
from parrot.tools.toolkit import AbstractToolkit          # verified: toolkit.py:168
from parrot.tools.toolkit import ToolkitTool              # verified: toolkit.py:18

# Security — shared query validator
from parrot.security import QueryLanguage, QueryValidator  # verified: security/__init__.py:10-12

# Database source layer
from parrot.tools.databasequery.base import (
    AbstractDatabaseSource,    # verified: base.py:186
    MetadataResult,            # verified: base.py:133
    QueryResult,               # verified: base.py:147
    RowResult,                 # verified: base.py:165
    ValidationResult,          # verified: base.py:85
    ColumnMeta,                # verified: base.py:99
    TableMeta,                 # verified: base.py:117
)
from parrot.tools.databasequery.sources import (
    get_source_class,          # verified: sources/__init__.py:132
    normalize_driver,          # verified: sources/__init__.py:45
    register_source,           # verified: sources/__init__.py:69
)

# Static file config
from parrot.conf import STATIC_DIR                        # verified: used by AbstractTool

# Legacy tool
from parrot.tools.abstract import AbstractTool            # verified: abstract.py

# Configuration (env var access for source credentials)

…(truncated)…
