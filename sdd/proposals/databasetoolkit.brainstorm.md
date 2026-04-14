# Specification: DatabaseToolkit

**Feature:** `parrot/tools/database/`  
**Status:** Draft  
**Replaces:** `DatabaseQueryTool` (multi-purpose pattern → dedicated toolkit pattern)

---

## 1. Motivation

`DatabaseQueryTool` exposes a single tool with multiple operating modes controlled
by optional parameters (`query`, `get_metadata`, etc.). Empirical evidence across
Gemini Flash and GPT-4o shows that LLMs default to the primary semantic of the tool
name and rarely activate secondary modes, even when the task explicitly requires them
(e.g., running `information_schema` queries via the default SQL path instead of the
dedicated metadata mode).

The toolkit pattern resolves this by exposing each operation as an independent,
named tool with an unambiguous description and a minimal, focused schema. The LLM
selects the right tool by name — no parameter-level disambiguation required.

---

## 2. Package Structure

```
parrot/tools/database/
├── __init__.py
├── toolkit.py          # DatabaseToolkit — main entry point
├── base.py             # AbstractDatabaseSource + result types
└── sources/
    ├── __init__.py     # source registry + auto-discovery
    ├── postgres.py     # PostgresSource
    ├── mysql.py        # MySQLSource
    ├── sqlite.py       # SQLiteSource
    ├── mongodb.py      # MongoSource
    ├── documentdb.py   # DocumentDBSource (extends MongoSource)
    ├── bigquery.py     # BigQuerySource
    ├── influxdb.py     # InfluxSource
    └── ...             # future sources follow the same contract
```

---

## 3. Result Types

Defined in `base.py`. All results are Pydantic v2 models, consistent with the
`ToolResult` convention used across the codebase.

```python
from pydantic import BaseModel, Field
from typing import Any

class ValidationResult(BaseModel):
    valid: bool
    error: str | None = None          # human-readable parse error if valid=False
    dialect: str | None = None        # dialect used for validation

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
    row_count: int | None = None      # None if count is expensive/unsupported

class MetadataResult(BaseModel):
    driver: str
    tables: list[TableMeta]
    raw: dict[str, Any] = Field(default_factory=dict)  # driver-specific extras

class QueryResult(BaseModel):
    driver: str
    rows: list[dict[str, Any]]
    row_count: int
    columns: list[str]
    execution_time_ms: float

class RowResult(BaseModel):
    driver: str
    row: dict[str, Any] | None       # None if no row matched
    found: bool
    execution_time_ms: float
```

---

## 4. AbstractDatabaseSource

Defined in `base.py`. The contract every source must satisfy.

