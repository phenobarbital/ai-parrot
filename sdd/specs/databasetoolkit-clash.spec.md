# Feature Specification: databasetoolkit-clash

**Feature ID**: FEAT-105
**Date**: 2026-04-17
**Author**: Jesus Lara
**Status**: approved
**Target version**: next minor

---

## 1. Motivation & Business Requirements

### Problem Statement

FEAT-062 introduced a new multi-database toolkit at
`packages/ai-parrot/src/parrot/tools/database/toolkit.py` exporting a class
called `DatabaseToolkit`. That name already exists in
`packages/ai-parrot/src/parrot/bots/database/toolkits/base.py` — the
abstract base used by `SQLAgent` and all of its concrete toolkits (SQL,
Influx, Elastic, DocumentDB). The two classes are semantically unrelated:

- `parrot.bots.database.toolkits.base.DatabaseToolkit` — an
  `AbstractToolkit` ABC that wraps a single database connection and
  exposes lifecycle + schema + query tools via **public async methods**
  auto-discovered by `AbstractToolkit._generate_tools()`.
- `parrot.tools.database.toolkit.DatabaseToolkit` — a plain class that
  owns four hand-written `AbstractTool` subclasses
  (`GetDatabaseMetadataTool`, `ValidateDatabaseQueryTool`,
  `ExecuteDatabaseQueryTool`, `FetchDatabaseRowTool`) and returns them
  via `get_tools()`. It does **not** inherit from `AbstractToolkit`.

Beyond the name clash, the FEAT-062 toolkit has three substantive issues:

1. **Pattern inconsistency.** Every other toolkit in the codebase
   inherits `AbstractToolkit` and exposes tools as public async methods
   (e.g., `WebScrapingToolkit`, `SQLToolkit`, `InfluxDBToolkit`). The new
   `DatabaseToolkit` departs from that convention, making it harder to
   compose with the framework's toolkit plumbing (tool prefixing,
   permission filtering, `exclude_tools`).
2. **Missing DDL safety net.** The legacy `DatabaseQueryTool`
   (`packages/ai-parrot-tools/src/parrot_tools/databasequery.py:308`)
   runs every query through
   `parrot.security.QueryValidator.validate_query(query, query_language)`
   to block DDL/DML (`CREATE`, `DROP`, `INSERT`, `EXEC`, etc.). The new
   toolkit's `ValidateDatabaseQueryTool` only performs syntactic
   validation (via `sqlglot.parse`) — a syntactically valid `DROP TABLE`
   passes. This is a regression in a "read-only" tool.
3. **Legacy tool drift.** The original monolithic `DatabaseQueryTool`
   still lives in `parrot_tools/databasequery.py` (1064 lines) and is the
   target of the `TOOL_REGISTRY` entry
   `"database_query": "parrot_tools.databasequery.DatabaseQueryTool"`.
   There is no module path that co-locates the new toolkit with the
   legacy single-tool implementation, so users migrating between them
   have no obvious upgrade path.

### Goals

- **G1** — Eliminate the `DatabaseToolkit` name clash by renaming the
  FEAT-062 toolkit to `DatabaseQueryToolkit`.
- **G2** — Move the module from `parrot.tools.database` →
  `parrot.tools.databasequery`. Package all database-query-related code
  (sources, base types, toolkit, legacy tool) under one namespace.
- **G3** — Relocate the legacy monolithic tool from
  `parrot_tools/databasequery.py` into
  `parrot/tools/databasequery/tool.py` and re-export `DatabaseQueryTool`
  from the package's `__init__.py`.
- **G4** — Refactor `DatabaseQueryToolkit` to inherit from
  `AbstractToolkit` and expose its four capabilities as public async
  methods: `get_database_metadata`, `validate_database_query`,
  `execute_database_query`, `fetch_database_row`.
- **G5** — Wire `parrot.security.QueryValidator.validate_query(...)`
  into `DatabaseQueryToolkit.validate_database_query()` and
  (by invocation) into `execute_database_query` / `fetch_database_row`
  so DDL/DML are rejected before reaching the underlying source. Keep
  the sqlglot syntactic check as a second layer.
- **G6** — Preserve ALL public behavior of the existing
  `parrot_tools.databasequery.DatabaseQueryTool` — the class, its
  `args_schema`, its `TOOL_REGISTRY` entry, and any runtime imports of
  `from parrot_tools.databasequery import ...` must keep working via a
  thin compatibility shim.
- **G7** — `from parrot.tools.database import DatabaseToolkit` must
  continue to resolve for one deprecation cycle (alias that emits a
  `DeprecationWarning` and re-exports `DatabaseQueryToolkit`).

### Non-Goals (explicitly out of scope)

- Modifying `parrot.bots.database.toolkits.base.DatabaseToolkit` — that
  class is load-bearing for `SQLAgent` and we are *keeping* its name.
