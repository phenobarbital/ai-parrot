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

### Module 2: Source-layer test_connection overrides

- **Path**: All files in `packages/ai-parrot/src/parrot/tools/databasequery/sources/`
- **Responsibility**: Override `test_connection` on non-SQL sources where
  `SELECT 1` is not valid (MongoDB → `ping`, Elastic → cluster health,
  InfluxDB → `buckets()`).
- **Depends on**: Module 1

### Module 3: Toolkit refactor (toolkit.py)

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
- **Depends on**: Module 1, Module 2

### Module 4: Legacy tool cleanup (tool.py)

- **Path**: `packages/ai-parrot/src/parrot/tools/databasequery/tool.py`
- **Responsibility**:
  - Remove the local `QueryValidator` class (lines 314-448) — import from
    `parrot.security` instead.
  - Remove the local `DriverInfo` class (lines 29-199) — import
    `normalize_driver` from `parrot.tools.databasequery.sources` and
    `QueryLanguage` from `parrot.security`.
  - Remove `get_default_credentials` free function (lines 202-208) —
    unused after source layer handles defaults.
  - Clean up unused imports.
  - Keep `DatabaseQueryTool` functional — it remains the legacy entry point.
  - **Note**: `_add_row_limit`, `_get_default_credentials`,
    `_execute_database_query` stay as-is (they are internal to the legacy tool).
    Only the duplicated *classes* are removed.
- **Depends on**: Module 3 (to verify toolkit is complete before trimming legacy)

### Module 5: Update __init__.py exports and tests

- **Path**: `packages/ai-parrot/src/parrot/tools/databasequery/__init__.py`
  and `tests/`
- **Responsibility**:
  - Export `add_row_limit` from `__init__.py` if useful to external callers.
  - Add unit tests for each new toolkit method.
  - Add a deprecation test that `validate_database_query` still works
    (if we keep a compat alias) or verify it's gone.
- **Depends on**: Module 3, Module 4

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_add_row_limit_sql` | M1 | Injects `LIMIT N` for SQL drivers |
| `test_add_row_limit_flux` | M1 | Injects `\|> limit(n: N)` for InfluxDB |
| `test_add_row_limit_elastic` | M1 | Sets `size` in JSON body for Elastic |
| `test_add_row_limit_already_present` | M1 | Does not double-limit |
| `test_source_test_connection_pg` | M2 | PostgresSource.test_connection returns True |
| `test_source_test_connection_mongo` | M2 | MongoSource.test_connection uses ping |
| `test_toolkit_validate_query` | M3 | Renamed method works, no credentials param |
| `test_toolkit_get_table_metadata` | M3 | Returns metadata for single table |
| `test_toolkit_test_connection` | M3 | Delegates to source.test_connection |
| `test_toolkit_save_result_csv` | M3 | Writes CSV, returns file info |
| `test_toolkit_save_result_excel` | M3 | Writes Excel, returns file info |
| `test_toolkit_save_result_json` | M3 | Writes JSON, returns file info |
| `test_toolkit_max_rows` | M3 | execute_database_query injects limit |
| `test_post_execute_serializes_models` | M3 | BaseModel results become dicts |
| `test_legacy_tool_still_works` | M4 | DatabaseQueryTool._execute unchanged |
| `test_legacy_tool_no_local_queryvalidator` | M4 | Uses parrot.security import |

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
```

### Existing Class Signatures