```python
from abc import ABC, abstractmethod
from typing import Any

class AbstractDatabaseSource(ABC):
    """
    Base class for database sources in DatabaseToolkit.

    Each source encapsulates:
    - Driver identification
    - Credential resolution (explicit > default)
    - Query validation (sqlglot default or dialect-specific override)
    - Metadata discovery
    - Query execution (multi-row and single-row)
    """

    # Subclasses set this to the asyncdb driver string, e.g. "postgresql"
    driver: str

    # Subclasses set this to the sqlglot dialect string, or None for
    # non-SQL sources that must override validate_query() themselves.
    sqlglot_dialect: str | None = None

    # ------------------------------------------------------------------ #
    # Credential resolution                                                #
    # ------------------------------------------------------------------ #

    async def resolve_credentials(
        self,
        credentials: dict[str, Any] | None
    ) -> dict[str, Any]:
        """
        Return credentials to use for this call.
        Explicit credentials take precedence over defaults.
        """
        return credentials or await self.get_default_credentials()

    @abstractmethod
    async def get_default_credentials(self) -> dict[str, Any]:
        """
        Return default credentials for this driver.
        Implementations typically read from environment variables
        or a secrets manager (AWS Secrets Manager, navconfig settings, etc.)
        """
        ...

    # ------------------------------------------------------------------ #
    # Query validation                                                     #
    # ------------------------------------------------------------------ #

    async def validate_query(self, query: str) -> ValidationResult:
        """
        Validate query syntax before execution.

        Default implementation uses sqlglot with the declared dialect.
        Sources with sqlglot_dialect=None MUST override this method;
        the default raises NotImplementedError to enforce the contract.

        Non-SQL sources (Mongo, InfluxDB, etc.) override this with
        dialect-appropriate validation (JSON schema, Flux parser, etc.)
        """
        if self.sqlglot_dialect is None:
            raise NotImplementedError(
                f"{self.__class__.__name__} does not define sqlglot_dialect "
                f"and must override validate_query()."
            )

        import sqlglot
        try:
            sqlglot.parse(query, dialect=self.sqlglot_dialect, error_level="raise")
            return ValidationResult(valid=True, dialect=self.sqlglot_dialect)
        except sqlglot.errors.ParseError as e:
            return ValidationResult(
                valid=False,
                error=str(e),
                dialect=self.sqlglot_dialect
            )

    # ------------------------------------------------------------------ #
    # Core operations                                                      #
    # ------------------------------------------------------------------ #

    @abstractmethod
    async def get_metadata(
        self,
        credentials: dict[str, Any],
        tables: list[str] | None = None
    ) -> MetadataResult:
        """
        Discover schema metadata.

        Args:
            credentials: Resolved credentials (already passed through resolve_credentials).
            tables: Optional list of table/collection names to restrict discovery.
                    If None, returns metadata for all accessible tables.

        Returns:
            MetadataResult with table and column definitions.
        """
        ...

    @abstractmethod
    async def query(
        self,
        credentials: dict[str, Any],
        sql: str,
        params: dict[str, Any] | None = None
    ) -> QueryResult:
        """
        Execute a query and return all matching rows.

        Args:
            credentials: Resolved credentials.
            sql: Query string (SQL, aggregation pipeline as JSON string, Flux, etc.)
            params: Optional named parameters for parameterized queries.

        Returns:
            QueryResult with rows, column names, and execution metadata.
        """
        ...

    @abstractmethod
    async def query_row(
        self,
        credentials: dict[str, Any],
        sql: str,
        params: dict[str, Any] | None = None
    ) -> RowResult:
        """
        Execute a query and return a single row (LIMIT 1 equivalent).

        Useful for lookups, existence checks, and single-record fetches
        without the overhead of returning a full result set.

        Args:
            credentials: Resolved credentials.
            sql: Query string.
            params: Optional named parameters.

        Returns:
            RowResult with the first matching row, or found=False if empty.
        """
        ...
```

---

## 5. Source Registry

`sources/__init__.py` maintains a registry that maps driver strings to source
classes. Sources self-register via a simple decorator to avoid manual maintenance
of the registry dict.

```python
# sources/__init__.py

_SOURCE_REGISTRY: dict[str, type[AbstractDatabaseSource]] = {}

def register_source(driver: str):
    """Decorator that registers a source class under the given driver string."""
    def decorator(cls):
        _SOURCE_REGISTRY[driver] = cls
        return cls
    return decorator

def get_source_class(driver: str) -> type[AbstractDatabaseSource]:
    if driver not in _SOURCE_REGISTRY:
        raise ValueError(
            f"No DatabaseSource registered for driver '{driver}'. "
            f"Available: {list(_SOURCE_REGISTRY.keys())}"
        )
    return _SOURCE_REGISTRY[driver]
```

Each source file applies the decorator at class definition:

```python
# sources/postgres.py
@register_source("postgresql")
class PostgresSource(AbstractDatabaseSource):
    driver = "postgresql"
    sqlglot_dialect = "postgres"
    ...
```

Sources are imported lazily in `get_source_class` to respect the project's
lazy-import convention and avoid pulling in heavy drivers at startup.

---

## 6. DatabaseToolkit

`toolkit.py` — the entry point consumed by agents. Exposes four `AbstractTool`
subclasses as independent tools via `get_tools()`.

### 6.1 Tool argument schemas

Each tool shares a `DatabaseBaseArgs` schema that carries `driver` and optional
`credentials`, then extends it with operation-specific fields.