- Redesigning `AbstractDatabaseSource` / the `sources/` registry.
- Adding new database drivers.
- Changing `parrot.security.QueryValidator` internals.
- Migrating `parrot_tools.db.DatabaseTool` or `parrot_tools.multidb.EnhancedDatabaseTool` (separate legacy tools, unaffected).
- Building a shared async connection-pool layer between the two
  `DatabaseToolkit` implementations.

---

## 2. Architectural Design

### Overview

Restructure the module tree so "database query for agents" has exactly
one home — `parrot.tools.databasequery` — and the toolkit honors the
rest of the framework's toolkit contract (`AbstractToolkit` subclass
with public async methods). Layer `QueryValidator` safety on top of the
existing sqlglot syntax check.

### Component Diagram

```
BEFORE
======
parrot/tools/database/                          parrot_tools/
├── __init__.py  (exports DatabaseToolkit)       └── databasequery.py
├── toolkit.py   (DatabaseToolkit — plain class)      (DatabaseQueryTool — 1064 lines)
├── base.py      (AbstractDatabaseSource, results)
└── sources/     (pg, mysql, sqlite, ...)

parrot/bots/database/toolkits/base.py
└── DatabaseToolkit  ← AbstractToolkit ABC  (SQLAgent-facing, NAME CLASH)


AFTER
=====
parrot/tools/databasequery/                     parrot_tools/
├── __init__.py                                  └── databasequery.py
│     ├─ DatabaseQueryToolkit                         (compat shim:
│     ├─ DatabaseQueryTool  ← moved from               re-exports
│     │   parrot_tools/databasequery.py                DatabaseQueryTool
│     ├─ AbstractDatabaseSource                        from
│     └─ result models                                 parrot.tools.databasequery)
├── toolkit.py  (DatabaseQueryToolkit : AbstractToolkit)
├── tool.py     (DatabaseQueryTool — legacy monolith)
├── base.py     (unchanged — AbstractDatabaseSource, result models)
└── sources/    (unchanged)

parrot/tools/database.py  (shim re-exporting DatabaseQueryToolkit as
                            DatabaseToolkit with DeprecationWarning)

parrot/bots/database/toolkits/base.py
└── DatabaseToolkit  ← unchanged, no longer clashes semantically
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.tools.toolkit.AbstractToolkit` | base class | `DatabaseQueryToolkit` now inherits it |
| `parrot.security.QueryValidator` | consumer | Called from every public query method |
| `parrot.security.QueryLanguage` | mapped-from-driver | Driver → language resolution reused from legacy `DriverInfo.get_query_language` |
| `parrot.tools.databasequery.base.AbstractDatabaseSource` | moved (path rename only) | Stays the extension point |
| `parrot.tools.databasequery.sources.*` | moved (path rename only) | `@register_source` still works via the registry |
| `parrot.bots.database.toolkits.base.DatabaseToolkit` | unchanged | Kept — no functional change |
| `TOOL_REGISTRY["database_query"]` | repointed | `"parrot_tools.databasequery.DatabaseQueryTool"` → `"parrot.tools.databasequery.DatabaseQueryTool"` |
| `parrot_tools/databasequery.py` | compat shim | Keeps one-line `from parrot.tools.databasequery import DatabaseQueryTool` to preserve old imports |
| `parrot/tools/database.py` (new shim) | compat shim | `DatabaseToolkit = DatabaseQueryToolkit` with warning |

### Data Models

No new Pydantic models. Reuses existing `ValidationResult`, `ColumnMeta`,
`TableMeta`, `MetadataResult`, `QueryResult`, `RowResult` unchanged.

### New Public Interfaces

```python
# parrot/tools/databasequery/toolkit.py
from parrot.tools.toolkit import AbstractToolkit
from parrot.security import QueryValidator

class DatabaseQueryToolkit(AbstractToolkit):
    """Multi-database toolkit inheriting AbstractToolkit.

    Auto-generates 4 tools from the public async methods below via
    AbstractToolkit._generate_tools().
    """

    tool_prefix: Optional[str] = "db"   # produces db_get_database_metadata etc. — opt-in

    async def get_database_metadata(
        self,
        driver: str,
        credentials: dict[str, Any] | None = None,
        tables: list[str] | None = None,
    ) -> dict[str, Any]: ...

    async def validate_database_query(
        self,
        driver: str,
        query: str,
        credentials: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...

    async def execute_database_query(
        self,
        driver: str,
        query: str,
        credentials: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...

    async def fetch_database_row(
        self,
        driver: str,
        query: str,
        credentials: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...

    # non-tool helpers — excluded from auto-discovery
    exclude_tools: tuple[str, ...] = ("cleanup", "get_source")

    def get_source(self, driver: str) -> AbstractDatabaseSource: ...
    async def cleanup(self) -> None: ...
```

The four methods return `MetadataResult.model_dump()` / `ValidationResult.model_dump()` / `QueryResult.model_dump()` / `RowResult.model_dump()` — same payloads as today, just no `ToolResult` wrapper because `AbstractToolkit` does the wrapping itself.