```python
# parrot/tools/toolkit.py
class AbstractToolkit(ABC):
    tool_prefix: Optional[str] = None                     # line 219
    prefix_separator: str = "_"                            # line 222
    exclude_tools: tuple[str, ...] = ()                   # line 205
    base_url: str = BASE_STATIC_URL                       # line 200

    def __init__(self, **kwargs): ...                      # line 224
    async def _pre_execute(self, tool_name, **kwargs): ... # line 261
    async def _post_execute(self, tool_name, result, **kwargs) -> Any: ...  # line 276
    def get_tools(self, ...) -> List[AbstractTool]: ...    # line 292
    async def cleanup(self) -> None: ...                   # line 254
    async def start(self) -> None: ...                     # line 240
    async def stop(self) -> None: ...                      # line 247

# parrot/tools/databasequery/base.py
class AbstractDatabaseSource(ABC):
    driver: str                                            # line 199
    sqlglot_dialect: str | None = None                     # line 200

    async def resolve_credentials(self, credentials): ...  # line 202
    async def get_default_credentials(self) -> dict: ...   # line 216 (abstract)
    async def validate_query(self, query) -> ValidationResult: ...  # line 225
    async def get_metadata(self, credentials, tables?) -> MetadataResult: ...  # line 271 (abstract)
    async def query(self, credentials, sql, params?) -> QueryResult: ...       # line 288 (abstract)
    async def query_row(self, credentials, sql, params?) -> RowResult: ...     # line 305 (abstract)
    def _get_db(self, asyncdb_driver, dsn, params) -> Any: ...                 # line 328
    async def close(self) -> None: ...                     # line 358

# parrot/tools/databasequery/toolkit.py (current)
class DatabaseQueryToolkit(AbstractToolkit):
    tool_prefix: Optional[str] = "dq"                      # line 133
    exclude_tools: tuple[str, ...] = ("get_source", "cleanup", "start", "stop")  # line 138

    def __init__(self, **kwargs): ...                       # line 140
    def get_source(self, driver) -> AbstractDatabaseSource: ...  # line 151
    async def cleanup(self) -> None: ...                    # line 169
    async def get_database_metadata(self, driver, credentials?, tables?) -> dict: ...  # line 183
    async def validate_database_query(self, driver, query, credentials?) -> dict: ...  # line 214
    async def execute_database_query(self, driver, query, credentials?, params?) -> dict: ...  # line 251
    async def fetch_database_row(self, driver, query, credentials?, params?) -> dict: ...  # line 285

# parrot/security/query_validator.py
class QueryLanguage(str, Enum):                            # line 19
    SQL = "sql"
    FLUX = "flux"
    MQL = "mql"
    JSON = "json"
    # ... others

class QueryValidator:                                      # line 29
    @staticmethod
    def validate_sql_query(query: str) -> Dict[str, Any]: ...   # line 32
    @staticmethod
    def validate_flux_query(query: str) -> Dict[str, Any]: ...  # (exists)
    @classmethod
    def validate_query(cls, query, query_language) -> Dict[str, Any]: ...  # (exists)
    @staticmethod
    def validate_elasticsearch_query(query: str) -> Dict[str, Any]: ...  # (exists)
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `DatabaseQueryToolkit.test_connection` | `AbstractDatabaseSource.test_connection` | method call | base.py (to be added) |
| `DatabaseQueryToolkit.save_result` | `pd.DataFrame.to_csv/to_excel/to_json` | pandas | external dep |
| `DatabaseQueryToolkit._post_execute` | `AbstractToolkit._post_execute` | override | toolkit.py:276 |
| `add_row_limit()` | `normalize_driver()` | function call | sources/__init__.py:45 |
| `add_row_limit()` | `_DRIVER_TO_QUERY_LANGUAGE` | dict lookup | toolkit.py:36 |

### Does NOT Exist (Anti-Hallucination)

- ~~`AbstractToolkit.output_dir`~~ — does not exist; only `AbstractTool` has it
- ~~`AbstractToolkit.static_dir`~~ — does not exist; only `AbstractTool` has it
- ~~`AbstractToolkit.to_static_url()`~~ — does not exist; only `AbstractTool` has it
- ~~`AbstractDatabaseSource.test_connection()`~~ — does not exist yet (Module 1 adds it)
- ~~`base.add_row_limit()`~~ — does not exist yet (Module 1 adds it)
- ~~`DatabaseQueryToolkit.validate_query()`~~ — does not exist yet (Module 3 renames it)
- ~~`DatabaseQueryToolkit.save_result()`~~ — does not exist yet (Module 3 adds it)
- ~~`parrot.tools.databasequery.DriverInfo`~~ — exists only in `tool.py` locally, not exported from the package

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Toolkit tool discovery**: public async methods are auto-discovered by
  `AbstractToolkit._generate_tools()`. Method name becomes tool name
  (prefixed with `dq_`). Docstring becomes tool description for the LLM.
- **Source delegation**: toolkit methods resolve a source via `get_source(driver)`,
  resolve credentials via `source.resolve_credentials(credentials)`, then
  call the source method. Keep this pattern for new methods.
- **DDL guard**: every query-executing path must call
  `QueryValidator.validate_query()` before reaching the source. This is
  already done for `execute_database_query` and `fetch_database_row` — maintain it.
- **`_post_execute` for serialisation**: return Pydantic models from methods.
  Override `_post_execute` to call `result.model_dump()` if `isinstance(result, BaseModel)`.
  This keeps internal code typed while the LLM gets plain dicts.

### Known Risks / Gotchas

- **`save_result` needs an output directory.** `AbstractToolkit` does not have
  `output_dir` or `static_dir`. `DatabaseQueryToolkit.__init__` must accept
  `output_dir` as an optional kwarg and store it. If not configured, `save_result`
  should return an error dict rather than raising.
- **Renaming `validate_database_query` → `validate_query` changes tool name.**
  The LLM-facing tool changes from `dq_validate_database_query` to
  `dq_validate_query`. This is a breaking change for any agent prompt that
  hardcodes the old name. Document in release notes.
- **`add_row_limit` for MongoDB/MQL.** The legacy tool uses `limit` as a
  parameter to `conn.query()`, not injected into the query string. The helper
  should return the original query unchanged for MQL and let the source
  pass `limit` separately. Consider adding `max_rows` to the source
  `query()` signature or handling it in the toolkit before delegating.
- **`tool.py` local `QueryValidator` removal.** The legacy tool's
  `QueryValidator` is identical to `parrot.security.QueryValidator` except
  for a `print()` debug statement (tool.py:351). Remove the `print` and
  switch to the shared import.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `pandas` | `>=2.0` | DataFrame construction for `save_result` |
| `openpyxl` | `>=3.0` | Excel export in `save_result` (optional, lazy import) |
| `pydantic` | `>=2.0` | Result models |
| `sqlglot` | `>=20.0` | SQL validation (already present) |

---

## 8. Open Questions

- [ ] Should `save_result` be an LLM-callable tool or an internal helper?
  If the LLM calls it, it needs the raw result dict from a prior
  `execute_database_query` call. — *Owner: Jesus*
- [ ] Should we keep a deprecated `validate_database_query` alias that
  logs a warning and delegates to `validate_query`, or remove it outright?
  — *Owner: Jesus*
- [ ] Should `max_rows` have a global default (e.g. 10000) or per-driver
  defaults? The legacy tool uses 10000 for SQL and 20 for MongoDB.
  — *Owner: Jesus*
- [ ] Should `add_row_limit` live in `base.py` (shared) or stay as a
  toolkit-level private method? The source layer could also use it.
  — *Owner: Jesus*

---

## Worktree Strategy

- **Isolation unit**: per-spec (sequential tasks)
- All five modules modify overlapping files (`base.py`, `toolkit.py`,
  `tool.py`, source files) — parallel execution would cause conflicts.
- **Cross-feature dependencies**: None. FEAT-105 is already merged.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-04-29 | Jesus Lara | Initial draft |