```python
class DatabaseBaseArgs(AbstractToolArgsSchema):
    driver: str = Field(
        description=(
            "Database driver to use. Supported values: "
            "'postgresql', 'mysql', 'sqlite', 'mongodb', "
            "'documentdb', 'bigquery', 'influxdb', and others."
        )
    )
    credentials: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Optional connection credentials (host, port, user, password, database, etc.). "
            "If omitted, default credentials for the selected driver are used."
        )
    )

class GetMetadataArgs(DatabaseBaseArgs):
    tables: list[str] | None = Field(
        default=None,
        description=(
            "Optional list of table or collection names to inspect. "
            "If omitted, metadata for all accessible tables is returned."
        )
    )

class ValidateQueryArgs(DatabaseBaseArgs):
    query: str = Field(
        description="The query string to validate syntactically before execution."
    )

class ExecuteQueryArgs(DatabaseBaseArgs):
    query: str = Field(
        description="The query to execute. Must be validated before calling this tool."
    )
    params: dict[str, Any] | None = Field(
        default=None,
        description="Optional named parameters for parameterized queries."
    )

class FetchRowArgs(DatabaseBaseArgs):
    query: str = Field(
        description=(
            "The query to execute. Returns a single row only. "
            "Useful for existence checks and single-record lookups."
        )
    )
    params: dict[str, Any] | None = Field(
        default=None,
        description="Optional named parameters."
    )
```

### 6.2 Tool implementations

All four tools follow the standard `AbstractTool._execute(**kwargs) -> ToolResult`
pattern. Each instantiates the source, resolves credentials, and delegates.

```python
class GetDatabaseMetadataTool(AbstractTool):
    name = "get_database_metadata"
    description = (
        "Discover the schema of a database: list tables, collections, or measurements "
        "and their column/field definitions. Call this BEFORE writing any query to "
        "understand the available tables and their structure."
    )
    args_schema = GetMetadataArgs

    def __init__(self, toolkit_ref: "DatabaseToolkit"):
        self._toolkit = toolkit_ref

    async def _execute(self, **kwargs) -> ToolResult:
        ...

class ValidateDatabaseQueryTool(AbstractTool):
    name = "validate_database_query"
    description = (
        "Validate the syntax of a query before execution. "
        "Always call this after writing a query and before calling execute_database_query. "
        "Returns valid=True or a detailed parse error."
    )
    args_schema = ValidateQueryArgs
    ...

class ExecuteDatabaseQueryTool(AbstractTool):
    name = "execute_database_query"
    description = (
        "Execute a validated query against the database and return all matching rows. "
        "Only call this after validate_database_query returns valid=True."
    )
    args_schema = ExecuteQueryArgs
    ...

class FetchDatabaseRowTool(AbstractTool):
    name = "fetch_database_row"
    description = (
        "Execute a query and return a single row. "
        "Use for existence checks, single-record lookups, or when only one result "
        "is expected. More efficient than execute_database_query for single-row needs."
    )
    args_schema = FetchRowArgs
    ...
```

### 6.3 DatabaseToolkit class

```python
class DatabaseToolkit:
    """
    Toolkit that exposes database operations as independent LLM-callable tools.

    Replaces DatabaseQueryTool with four focused tools that avoid the
    multi-purpose parameter ambiguity problem observed with Gemini Flash and GPT.

    Tools exposed:
    - get_database_metadata     → schema discovery
    - validate_database_query   → syntax validation (pre-execution)
    - execute_database_query    → multi-row query execution
    - fetch_database_row        → single-row fetch

    Supported drivers (via asyncdb): postgresql, mysql, sqlite, mongodb,
    documentdb, bigquery, influxdb, and any registered custom source.

    Usage:
        toolkit = DatabaseToolkit()

        agent = BasicAgent(
            name="DataAgent",
            tools=toolkit.get_tools()
        )
    """

    def __init__(self):
        self.logger = logging.getLogger("Parrot.Toolkits.Database")
        self._tools: list[AbstractTool] = []
        self._source_cache: dict[str, AbstractDatabaseSource] = {}
        self._initialize_tools()

    def _initialize_tools(self):
        self._tools = [
            GetDatabaseMetadataTool(toolkit_ref=self),
            ValidateDatabaseQueryTool(toolkit_ref=self),
            ExecuteDatabaseQueryTool(toolkit_ref=self),
            FetchDatabaseRowTool(toolkit_ref=self),
        ]

    def get_source(self, driver: str) -> AbstractDatabaseSource:
        """
        Return (and cache) the source instance for the given driver.
        Sources are instantiated lazily on first use.
        """
        if driver not in self._source_cache:
            source_cls = get_source_class(driver)
            self._source_cache[driver] = source_cls()
        return self._source_cache[driver]

    def get_tools(self) -> list[AbstractTool]:
        return self._tools

    def get_tool_by_name(self, name: str) -> AbstractTool | None:
        return next((t for t in self._tools if t.name == name), None)

    async def cleanup(self):
        for tool in self._tools:
            with contextlib.suppress(Exception):
                await tool.cleanup()
        self._source_cache.clear()
```