```python
# parrot/tools/databasequery/__init__.py  (new — public exports)
from parrot.tools.databasequery.base import (
    AbstractDatabaseSource, ValidationResult, ColumnMeta, TableMeta,
    MetadataResult, QueryResult, RowResult,
)
from parrot.tools.databasequery.toolkit import DatabaseQueryToolkit
from parrot.tools.databasequery.tool import DatabaseQueryTool   # legacy monolith

__all__ = [
    "DatabaseQueryToolkit",
    "DatabaseQueryTool",
    "AbstractDatabaseSource",
    "ValidationResult", "ColumnMeta", "TableMeta",
    "MetadataResult", "QueryResult", "RowResult",
]
```

```python
# parrot/tools/database.py  (new compat shim — replaces parrot/tools/database/ package)
"""Deprecated alias — use parrot.tools.databasequery instead."""
import warnings
from parrot.tools.databasequery import (
    DatabaseQueryToolkit as DatabaseToolkit,
    AbstractDatabaseSource, ValidationResult, ColumnMeta, TableMeta,
    MetadataResult, QueryResult, RowResult,
)

warnings.warn(
    "parrot.tools.database is deprecated; import from parrot.tools.databasequery.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    "DatabaseToolkit",
    "AbstractDatabaseSource",
    "ValidationResult", "ColumnMeta", "TableMeta",
    "MetadataResult", "QueryResult", "RowResult",
]
```

---

## 3. Module Breakdown

### Module 1: Move package `parrot.tools.database` → `parrot.tools.databasequery`

- **Paths**:
  - `packages/ai-parrot/src/parrot/tools/database/` → `packages/ai-parrot/src/parrot/tools/databasequery/`
  - Move with `git mv` to preserve history.
- **Responsibility**: Mechanical rename. Update every intra-package
  import (`from parrot.tools.database...` → `from parrot.tools.databasequery...`)
  inside `base.py`, `toolkit.py`, `sources/__init__.py`, and every
  `sources/*.py`. The `_source_modules` list inside
  `sources/__init__.py:106-120` MUST be updated — those are string
  module paths used by `importlib.import_module()`.
- **Depends on**: nothing.

### Module 2: Move legacy `DatabaseQueryTool` into the new subpackage

- **Paths**:
  - `packages/ai-parrot-tools/src/parrot_tools/databasequery.py` →
    `packages/ai-parrot/src/parrot/tools/databasequery/tool.py`
  - Replace the source file at
    `packages/ai-parrot-tools/src/parrot_tools/databasequery.py` with a
    **compatibility shim** that re-exports the moved symbols:
    ```python
    """Compat shim — use parrot.tools.databasequery instead."""
    from parrot.tools.databasequery import (
        DatabaseQueryTool, DriverInfo, DatabaseQueryArgs,
    )
    from parrot.security import QueryLanguage, QueryValidator  # preserved re-exports
    __all__ = [
        "DatabaseQueryTool", "DriverInfo", "DatabaseQueryArgs",
        "QueryLanguage", "QueryValidator",
    ]
    ```
- **Responsibility**: Preserve the legacy tool verbatim under the new
  module path. Update every `from .abstract` import inside `tool.py` to
  the correct ai-parrot path (`from parrot.tools.abstract` or the
  equivalent — **verify with `grep` before committing**: see
  "Does NOT Exist" in Section 6).
- **Depends on**: Module 1 (the target folder must exist).

### Module 3: Refactor `DatabaseQueryToolkit` as `AbstractToolkit`

- **Path**: `packages/ai-parrot/src/parrot/tools/databasequery/toolkit.py`
- **Responsibility**: Rewrite the class to:
  - Inherit from `parrot.tools.toolkit.AbstractToolkit`.
  - Delete the four `AbstractTool` subclasses
    (`GetDatabaseMetadataTool`, `ValidateDatabaseQueryTool`,
    `ExecuteDatabaseQueryTool`, `FetchDatabaseRowTool`) and their
    `Args` schemas (replaced by method-signature-derived schemas
    generated by `ToolkitTool._generate_args_schema_from_method`).
  - Expose four public async methods with identical signatures to the
    old `args_schema` fields (`driver`, `query`, `credentials`,
    `params`, `tables`).
  - Set `tool_prefix = "db"` so the LLM sees
    `db_get_database_metadata`, etc.
  - Keep `get_source()` and `cleanup()` but list them in
    `exclude_tools` so they are NOT exposed as tools.
  - Call `QueryValidator.validate_query(query, language)` at the top
    of `validate_database_query`, `execute_database_query`, and
    `fetch_database_row` (see Module 5).
- **Depends on**: Modules 1, 4, 5.

### Module 4: `DatabaseQueryToolkit` backwards-compat alias + package shim

- **Paths**:
  - `packages/ai-parrot/src/parrot/tools/databasequery/__init__.py` — new public surface (see code block in Section 2).
  - `packages/ai-parrot/src/parrot/tools/database.py` — new compat module emitting `DeprecationWarning` and re-exporting `DatabaseQueryToolkit` as `DatabaseToolkit`.
