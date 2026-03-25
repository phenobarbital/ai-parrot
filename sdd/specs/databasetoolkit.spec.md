# Feature Specification: DatabaseToolkit

**Feature ID**: FEAT-062
**Date**: 2026-03-25
**Author**: claude-opus-4-6
**Status**: draft
**Target version**: next minor

---

## 1. Motivation & Business Requirements

### Problem Statement

`DatabaseQueryTool` (in `parrot_tools/databasequery.py`) exposes a single tool with
multiple operating modes controlled by optional parameters (`query`, `get_metadata`,
etc.). Empirical evidence across Gemini Flash and GPT-4o shows that LLMs default to
the primary semantic of the tool name and rarely activate secondary modes, even when
the task explicitly requires them — e.g., running `information_schema` queries via the
default SQL path instead of the dedicated metadata mode.

### Goals
- Expose each database operation as an independent, named tool with an unambiguous
  description and a minimal, focused schema.
- Provide a three-step agentic flow: **discover schema → validate query → execute
  query** that reduces query errors in practice.
- Support all drivers currently supported by `DatabaseQueryTool` (PostgreSQL, MySQL,
  SQLite, MongoDB, DocumentDB, BigQuery, InfluxDB, and others via asyncdb).
- Use a pluggable source registry so new drivers can be added without touching
  toolkit code.

### Non-Goals (explicitly out of scope)
- Connection pooling per `(driver, credentials)` pair — open/close per call is
  acceptable for conversational agent workloads.
- `EXPLAIN`-based query validation — deferred to a future iteration.
- Query result pagination — callers can use `LIMIT`/`OFFSET` in the query.
- Cross-database joins or federation.
- Removing `DatabaseQueryTool` — both coexist; migration is opt-in.

---

## 2. Architectural Design

### Overview

Replace the single multi-purpose `DatabaseQueryTool` with a `DatabaseToolkit` that
exposes **four independent `AbstractTool` subclasses** via `get_tools()`. Each tool
maps to exactly one database operation. A pluggable **source registry** decouples
driver-specific logic from the toolkit orchestration.

### Component Diagram
```
DatabaseToolkit
├── GetDatabaseMetadataTool     → schema discovery
├── ValidateDatabaseQueryTool   → syntax validation (sqlglot / custom)
├── ExecuteDatabaseQueryTool    → multi-row query execution
└── FetchDatabaseRowTool        → single-row fetch

Each tool delegates to:
    get_source(driver) → AbstractDatabaseSource subclass
                            ├── PostgresSource
                            ├── MySQLSource
                            ├── SQLiteSource
                            ├── MongoSource
                            ├── DocumentDBSource
                            ├── BigQuerySource
                            ├── InfluxSource
                            └── ... (future sources)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractTool` | extends | Each of the four tools inherits `AbstractTool` |
| `AbstractToolArgsSchema` | extends | Shared `DatabaseBaseArgs` schema |
| `ToolResult` | returns | All tool `_execute()` methods return `ToolResult` |
| `asyncdb.AsyncDB` | uses | All DB connections and query execution |
| `BasicAgent` / `AgentCrew` | consumed by | `toolkit.get_tools()` passed to agent `tools=` |
| `DatabaseQueryTool` | coexists | Not removed; agents can migrate incrementally |

### Data Models

```python
# Result types (Pydantic v2) — defined in base.py

class ValidationResult(BaseModel):
    valid: bool
    error: str | None = None
    dialect: str | None = None

class ColumnMeta(BaseModel):
    name: str
    data_type: str
    nullable: bool = True
    primary_key: bool = False
    default: Any = None

class TableMeta(BaseModel):
    name: str
    schema_name: str | None = None
    columns: list[ColumnMeta] = Field(default_factory=list)
    row_count: int | None = None

class MetadataResult(BaseModel):
    driver: str
    tables: list[TableMeta]
    raw: dict[str, Any] = Field(default_factory=dict)

class QueryResult(BaseModel):
    driver: str
    rows: list[dict[str, Any]]
    row_count: int
    columns: list[str]
    execution_time_ms: float

class RowResult(BaseModel):
    driver: str
    row: dict[str, Any] | None
    found: bool
    execution_time_ms: float
```

### New Public Interfaces

```python
# toolkit.py — main entry point

class DatabaseToolkit:
    def __init__(self) -> None: ...
    def get_source(self, driver: str) -> AbstractDatabaseSource: ...
    def get_tools(self) -> list[AbstractTool]: ...
    def get_tool_by_name(self, name: str) -> AbstractTool | None: ...
    async def cleanup(self) -> None: ...

# sources/__init__.py — registry

def register_source(driver: str) -> Callable: ...
def get_source_class(driver: str) -> type[AbstractDatabaseSource]: ...
```

---

## 3. Module Breakdown