---

## 7. Source Implementation Guide

### 7.1 SQL sources (PostgreSQL, MySQL, SQLite, BigQuery)

- Set `sqlglot_dialect` to the appropriate dialect string.
- Inherit `validate_query()` from `AbstractDatabaseSource` (no override needed).
- `get_metadata()` queries `information_schema.tables` / `information_schema.columns`
  via asyncdb using resolved credentials.
- `query()` and `query_row()` use asyncdb's standard fetch interface.

### 7.2 MongoDB / DocumentDB

- `sqlglot_dialect = None` → **must** override `validate_query()`.
- Validation: parse the query string as JSON and verify it is a valid dict
  (filter document) or a list of dicts (aggregation pipeline).
- `get_metadata()` uses `list_collection_names()` + `$sample` to infer field types.
- `query()` accepts a JSON string representing a filter or pipeline.
- `DocumentDBSource` extends `MongoSource`; only credential resolution differs.

### 7.3 InfluxDB

- `sqlglot_dialect = None` → **must** override `validate_query()`.
- For **InfluxQL**: attempt parse via `influxdb-client` parser utilities.
- For **Flux**: attempt a dry-run query against the `/api/v2/query` endpoint
  with a zero-range guard to avoid data retrieval.
- `get_metadata()` returns buckets as "tables" and field keys as "columns".

---

## 8. Recommended Agent Usage Pattern

The toolkit encourages a three-step agentic flow that significantly reduces
query errors in practice:

```
1. get_database_metadata(driver, tables?)
        ↓ understand schema
2. validate_database_query(driver, query)
        ↓ confirm syntax before touching the DB
3. execute_database_query(driver, query)
   — or —
   fetch_database_row(driver, query)
```

This pattern should be reflected in the agent's system prompt when the
`DatabaseToolkit` is included in its tools.

---

## 9. Dependencies

| Package       | Usage                                      | Already present |
|---------------|--------------------------------------------|-----------------|
| `asyncdb`     | All DB connections and query execution     | ✅ Yes           |
| `sqlglot`     | SQL syntax validation for SQL dialects     | ➕ Add           |
| `pydantic` v2 | Result models and args schemas             | ✅ Yes           |
| `navconfig`   | Logging, settings for default credentials  | ✅ Yes           |

`sqlglot` is pure Python, no system dependencies, ~2MB. Install via:
```
uv add sqlglot
```

---

## 10. Migration from DatabaseQueryTool

`DatabaseQueryTool` is **not removed** in this iteration. Both can coexist.
Agents that used `DatabaseQueryTool` can be migrated by replacing the tool
list with `DatabaseToolkit().get_tools()` and updating the system prompt to
reference the three-step pattern described in section 8.

---

## 11. Out of Scope (v1)

- Connection pooling per `(driver, credentials)` pair — open/close per call is
  acceptable for conversational agent workloads.
- `EXPLAIN`-based query validation — deferred to a future iteration.
- Query result pagination — deferred; callers can use `LIMIT`/`OFFSET` in the query.
- Cross-database joins or federation — not in scope.