- **Responsibility**: Preserve `from parrot.tools.database import DatabaseToolkit` for one release with a clear migration message.
- **Depends on**: Module 3.

### Module 5: Driver → QueryLanguage mapping inside the toolkit

- **Path**: `packages/ai-parrot/src/parrot/tools/databasequery/toolkit.py`
  (private helper).
- **Responsibility**: Add a small internal mapping from canonical
  driver name to `parrot.security.QueryLanguage`:

  | canonical driver | QueryLanguage |
  |---|---|
  | `pg`, `mysql`, `bigquery`, `sqlite`, `oracle`, `mssql`, `clickhouse`, `duckdb` | `SQL` |
  | `influx` | `FLUX` |
  | `mongo`, `atlas`, `documentdb` | `MQL` |
  | `elastic` | `JSON` |

  Implemented as a module-level `_DRIVER_TO_QUERY_LANGUAGE: dict[str, QueryLanguage]`. Lookup uses `normalize_driver()` first.
- **Depends on**: `parrot.security.QueryValidator` / `QueryLanguage`
  (existing).

### Module 6: `TOOL_REGISTRY` and redirector updates

- **Paths**:
  - `packages/ai-parrot-tools/src/parrot_tools/__init__.py:112` — repoint
    `"database_query"` → `"parrot.tools.databasequery.DatabaseQueryTool"`.
  - `packages/ai-parrot/src/parrot/tools/__init__.py` — confirm the
    `_CORE_SUBMODULES` set picks up the new `databasequery/` folder
    automatically via the glob at line 44. The redirector MUST NOT
    hijack `parrot.tools.databasequery.*` imports.
- **Depends on**: Modules 1, 2.

### Module 7: Tests