### Module 1: Result Types & AbstractDatabaseSource
- **Path**: `parrot/tools/database/base.py`
- **Responsibility**: Define all Pydantic result models (`ValidationResult`,
  `ColumnMeta`, `TableMeta`, `MetadataResult`, `QueryResult`, `RowResult`) and
  `AbstractDatabaseSource` ABC with the contract: `resolve_credentials`,
  `get_default_credentials`, `validate_query`, `get_metadata`, `query`, `query_row`.
- **Depends on**: None (only stdlib + pydantic)

### Module 2: Source Registry
- **Path**: `parrot/tools/database/sources/__init__.py`
- **Responsibility**: `_SOURCE_REGISTRY` dict, `register_source()` decorator,
  `get_source_class()` lookup with lazy imports.
- **Depends on**: Module 1 (imports `AbstractDatabaseSource` for type hints)

### Module 3: PostgresSource
- **Path**: `parrot/tools/database/sources/postgres.py`
- **Responsibility**: PostgreSQL-specific implementation of `AbstractDatabaseSource`.
  Uses `asyncdb` with driver `"pg"`. Queries `information_schema` for metadata.
  Inherits default `validate_query()` with `sqlglot_dialect = "postgres"`.
- **Depends on**: Module 1, Module 2

### Module 4: MySQLSource
- **Path**: `parrot/tools/database/sources/mysql.py`
- **Responsibility**: MySQL-specific source. Driver `"mysql"`,
  `sqlglot_dialect = "mysql"`.
- **Depends on**: Module 1, Module 2

### Module 5: SQLiteSource
- **Path**: `parrot/tools/database/sources/sqlite.py`
- **Responsibility**: SQLite-specific source. Driver `"sqlite"`,
  `sqlglot_dialect = "sqlite"`.
- **Depends on**: Module 1, Module 2

### Module 6: MongoSource
- **Path**: `parrot/tools/database/sources/mongodb.py`
- **Responsibility**: MongoDB source. `sqlglot_dialect = None`. Overrides
  `validate_query()` with JSON parse validation. `get_metadata()` uses
  `list_collection_names()` + `$sample` for field inference.
- **Depends on**: Module 1, Module 2

### Module 7: BigQuerySource
- **Path**: `parrot/tools/database/sources/bigquery.py`
- **Responsibility**: BigQuery source. Driver `"bigquery"`,
  `sqlglot_dialect = "bigquery"`.
- **Depends on**: Module 1, Module 2

### Module 8: Tool Argument Schemas & Tool Implementations
- **Path**: `parrot/tools/database/toolkit.py`
- **Responsibility**: `DatabaseBaseArgs`, `GetMetadataArgs`, `ValidateQueryArgs`,
  `ExecuteQueryArgs`, `FetchRowArgs` schemas. Four `AbstractTool` subclasses:
  `GetDatabaseMetadataTool`, `ValidateDatabaseQueryTool`,
  `ExecuteDatabaseQueryTool`, `FetchDatabaseRowTool`. `DatabaseToolkit` class
  with `get_tools()`, `get_source()`, `cleanup()`.
- **Depends on**: Module 1, Module 2 (all sources via registry)

### Module 9: Package Init & Exports
- **Path**: `parrot/tools/database/__init__.py`
- **Responsibility**: Public exports: `DatabaseToolkit`,
  `AbstractDatabaseSource`, result types. Lazy imports for optional sources.
- **Depends on**: Module 1, Module 8

### Module 10: Unit & Integration Tests
- **Path**: `tests/tools/database/test_toolkit.py`,
  `tests/tools/database/test_sources.py`,
  `tests/tools/database/test_registry.py`
- **Responsibility**: Test result models, registry, source contract, toolkit
  `get_tools()`, tool schema generation, and end-to-end execution with mocked
  asyncdb connections.
- **Depends on**: All modules

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_validation_result_valid` | Module 1 | `ValidationResult(valid=True)` serializes correctly |
| `test_validation_result_invalid` | Module 1 | `ValidationResult(valid=False, error=...)` |
| `test_column_meta_defaults` | Module 1 | Default `nullable=True`, `primary_key=False` |
| `test_table_meta_with_columns` | Module 1 | `TableMeta` with nested `ColumnMeta` list |
| `test_query_result_fields` | Module 1 | `QueryResult` has correct field types |
| `test_row_result_not_found` | Module 1 | `RowResult(found=False, row=None)` |
| `test_register_source` | Module 2 | Decorator registers class in `_SOURCE_REGISTRY` |
| `test_get_source_class_valid` | Module 2 | Returns registered class |
| `test_get_source_class_invalid` | Module 2 | Raises `ValueError` for unknown driver |
| `test_postgres_validate_valid_sql` | Module 3 | `validate_query("SELECT 1")` returns `valid=True` |
| `test_postgres_validate_invalid_sql` | Module 3 | Returns `valid=False` with parse error |
| `test_mongo_validate_valid_json` | Module 6 | JSON filter doc validates |
| `test_mongo_validate_invalid_json` | Module 6 | Invalid JSON returns `valid=False` |
| `test_toolkit_get_tools_count` | Module 8 | `get_tools()` returns exactly 4 tools |
| `test_toolkit_tool_names` | Module 8 | Tool names match expected set |
| `test_toolkit_get_source_caches` | Module 8 | Same driver returns cached instance |
| `test_tool_schemas_valid` | Module 8 | Each tool's `get_schema()` produces valid JSON |

### Integration Tests

| Test | Description |
|---|---|
| `test_postgres_metadata_e2e` | Full metadata discovery against a test PostgreSQL DB |
| `test_postgres_query_e2e` | Execute a SELECT and verify `QueryResult` structure |
| `test_postgres_query_row_e2e` | Single-row fetch returns `found=True` |
| `test_validate_then_execute_flow` | Three-step flow: metadata → validate → execute |

### Test Data / Fixtures

```python
@pytest.fixture
def mock_asyncdb():
    """Mock asyncdb connection that returns canned results."""
    ...

@pytest.fixture
def toolkit():
    """Fresh DatabaseToolkit instance."""
    return DatabaseToolkit()

@pytest.fixture
def postgres_source():
    """PostgresSource with mocked credentials."""
    ...
```

---

## 5. Acceptance Criteria

- [ ] `DatabaseToolkit().get_tools()` returns 4 tools with correct names and schemas
- [ ] Each tool's `get_schema()` produces a valid JSON schema consumable by LLMs
- [ ] `validate_database_query` correctly validates SQL via sqlglot for PostgreSQL,
      MySQL, SQLite, and BigQuery dialects
- [ ] `validate_database_query` correctly validates JSON filters for MongoDB
- [ ] `get_database_metadata` returns `MetadataResult` with table/column info
- [ ] `execute_database_query` returns `QueryResult` with rows and execution time
- [ ] `fetch_database_row` returns `RowResult` with single row or `found=False`
- [ ] Source registry supports `register_source()` decorator and `get_source_class()` lookup
- [ ] All sources resolve credentials via `resolve_credentials()` (explicit > default)
- [ ] `DatabaseQueryTool` remains functional — no breaking changes
- [ ] All unit tests pass: `pytest tests/tools/database/ -v`
- [ ] `sqlglot` added to dependencies in `pyproject.toml`
- [ ] Package exports work: `from parrot.tools.database import DatabaseToolkit`

---

## 6. Implementation Notes & Constraints

### Patterns to Follow
- Use `AbstractTool` from `parrot/tools/abstract.py` — each of the four tools
  inherits it and implements `async _execute(**kwargs) -> ToolResult`
- Use `AbstractToolArgsSchema` from `parrot/tools/abstract.py` for argument schemas
- Use `ToolResult` for all return values from `_execute()`
- Follow the `DatasetManager` toolkit pattern in `parrot/tools/dataset_manager/`
  as a reference for toolkit structure
- All structured data as Pydantic v2 models
- Async-first: all source methods are `async def`
- Logging via `self.logger = logging.getLogger("Parrot.Toolkits.Database")`
- Lazy imports for source modules to avoid pulling heavy drivers at startup

### Known Risks / Gotchas
- `sqlglot` error levels use string values (`"raise"`) — verify API compatibility
  with the installed version.
- MongoDB validation is JSON-parse-based, not schema-validated — a syntactically
  valid JSON document could still be an invalid aggregation pipeline.
- The `asyncdb` driver string naming differs from the `sqlglot` dialect naming
  (e.g., `"pg"` vs `"postgres"`) — sources must map both correctly.
- Existing tests in `tests/tools/database/` target the FEAT-032 schema tools,
  not this new toolkit — new tests go in separate files.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `sqlglot` | `>=20.0` | SQL syntax validation for SQL dialects |
| `asyncdb` | existing | All DB connections and query execution |
| `pydantic` | `>=2.0` | Result models and args schemas |
| `navconfig` | existing | Settings for default credentials |

---

## 7. Worktree Strategy

- **Isolation unit**: `per-spec` (sequential tasks in one worktree)
- **Rationale**: All modules build on each other linearly (base → registry →
  sources → toolkit → tests). Parallel execution would require constant
  coordination on shared files.
- **Parallelizable exceptions**: Source implementations (Modules 3–7) can be
  parallelized after Module 2 is complete, but the savings are marginal given
  their small size.
- **Cross-feature dependencies**: None. `DatabaseQueryTool` coexists unchanged.

---

## 8. Open Questions

- [ ] Should `InfluxSource` support both InfluxQL and Flux, or only Flux? — *Owner: project lead*
- [ ] Should `DocumentDBSource` be a separate source or a config variant of `MongoSource`? — *Owner: project lead*
- [ ] Should we add `Oracle`, `MSSQL`, `ClickHouse` sources in v1 (they exist in `DatabaseQueryTool.DRIVER_MAP`)? — *Owner: project lead*

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-03-25 | claude-opus-4-6 | Initial draft from brainstorm |