- **Paths**:
  - `packages/ai-parrot-tools/tests/database/` — rename directory to
    `packages/ai-parrot-tools/tests/databasequery/` (or keep under
    `ai-parrot` if that is where the source moved; **preferred**: co-locate tests at `packages/ai-parrot/tests/tools/databasequery/`).
    **Verify before renaming** — running `pytest` must still pick the tests up.
  - Update every existing `from parrot.tools.database...` import in the
    test files (see `test_integration.py`, `test_registry.py`,
    `test_sources.py`, `test_base_types.py`, `test_cache_vector_tier.py`,
    `test_init_exports.py`, `test_abstract_credentials.py`) to the new
    path.
  - **Add new tests** in `test_toolkit_ddl_guard.py`:
    - `test_validate_rejects_drop_table`
    - `test_validate_rejects_insert`
    - `test_validate_rejects_exec_stored_proc` (SQL; MSSQL allows EXEC at source level — the toolkit's `QueryValidator` still blocks it based on the generic SQL rule; confirm expected behavior in Q1).
    - `test_execute_rejects_ddl_before_source_call` (spy on the source to prove the source is never called when QueryValidator blocks).
    - `test_flux_query_allowed`, `test_flux_drop_rejected`.
    - `test_mongo_find_allowed` / `test_mongo_drop_rejected`.
  - **Add new tests** in `test_toolkit_abstracttoolkit_contract.py`:
    - `test_inherits_abstract_toolkit`
    - `test_tool_count_is_four`
    - `test_tool_names_prefixed_with_db`
    - `test_exclude_tools_hides_get_source_and_cleanup`
  - **Add new tests** in `test_backcompat_shim.py`:
    - `from parrot.tools.database import DatabaseToolkit` emits `DeprecationWarning` but resolves to the new class.
    - `from parrot_tools.databasequery import DatabaseQueryTool` still works and resolves to the moved module.
- **Depends on**: Modules 1–5.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_inherits_abstract_toolkit` | 3 | `DatabaseQueryToolkit` is an `AbstractToolkit` instance |
| `test_tool_count_is_four` | 3 | `toolkit.get_tools()` returns 4 `AbstractTool`s |
| `test_tool_names_prefixed` | 3 | Names are `db_get_database_metadata` etc. (or unprefixed if `tool_prefix=None` per Q2) |
| `test_excluded_methods_hidden` | 3 | `get_source` and `cleanup` do NOT appear in `get_tools()` output |
| `test_args_schema_auto_generated` | 3 | Each tool's `args_schema` exposes `driver`, `query`, etc. fields |
| `test_validate_rejects_drop_table` | 5 | `validate_database_query(driver="pg", query="DROP TABLE users")` returns `valid=False` and flags DDL |
| `test_validate_rejects_insert` | 5 | `INSERT INTO` → rejected |
| `test_validate_rejects_update_delete` | 5 | `UPDATE users SET ...` / `DELETE FROM users` → rejected |
| `test_validate_passes_select` | 5 | Plain `SELECT * FROM users` passes validation |
| `test_execute_rejects_ddl_before_source_call` | 5 | Source mock is never reached when `QueryValidator` blocks |
| `test_fetch_row_rejects_ddl` | 5 | Same for `fetch_database_row` |
| `test_flux_from_bucket_allowed` | 5 | Valid Flux passes |
| `test_mongo_find_allowed` | 5 | Valid MQL filter passes |
| `test_driver_to_query_language_mapping` | 5 | Canonical driver → `QueryLanguage` mapping correct for all 13 drivers |
| `test_database_deprecation_alias` | 4 | `from parrot.tools.database import DatabaseToolkit` emits `DeprecationWarning` |
| `test_databasequery_shim_preserves_tool` | 2 | `from parrot_tools.databasequery import DatabaseQueryTool` still resolves |
| `test_tool_registry_database_query_path` | 6 | `TOOL_REGISTRY["database_query"]` imports successfully |

### Integration Tests

| Test | Description |
|---|---|
| `test_e2e_metadata_then_validate_then_execute` | Golden-path three-step flow on a temp SQLite DB |
| `test_ddl_guard_e2e_sqlite` | On a live SQLite source: `DROP TABLE users` via `execute_database_query` returns `valid=False` and the table survives |
| `test_source_cache_cleanup` | `cleanup()` closes every cached source pool |
| `test_sources_registry_still_discovers_all_drivers` | After the rename, `get_source_class("pg")` etc. still resolve |

### Test Data / Fixtures

```python
@pytest.fixture
def toolkit():
    return DatabaseQueryToolkit()

@pytest.fixture
def sqlite_creds(tmp_path):
    db = tmp_path / "test.db"
    return {"dsn": f"sqlite:///{db}"}

DDL_QUERIES = [
    "DROP TABLE users",
    "CREATE TABLE t (id int)",
    "TRUNCATE TABLE users",
    "INSERT INTO users VALUES (1)",
    "UPDATE users SET x = 1",
    "DELETE FROM users",
    "GRANT ALL ON users TO x",
    "EXEC sp_foo",
]
```

---

## 5. Acceptance Criteria

- [ ] Package `packages/ai-parrot/src/parrot/tools/database/` no longer
      exists; replaced by a single-file shim
      `packages/ai-parrot/src/parrot/tools/database.py`.
- [ ] Package `packages/ai-parrot/src/parrot/tools/databasequery/` exists
      with `__init__.py`, `base.py`, `toolkit.py`, `tool.py`, and
      `sources/`.
- [ ] `grep -rn "class DatabaseToolkit\b" packages/ai-parrot/src/parrot/tools/`
      returns **zero** matches (moved/renamed).
- [ ] `grep -rn "class DatabaseToolkit\b" packages/ai-parrot/src/parrot/bots/`
      returns exactly **one** match (the SQLAgent-facing ABC, unchanged).
- [ ] `isinstance(DatabaseQueryToolkit(), AbstractToolkit)` is `True`.
- [ ] `len(DatabaseQueryToolkit().get_tools())` equals `4`.
- [ ] `DatabaseQueryToolkit().validate_database_query(driver="pg", query="DROP TABLE u")` returns a dict with `valid=False` and an error message mentioning DDL/dangerous operation.
- [ ] `DatabaseQueryToolkit().execute_database_query(driver="pg", query="DROP TABLE u")` short-circuits before reaching the source — asserted with a mock.
- [ ] `from parrot.tools.database import DatabaseToolkit` still works and emits `DeprecationWarning`.
- [ ] `from parrot_tools.databasequery import DatabaseQueryTool` still works.
- [ ] `TOOL_REGISTRY["database_query"]` resolves to `parrot.tools.databasequery.DatabaseQueryTool`.
- [ ] `pytest packages/ai-parrot-tools/tests/ -v` passes after the test path updates.
- [ ] `pytest packages/ai-parrot/tests/ -v` passes (SQLAgent / SQLToolkit untouched).
- [ ] No new top-level dependencies.

---

## 6. Codebase Contract

### Verified Imports

```python
# New canonical paths (after this feature lands)
from parrot.tools.databasequery import (
    DatabaseQueryToolkit,                   # new class (Module 3)
    DatabaseQueryTool,                       # moved from parrot_tools (Module 2)
    AbstractDatabaseSource,
    ValidationResult, ColumnMeta, TableMeta,
    MetadataResult, QueryResult, RowResult,
)

# Existing — verified before edits
from parrot.tools.toolkit import AbstractToolkit
# verified: packages/ai-parrot/src/parrot/tools/toolkit.py:140

from parrot.tools.abstract import AbstractTool, AbstractToolArgsSchema, ToolResult
# verified: packages/ai-parrot/src/parrot/tools/database/toolkit.py:23 (used by old impl)

from parrot.security import QueryLanguage, QueryValidator
# verified: packages/ai-parrot/src/parrot/security/query_validator.py:19,29
# verified re-export: packages/ai-parrot/src/parrot/security/__init__.py (yes)

# Kept UNCHANGED — these are different classes, same name:
from parrot.bots.database.toolkits.base import DatabaseToolkit as _BotsDBToolkit
# verified: packages/ai-parrot/src/parrot/bots/database/toolkits/base.py:65 — AbstractToolkit ABC

# Deprecated alias (still resolvable after this feature):
from parrot.tools.database import DatabaseToolkit   # DeprecationWarning; resolves to DatabaseQueryToolkit

# Legacy tool compat path (still resolvable after this feature):
from parrot_tools.databasequery import DatabaseQueryTool, QueryLanguage, QueryValidator
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/tools/toolkit.py:140
class AbstractToolkit(ABC):
    input_class: Optional[Type[BaseModel]] = None                  # line 168
    return_direct: bool = False                                    # line 169
    exclude_tools: tuple[str, ...] = ()                            # line 177
    tool_prefix: Optional[str] = None                              # line 191
    prefix_separator: str = "_"                                    # line 194

    def __init__(self, **kwargs): ...                              # line 196
    async def start(self) -> None: ...                             # line 212
    async def stop(self) -> None: ...                              # line 219
    async def cleanup(self) -> None: ...                           # line 226
    def get_tools(self, permission_context=None, resolver=None) -> List[AbstractTool]: ...   # line 233
    def _generate_tools(self) -> None: ...                         # line 286
```

```python
# packages/ai-parrot/src/parrot/security/query_validator.py:29
class QueryValidator:
    @staticmethod
    def validate_sql_query(query: str) -> Dict[str, Any]: ...       # line 33
    @staticmethod
    def validate_flux_query(query: str) -> Dict[str, Any]: ...      # line 79
    # Additional methods verified: validate_mql_query, validate_json_dsl,
    # validate_query(query, language) — the dispatcher used by legacy tool.
    # ^^ VERIFY before wiring — grep for 'def validate_query' to confirm.
```

```python
# packages/ai-parrot/src/parrot/tools/database/toolkit.py:358  (BEFORE — to be rewritten)
class DatabaseToolkit:
    def __init__(self) -> None: ...                                # line 377
    def _initialize_tools(self) -> None: ...                       # line 384
    def get_source(self, driver: str) -> AbstractDatabaseSource: ...   # line 393
    def get_tools(self) -> list[AbstractTool]: ...                 # line 415
    def get_tool_by_name(self, name: str) -> AbstractTool | None: ...  # line 425
    async def cleanup(self) -> None: ...                           # line 436
```

```python
# packages/ai-parrot/src/parrot/tools/database/base.py:186
class AbstractDatabaseSource(ABC):
    driver: str                                                     # line 199
    sqlglot_dialect: str | None = None                              # line 200
    async def resolve_credentials(self, credentials) -> dict: ...   # line 202
    @abstractmethod
    async def get_default_credentials(self) -> dict: ...            # line 217
    async def validate_query(self, query: str) -> ValidationResult: ...  # line 225 (sqlglot-based)
    @abstractmethod
    async def get_metadata(self, credentials, tables=None) -> MetadataResult: ...   # line 271
    @abstractmethod
    async def query(self, credentials, sql, params=None) -> QueryResult: ...        # line 288
    @abstractmethod
    async def query_row(self, credentials, sql, params=None) -> RowResult: ...      # line 306
```

```python
# packages/ai-parrot/src/parrot/tools/database/sources/__init__.py:24
_DRIVER_ALIASES = {
    "postgres": "pg", "postgresql": "pg", "mariadb": "mysql",
    "bq": "bigquery", "sqlserver": "mssql", "influxdb": "influx",
    "mongodb": "mongo", "elasticsearch": "elastic", "opensearch": "elastic",
}
def normalize_driver(driver: str) -> str: ...                       # line 45
def register_source(driver: str) -> Callable[[type], type]: ...     # line 69
def get_source_class(driver: str) -> type[AbstractDatabaseSource]: ...   # line 132

_source_modules = [                                                 # line 106
    "parrot.tools.database.sources.postgres", ...                   # MUST rename → "...databasequery.sources.postgres"
]
```

```python
# packages/ai-parrot-tools/src/parrot_tools/databasequery.py:308 (1064 LOC — to be moved verbatim)
class DatabaseQueryTool(AbstractTool):
    name = "database_query"
    args_schema = DatabaseQueryArgs
    def __init__(self, **kwargs): ...
    def _default_output_dir(self): ...
    def _validate_query_safety(self, query: str, driver: str) -> Dict[str, Any]:   # line 386
        query_language = DriverInfo.get_query_language(driver)
        return QueryValidator.validate_query(query, query_language)   # <- the DDL guard to port to the toolkit
```

```python
# packages/ai-parrot-tools/src/parrot_tools/__init__.py:112
"database_query": "parrot_tools.databasequery.DatabaseQueryTool",   # MUST repoint to parrot.tools.databasequery.DatabaseQueryTool
```

```python
# packages/ai-parrot/src/parrot/tools/__init__.py:44
_CORE_SUBMODULES = frozenset(
    {p.stem for p in _CORE_TOOLS_DIR.glob("*.py") if p.stem != "__init__"}
    | {p.name for p in _CORE_TOOLS_DIR.iterdir() if p.is_dir() and (p / "__init__.py").exists()}
)
# After Module 1+2, this set will include "databasequery" (the new dir) AND
# "database" (the new compat .py shim). Both are core — the redirector will
# not hijack them. No code change needed here.
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `DatabaseQueryToolkit.validate_database_query()` | `QueryValidator.validate_query(query, language)` | direct call, then `AbstractDatabaseSource.validate_query` as second layer | `query_validator.py:29`, `database/base.py:225` |
| `DatabaseQueryToolkit.execute_database_query()` | `QueryValidator.validate_query(...)` before `source.query(...)` | early-return `ValidationResult(valid=False)` on DDL | `query_validator.py` |
| `DatabaseQueryToolkit.get_source()` | `get_source_class(driver)` | cached instantiation | `databasequery/sources/__init__.py:132` (post-rename) |
| `parrot.tools.database` (shim) | `parrot.tools.databasequery.DatabaseQueryToolkit` | re-export as `DatabaseToolkit` + `DeprecationWarning` | new file |
| `parrot_tools.databasequery` (shim) | `parrot.tools.databasequery.*` | re-export of `DatabaseQueryTool`, `DriverInfo`, `DatabaseQueryArgs` | new file |
| `TOOL_REGISTRY["database_query"]` | `parrot.tools.databasequery.DatabaseQueryTool` | string path used by `lazy_import` | `parrot_tools/__init__.py:112` |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.tools.DatabaseToolkit`~~ — top-level name not re-exported from `parrot.tools/__init__.py`; always addressed via `parrot.tools.database` or `parrot.tools.databasequery`.
- ~~`parrot.tools.databasequery.DatabaseToolkit`~~ — will NOT exist after this feature. The new name is `DatabaseQueryToolkit`. The `DatabaseToolkit` alias lives only in the `parrot.tools.database` **shim file**, not inside `databasequery/`.
- ~~`AbstractToolkit.register_tool(...)` / `.add_tool(...)`~~ — no such method; tools come exclusively from public async methods via `_generate_tools()`.
- ~~`QueryValidator.validate(...)` (no arg)~~ — the dispatcher is `validate_query(query, language)`; verify with `grep -n "def validate_query" packages/ai-parrot/src/parrot/security/query_validator.py` before wiring.
- ~~`parrot.tools.database.toolkit.DatabaseQueryToolkit`~~ — the class lives under the new `databasequery/` path, not the old `database/` path.
- ~~`parrot_tools.databasequery.DatabaseQueryToolkit`~~ — the toolkit has a single home in `parrot.tools.databasequery`. The `parrot_tools` compat shim only re-exports the legacy `DatabaseQueryTool`, `DriverInfo`, and `DatabaseQueryArgs`.
- ~~`AbstractTool.name` must be unique globally~~ — tools are named per-toolkit; with `tool_prefix="db"` the final names are `db_get_database_metadata` etc. — no global registry check.
- ~~`sqlglot.parse` blocks DDL~~ — `sqlglot.parse("DROP TABLE x")` succeeds. DDL rejection is the responsibility of `QueryValidator`, not the source's `validate_query`.
- ~~`AbstractToolkit` supports synchronous methods as tools~~ — only `async def` public methods are picked up. Verify by reading `_generate_tools()` before writing any sync helper that should be excluded.
- ~~`parrot.tools.databasequery.DatabaseQueryTool` can be imported without `asyncdb`~~ — the legacy tool imports `from asyncdb import AsyncDB` at module top (line 14). The move keeps that dependency.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Use `git mv` for every file move so history is preserved.
- Drive the `AbstractToolkit` refactor by mirroring
  `parrot.bots.database.toolkits.sql.SQLToolkit` — it is the nearest
  established pattern (same family of operations, `AbstractToolkit`
  subclass, `exclude_tools`, lifecycle methods).
- All four public methods return plain dicts (`.model_dump()` output).
  `AbstractToolkit` wraps them in `ToolResult` automatically — do NOT
  construct `ToolResult` manually inside the methods.
- Layer the safety check: `QueryValidator` first (cheap, DDL-blocking),
  then `source.validate_query` (sqlglot syntax). If `QueryValidator`
  rejects, return `ValidationResult(valid=False, error=...)` without
  touching the source.
- Keep `get_source()` synchronous — matches the existing implementation
  and makes it trivial to cache.
- All logging through `self.logger`; no `print`.

### Known Risks / Gotchas

- **Risk: `parrot.tools.database` is both a package directory AND will
  become a shim module.** Python does not allow both a `database/`
  package and a `database.py` file to coexist at the same import path.
  Mitigation: after `git mv database → databasequery`, Python will no
  longer see a `database/` package — creating `database.py` is then
  safe. Verify with `python -c "import parrot.tools.database"` after
  the move.
- **Risk: `sources/__init__.py:106` hardcodes the path
  `parrot.tools.database.sources.postgres`.** If missed, the lazy
  `_ensure_sources_loaded()` will silently fail to register sources
  and every driver will raise "No DatabaseSource registered".
  Mitigation: update the `_source_modules` list in Module 1 and assert
  via `test_sources_registry_still_discovers_all_drivers`.
- **Risk: Tests in `packages/ai-parrot-tools/tests/database/` may be
  tied to the import path.** The tests reference
  `from parrot.tools.database.*`. After the rename those must be
  updated — run a project-wide `grep` and assert zero legacy paths
  remain before committing.
- **Risk: `parrot_tools/databasequery.py` being replaced by a shim
  could break `from parrot_tools.databasequery import DriverInfo`
  callers.** Mitigation: the compat shim re-exports `DriverInfo`,
  `DatabaseQueryArgs`, `QueryLanguage`, and `QueryValidator` (all
  symbols currently imported by callers — confirm with `grep -rn
  "from parrot_tools.databasequery"` before freezing the shim surface).
- **Risk: `DeprecationWarning` fires on every import of the
  `parrot.tools.database` shim.** Users who run `pytest -W error`
  will see their suites fail. Mitigation: use
  `warnings.warn(..., DeprecationWarning, stacklevel=2)` only once
  per process by guarding on a module-level flag, or use
  `FutureWarning` if the repo convention is to use
  `DeprecationWarning` for removed APIs — verify project precedent.
- **Risk: `AbstractToolkit.tool_prefix="db"` renames tools that LLM
  prompts or evals already reference.** Mitigation: Q2 asks whether to
  default to prefixed (`db_get_database_metadata`) or unprefixed
  (`get_database_metadata`). Default choice in this spec: prefixed —
  aligns with `SQLToolkit` which already uses a prefix. Revisit if
  reviewer disagrees.
- **Risk: The old `DatabaseToolkit` in `parrot/bots/` is still called
  `DatabaseToolkit`.** After this feature ships, the name still exists
  in one place (the bot-side ABC). That is intentional — it is only
  confusing by name, not by runtime collision (different modules). If
  a future reviewer finds the name confusing, a follow-up spec can
  rename it to `AbstractSQLAgentToolkit` or similar. Out of scope here.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `sqlglot` | (existing) | Per-source syntactic validation — unchanged |
| `asyncdb` | (existing) | Legacy tool driver connector — unchanged |
| No new dependencies | | |

---

## 8. Open Questions

- [x] **Q1** — For MSSQL stored procedures, legacy behavior on the
  source side allows `EXEC`/`EXECUTE`. The generic SQL
  `QueryValidator.validate_sql_query` blocks `EXEC`. Should the toolkit
  apply a driver-specific exception (allow EXEC for `mssql`) or keep
  the strict generic behavior? *Default in spec: strict (block EXEC
  for every SQL driver). Revisit if MSSQL stored-proc callers exist.*
  *Owner: Jesus Lara*: allow EXEC for `mssql`
- [x] **Q2** — Set `tool_prefix="db"` so LLM tool names become
  `db_get_database_metadata` etc., or leave `tool_prefix=None` to
  preserve the existing names from FEAT-062? *Default in spec:
  `"db"` — matches the `SQLToolkit` convention.* *Owner: Jesus Lara*: prefix=dq to avoid prefix clash with SQLToolkit.
- [x] **Q3** — Should the `parrot.tools.database` compat shim live for
  one minor release (3 months) or until the next major version? Pick a
  sunset. *Owner: Jesus Lara*: because was not inherited from AbstractToolkit, DatabaseToolkit was unabled to deployed into PROD, is safely for removing the folder parrot.tools.database.
- [x] **Q4** — Tests currently live in
  `packages/ai-parrot-tools/tests/database/`. They assert against
  `parrot.tools.database.*` — imports that will resolve (with
  `DeprecationWarning`) after this feature. Should we move the tests
  to `packages/ai-parrot/tests/tools/databasequery/` now, or leave
  them in ai-parrot-tools and only rewrite the imports? *Default in
  spec: move to `packages/ai-parrot/tests/tools/databasequery/` since
  the source moved there.* *Owner: Jesus Lara*: move.

---

## Worktree Strategy

**Default isolation unit**: `per-spec`.

All module tasks touch overlapping files (`toolkit.py`, `__init__.py`,
`sources/__init__.py`, `TOOL_REGISTRY`, tests). Mechanical moves must
land before the toolkit refactor, and both must land before the tests
pass. Run tasks sequentially in one worktree.

Cross-feature dependencies:
- **Blocks nothing.**
- **Blocked by**: no active spec. Compatible with any in-flight FEAT
  touching `parrot.bots.database.*` (the bot toolkits), because that
  class is explicitly untouched here.

Recommended worktree bootstrap:

```bash
git checkout dev && git pull origin dev
git worktree add -b feat-105-databasetoolkit-clash \
  .claude/worktrees/feat-105-databasetoolkit-clash HEAD
```

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-04-17 | Jesus Lara | Initial draft |
