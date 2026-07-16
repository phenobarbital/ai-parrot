---
type: Wiki Overview
title: 'Feature Specification: sqlagent-repair'
id: doc:sdd-specs-sqlagent-repair-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'AI-Parrot has two overlapping database agent packages that solve complementary
  halves of the same problem:'
relates_to:
- concept: mod:parrot.bots
  rel: mentions
- concept: mod:parrot.bots.abstract
  rel: mentions
- concept: mod:parrot.bots.database
  rel: mentions
- concept: mod:parrot.bots.database.cache
  rel: mentions
- concept: mod:parrot.bots.database.models
  rel: mentions
- concept: mod:parrot.bots.database.retries
  rel: mentions
- concept: mod:parrot.bots.database.router
  rel: mentions
- concept: mod:parrot.bots.database.toolkits
  rel: mentions
- concept: mod:parrot.conf
  rel: mentions
- concept: mod:parrot.memory
  rel: mentions
- concept: mod:parrot.models
  rel: mentions
- concept: mod:parrot.stores.abstract
  rel: mentions
- concept: mod:parrot.tools.manager
  rel: mentions
- concept: mod:parrot.tools.toolkit
  rel: mentions
---

# Feature Specification: sqlagent-repair

**Feature ID**: FEAT-082
**Date**: 2026-04-04
**Author**: Jesus Lara + Claude
**Status**: approved
**Target version**: next minor
**Brainstorm**: `sdd/proposals/sqlagent-repair.brainstorm.md`

---

## 1. Motivation & Business Requirements

### Problem Statement

AI-Parrot has two overlapping database agent packages that solve complementary halves of the same problem:

- **`parrot/bots/db/`** (6,386 lines, 12 files) — supports multiple database types (PostgreSQL, BigQuery, InfluxDB, Elasticsearch, DocumentDB) via one-agent-per-database-type pattern. Uses individual `AbstractTool` subclasses. Lacks user roles, output components, intent routing, and retry logic. Schema cache is Redis-only with basic TTL.

- **`parrot/bots/database/`** (4,396 lines, 8 files) — rich model layer with `UserRole`, `OutputComponent` (bitwise flags), `QueryIntent`, `RouteDecision`, `DatabaseResponse`, `QueryRetryConfig`/`SQLRetryHandler`, and two-tier caching (LRU + vector store). Only supports SQL databases via SQLAlchemy async.

Neither package is complete. The `bots/db` package has all the drivers but poor architecture. The `bots/database` package has the right abstractions but only one driver. Both are partially broken due to recent refactoring.

Additionally, `parrot_tools/database/` has standalone schema search tools (`PgSchemaSearchTool`, `BQSchemaSearchTool`) that duplicate logic that should live inside per-database toolkits.

### Goals

1. **Unify** into a single package at `parrot/bots/database/` with all drivers and all models.
2. **Toolkit-based architecture**: one `AbstractToolkit` subclass per database type, with inheritance hierarchy `DatabaseToolkit` -> `SQLToolkit` -> `PostgresToolkit`/`BigQueryToolkit` etc.
3. **One unified Agent** (`DatabaseAgent`) that holds N toolkits, with hybrid routing (explicit + LLM-inferred database selection).
4. **Per-request user role** with three-tier resolution: explicit param > router-inferred from intent > agent default.
5. **CacheManager** with namespaced partitions per database (shared Redis pool + shared vector store, independent LRU sizing/TTL per partition).
6. **asyncdb as default** backend with sqlalchemy-async as opt-in via `backend` config.
7. **Delete `parrot/bots/db/`** and absorb `parrot_tools/database/pg.py` + `bq.py` into toolkits.

### Non-Goals (explicitly out of scope)

- Plugin/entry-point architecture for third-party database adapters.
- Connection pooling optimization (current open/close per call is acceptable).
- Cross-database joins or federation.
- Removing `QueryToolkit` from `parrot_tools/` (it serves a different purpose: pre-built query slugs).
- Removing FEAT-062 `DatabaseToolkit` in `parrot_tools/` (that is a separate, complementary feature for `DatabaseQueryTool` replacement at the tools level).

---

## 2. Architectural Design

### Overview

Replace the one-agent-per-database pattern with a toolkit-first architecture. Each database type is a toolkit class (inheriting `AbstractToolkit`) that encapsulates all operations. A thin `DatabaseAgent` orchestrates toolkits via a router and cache manager.

### Component Diagram

```
DatabaseAgent (orchestration, LLM interaction, response formatting)
  │
  ├── SchemaQueryRouter (intent detection, role inference, database selection)
  │
  ├── CacheManager (namespaced partitions, shared Redis + vector store)
  │     ├── Partition: "postgres_sales" (LRU maxsize=500, TTL=1800s)
  │     ├── Partition: "bigquery_analytics" (LRU maxsize=200, TTL=3600s)
  │     └── Partition: "influx_metrics" (LRU maxsize=100, TTL=900s)
  │
  ├── PostgresToolkit(SQLToolkit(DatabaseToolkit(AbstractToolkit)))
  │     ├── search_schema()     → LLM tool: "postgres_sales.search_schema"
  │     ├── generate_query()    → LLM tool: "postgres_sales.generate_query"
  │     ├── execute_query()     → LLM tool: "postgres_sales.execute_query"
  │     ├── explain_query()     → LLM tool: "postgres_sales.explain_query"
  │     └── validate_query()    → LLM tool: "postgres_sales.validate_query"
  │
  ├── BigQueryToolkit(SQLToolkit(DatabaseToolkit))
  │     └── (same methods, BigQuery-specific overrides)
  │
  ├── InfluxDBToolkit(DatabaseToolkit)
  │     ├── search_measurements()
  │     ├── generate_flux_query()
  │     ├── execute_flux_query()
  │     └── explore_buckets()
  │
  ├── ElasticToolkit(DatabaseToolkit)
  │     ├── search_indices()
  │     ├── generate_dsl_query()
  │     ├── execute_query()
  │     └── run_aggregation()
  │
  └── DocumentDBToolkit(DatabaseToolkit)
        ├── search_collections()
        ├── generate_mql_query()
        ├── execute_query()
        └── explore_collection()
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractToolkit` (`parrot/tools/toolkit.py:140`) | inherits | `DatabaseToolkit` base inherits from it |
| `AbstractBot` (`parrot/bots/abstract.py:92`) | inherits | `DatabaseAgent` inherits from it (replaces current `AbstractDBAgent`) |
| `ToolManager` (`parrot/tools/manager.py:192`) | uses | Agent registers toolkit tools via `register_toolkit()` |
| `AbstractStore` (`parrot/stores/abstract.py`) | uses | CacheManager uses for vector store tier |
| `SchemaMetadataCache` (`parrot/bots/database/cache.py:11`) | wraps | CacheManager wraps with partitioning |
| `SchemaQueryRouter` (`parrot/bots/database/router.py:15`) | extends | Add database selection + role inference |
| `QueryRetryConfig`/`SQLRetryHandler` (`parrot/bots/database/retries.py`) | extends | Generalize for non-SQL databases |
| `AsyncDB` (`asyncdb`) | uses | Default backend for all toolkits |

### Data Models

All existing models from `parrot/bots/database/models.py` are preserved unchanged:

```python
# Preserved as-is from models.py
class UserRole(str, Enum): ...          # line 15
class OutputComponent(Flag): ...         # line 24
class OutputFormat(str, Enum): ...       # line 45
class QueryIntent(str, Enum): ...        # line 72
class SchemaMetadata: ...                # line 84
class TableMetadata: ...                 # line 104
class QueryExecutionRequest(BaseModel): ... # line 170
class QueryExecutionResponse(BaseModel): ... # line 180
class DatabaseResponse: ...              # line 269
```

New/modified models:

```python
@dataclass
class RouteDecision:
    """Extended with database selection and inferred role."""
    intent: QueryIntent
    components: OutputComponent
    user_role: UserRole
    primary_schema: str
    allowed_schemas: List[str]
    # NEW: database selection
    target_database: Optional[str] = None  # toolkit identifier
    role_source: str = "default"  # "explicit", "inferred", "default"
    # existing fields...
    needs_metadata_discovery: bool = True
    needs_query_generation: bool = True
    needs_execution: bool = True
    needs_plan_analysis: bool = False
    data_limit: Optional[int] = 1000
    include_full_data: bool = False
    convert_to_dataframe: bool = False
    execution_options: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.8


class CachePartitionConfig(BaseModel):
    """Configuration for a single cache partition."""
    namespace: str
    lru_maxsize: int = 500
    lru_ttl: int = 1800  # seconds
    redis_ttl: int = 3600  # seconds


class DatabaseToolkitConfig(BaseModel):
    """Configuration passed to toolkit constructors."""
    dsn: Optional[str] = None
    allowed_schemas: List[str] = ["public"]
    primary_schema: Optional[str] = None
    backend: str = "asyncdb"  # "asyncdb" | "sqlalchemy"
    cache_config: Optional[CachePartitionConfig] = None
```

### New Public Interfaces

```python
# === DatabaseToolkit base (new) ===
class DatabaseToolkit(AbstractToolkit, ABC):
    """Base class for all database toolkits."""

    def __init__(
        self,
        dsn: str,
        allowed_schemas: List[str] = ["public"],
        primary_schema: Optional[str] = None,
        backend: str = "asyncdb",
        cache_partition: Optional[CachePartition] = None,
        retry_config: Optional[QueryRetryConfig] = None,
        **kwargs
    ): ...

    # Abstract methods each toolkit must implement
    @abstractmethod
    async def search_schema(self, search_term: str, ...) -> List[TableMetadata]: ...
    @abstractmethod
    async def execute_query(self, query: str, limit: int = 1000, ...) -> QueryExecutionResponse: ...

    # Concrete shared methods
    async def start(self) -> None: ...   # connect to database
    async def stop(self) -> None: ...    # close connections
    async def get_table_metadata(self, schema: str, table: str) -> Optional[TableMetadata]: ...


# === SQLToolkit (new) ===
class SQLToolkit(DatabaseToolkit):
    """Common SQL operations. Override specific methods for dialect differences."""

    async def search_schema(self, search_term: str, ...) -> List[TableMetadata]: ...
    async def generate_query(self, natural_language: str, target_tables: Optional[List[str]] = None) -> str: ...
    async def execute_query(self, query: str, limit: int = 1000, timeout: int = 30) -> QueryExecutionResponse: ...
    async def explain_query(self, query: str) -> str: ...
    async def validate_query(self, sql: str) -> Dict[str, Any]: ...

    # Overridable dialect hooks
    def _get_explain_prefix(self) -> str: ...         # "EXPLAIN ANALYZE" for PG
    def _get_information_schema_query(self) -> str: ... # dialect-specific introspection
    def _build_dsn(self, raw_dsn: str) -> str: ...    # ensure async driver


# === PostgresToolkit (new) ===
class PostgresToolkit(SQLToolkit):
    """PostgreSQL-specific overrides."""
    def _get_explain_prefix(self) -> str:
        return "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)"
    # ... PG-specific information_schema queries


# === CacheManager (new) ===
class CacheManager:
    """Manages namespaced cache partitions with shared Redis + vector store."""

    def __init__(
        self,
        redis_url: Optional[str] = None,
        vector_store: Optional[AbstractStore] = None
    ): ...

    def create_partition(self, config: CachePartitionConfig) -> CachePartition: ...
    def get_partition(self, namespace: str) -> Optional[CachePartition]: ...
    async def search_across_databases(self, query: str, limit: int = 5) -> List[TableMetadata]: ...
    async def close(self) -> None: ...


# === DatabaseAgent (rewrite of AbstractDBAgent) ===
class DatabaseAgent(AbstractBot):
    """Unified database agent with multi-toolkit support."""

    def __init__(
        self,
        name: str = "DatabaseAgent",
        toolkits: List[DatabaseToolkit] = None,
        default_user_role: UserRole = UserRole.DATA_ANALYST,
        vector_store: Optional[AbstractStore] = None,
        redis_url: Optional[str] = None,
        system_prompt_template: Optional[str] = None,
        **kwargs
    ): ...

    async def configure(self, app=None) -> None: ...

    async def ask(
        self,
        query: str,
        user_role: Optional[UserRole] = None,  # per-request override
        database: Optional[str] = None,         # explicit toolkit selection
        context: Optional[str] = None,
        output_components: Optional[Union[str, OutputComponent]] = None,
        output_format: Optional[Union[str, Type[BaseModel]]] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        enable_retry: bool = True,
        **kwargs
    ) -> AIMessage: ...
```

---

## 3. Module Breakdown

### Module 1: CacheManager
- **Path**: `parrot/bots/database/cache.py`
- **Responsibility**: Replace current `SchemaMetadataCache` with `CacheManager` that creates namespaced `CachePartition` instances. Each partition has its own LRU (via `cachetools.TTLCache`) with configurable `maxsize` and `ttl`. All partitions share one Redis connection pool (via `aioredis`) and one optional vector store (`AbstractStore`). Provides `search_across_databases()` for cross-partition queries.
- **Depends on**: `cachetools`, `redis[hiredis]`, `parrot.stores.abstract.AbstractStore`
- **Preserves**: `SchemaMetadataCache` API surface (get/store/search) within each partition

### Module 2: DatabaseToolkit base
- **Path**: `parrot/bots/database/toolkits/base.py`
- **Responsibility**: Abstract base class inheriting `AbstractToolkit`. Defines the contract for all database toolkits: `search_schema()`, `execute_query()`, `start()`, `stop()`, `get_table_metadata()`. Accepts `CachePartition` and `QueryRetryConfig` at init. Methods decorated as tools via `AbstractToolkit._generate_tools()`.
- **Depends on**: `parrot.tools.toolkit.AbstractToolkit`, Module 1 (CacheManager/CachePartition), `parrot.bots.database.retries.QueryRetryConfig`

### Module 3: SQLToolkit
- **Path**: `parrot/bots/database/toolkits/sql.py`
- **Responsibility**: Concrete toolkit for SQL databases. Implements `search_schema()` using information_schema queries, `generate_query()` via LLM prompt, `execute_query()` via asyncdb or sqlalchemy-async, `explain_query()` with dialect-specific prefix, `validate_query()`. Provides overridable hooks for dialect differences: `_get_explain_prefix()`, `_get_information_schema_query()`, `_build_dsn()`, `_get_sample_data_query()`.
- **Depends on**: Module 2 (DatabaseToolkit), `asyncdb.AsyncDB`, `sqlalchemy.ext.asyncio`

### Module 4: PostgresToolkit
- **Path**: `parrot/bots/database/toolkits/postgres.py`
- **Responsibility**: PostgreSQL-specific overrides of `SQLToolkit`. Overrides `_get_explain_prefix()` for `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`, `_get_information_schema_query()` for `pg_class`/`pg_namespace` joins, `_build_dsn()` for `postgresql+asyncpg://` driver. Absorbs logic from `parrot_tools/database/pg.py:PgSchemaSearchTool.analyze_table()`.
- **Depends on**: Module 3 (SQLToolkit)

### Module 5: BigQueryToolkit
- **Path**: `parrot/bots/database/toolkits/bigquery.py`
- **Responsibility**: BigQuery-specific overrides of `SQLToolkit`. Overrides schema introspection for `INFORMATION_SCHEMA.TABLES`/`COLUMNS` BigQuery syntax, query execution via `google-cloud-bigquery` client or asyncdb bigquery driver, `_get_explain_prefix()` for BigQuery's dry-run cost estimation. Absorbs `parrot_tools/database/bq.py:BQSchemaSearchTool`.
- **Depends on**: Module 3 (SQLToolkit), `google-cloud-bigquery` (optional)

### Module 6: InfluxDBToolkit
- **Path**: `parrot/bots/database/toolkits/influx.py`
- **Responsibility**: InfluxDB toolkit inheriting directly from `DatabaseToolkit` (not `SQLToolkit`). Implements `search_measurements()`, `generate_flux_query()`, `execute_flux_query()`, `explore_buckets()`. Port from `parrot/bots/db/influx.py:InfluxDBAgent`.
- **Depends on**: Module 2 (DatabaseToolkit), `asyncdb` influx driver

### Module 7: ElasticToolkit
- **Path**: `parrot/bots/database/toolkits/elastic.py`
- **Responsibility**: Elasticsearch toolkit inheriting from `DatabaseToolkit`. Implements `search_indices()`, `generate_dsl_query()`, `execute_query()`, `run_aggregation()`. Port from `parrot/bots/db/elastic.py:ElasticDbAgent`.
- **Depends on**: Module 2 (DatabaseToolkit), `asyncdb` elasticsearch driver

### Module 8: DocumentDBToolkit
- **Path**: `parrot/bots/database/toolkits/documentdb.py`
- **Responsibility**: DocumentDB/MongoDB toolkit inheriting from `DatabaseToolkit`. Implements `search_collections()`, `generate_mql_query()`, `execute_query()`, `explore_collection()`. Port from `parrot/bots/db/documentdb.py:DocumentDBAgent`.
- **Depends on**: Module 2 (DatabaseToolkit), `asyncdb` documentdb driver

### Module 9: Extended Router
- **Path**: `parrot/bots/database/router.py`
- **Responsibility**: Extend `SchemaQueryRouter` with: (a) database selection — if query mentions a known database/toolkit name, set `target_database` in `RouteDecision`; (b) role inference — map detected `QueryIntent` to a suggested `UserRole` when no explicit role is provided. Add `INTENT_ROLE_MAPPING` dict.
- **Depends on**: existing `parrot/bots/database/models.py`

### Module 10: Extended RetryHandler
- **Path**: `parrot/bots/database/retries.py`
- **Responsibility**: Generalize `SQLRetryHandler` to work with any toolkit (not just SQLAlchemy engine). Add `RetryHandler` base class that toolkits can subclass. Keep `SQLRetryHandler(RetryHandler)` for SQL-specific error patterns. Add `FluxRetryHandler`, `DSLRetryHandler` stubs for future use.
- **Depends on**: Module 2 (DatabaseToolkit)

### Module 11: DatabaseAgent
- **Path**: `parrot/bots/database/agent.py`
- **Responsibility**: Rewrite of current `AbstractDBAgent`. Thin orchestration layer: holds list of toolkits, `CacheManager`, extended `SchemaQueryRouter`. Implements `ask()` with three-tier role resolution (explicit > inferred > default), hybrid database routing, response formatting via `DatabaseResponse`. Registers toolkit tools with `ToolManager`. System prompt dynamically built from registered toolkits' capabilities.
- **Depends on**: Modules 1-10

### Module 12: Cleanup & Migration
- **Path**: `parrot/bots/database/__init__.py`, `parrot/bots/db/` (delete), `parrot_tools/database/pg.py` (delete), `parrot_tools/database/bq.py` (delete)
- **Responsibility**: Update `__init__.py` exports to expose `DatabaseAgent`, all toolkit classes, and `CacheManager`. Delete `parrot/bots/db/` directory. Delete absorbed tools from `parrot_tools/database/`.
- **Depends on**: All previous modules

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_cache_partition_isolation` | Module 1 | Two partitions don't interfere with each other's entries |
| `test_cache_partition_lru_eviction` | Module 1 | Partition respects its own maxsize and TTL |
| `test_cache_search_across_databases` | Module 1 | Cross-partition search returns results from all partitions |
| `test_cache_redis_fallback` | Module 1 | Works with LRU-only when Redis is unavailable |
| `test_database_toolkit_tool_generation` | Module 2 | `get_tools()` returns tools from public async methods |
| `test_database_toolkit_exclude_tools` | Module 2 | `exclude_tools` prevents method from becoming a tool |
| `test_sql_toolkit_search_schema` | Module 3 | Schema search returns `TableMetadata` objects |
| `test_sql_toolkit_execute_query` | Module 3 | Query execution returns `QueryExecutionResponse` |
| `test_sql_toolkit_backend_selection` | Module 3 | `backend="asyncdb"` vs `backend="sqlalchemy"` routes correctly |
| `test_postgres_explain_prefix` | Module 4 | Returns `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` |
| `test_postgres_information_schema` | Module 4 | Uses `pg_class`/`pg_namespace` joins |
| `test_bigquery_dry_run` | Module 5 | BigQuery explain uses dry-run cost estimation |
| `test_influx_flux_query` | Module 6 | Generates valid Flux query syntax |
| `test_elastic_dsl_query` | Module 7 | Generates valid Elasticsearch DSL |
| `test_documentdb_mql` | Module 8 | Generates valid MongoDB query language |
| `test_router_role_inference` | Module 9 | "optimize this query" → `DATABASE_ADMIN` |
| `test_router_database_selection` | Module 9 | Mentions of BigQuery set `target_database` |
| `test_router_explicit_role_priority` | Module 9 | Explicit role beats inferred beats default |
| `test_retry_handler_sql` | Module 10 | SQL retry handler detects retryable errors |
| `test_retry_handler_generic` | Module 10 | Base retry handler works for non-SQL toolkits |
| `test_agent_single_toolkit` | Module 11 | Agent with one toolkit responds correctly |
| `test_agent_multi_toolkit` | Module 11 | Agent with N toolkits routes to correct one |
| `test_agent_role_resolution` | Module 11 | Three-tier role resolution works correctly |

### Integration Tests

| Test | Description |
|---|---|
| `test_postgres_end_to_end` | Full flow: configure → search schema → generate query → execute → format response (requires PostgreSQL) |
| `test_multi_database_routing` | Agent with PG + mock toolkit routes queries correctly |
| `test_cache_persistence` | Metadata survives LRU eviction via Redis/vector store tiers |

### Test Data / Fixtures

```python
@pytest.fixture
def mock_cache_manager():
    """CacheManager with in-memory partitions (no Redis)."""
    return CacheManager(redis_url=None, vector_store=None)

@pytest.fixture
def sample_table_metadata():
    return TableMetadata(
        schema="public", tablename="orders", table_type="BASE TABLE",
        full_name='"public"."orders"',
        columns=[{"name": "id", "type": "integer", "nullable": False}],
        primary_keys=["id"], foreign_keys=[], indexes=[], row_count=1000
    )

@pytest.fixture
def mock_postgres_toolkit(mock_cache_manager):
    """PostgresToolkit with mocked database connection."""
    partition = mock_cache_manager.create_partition(
        CachePartitionConfig(namespace="test_pg", lru_maxsize=50)
    )
    return PostgresToolkit(
        dsn="postgresql://test:test@localhost/test",
        allowed_schemas=["public"],
        backend="asyncdb",
        cache_partition=partition
    )
```

---

## 5. Acceptance Criteria

- [ ] `DatabaseAgent` works with a single `PostgresToolkit` — configure, ask, get response
- [ ] `DatabaseAgent` works with multiple toolkits — queries route to correct toolkit
- [ ] Per-request `user_role` overrides agent default; router infers role when not provided
- [ ] `CacheManager` partitions are isolated (different maxsize/TTL per toolkit)
- [ ] `CacheManager` falls back gracefully when Redis is unavailable (LRU-only mode)
- [ ] All 6 `UserRole` types produce correct `OutputComponent` combinations
- [ ] `SQLToolkit` inheritance works: `PostgresToolkit` and `BigQueryToolkit` override only what differs
- [ ] `QueryRetryConfig` works for SQL toolkits (retries on type errors, column-not-found, etc.)
- [ ] `parrot/bots/db/` is deleted with no remaining imports
- [ ] `parrot_tools/database/pg.py` and `bq.py` are deleted with no remaining imports
- [ ] All unit tests pass (`pytest tests/unit/ -v`)
- [ ] No breaking changes to existing `parrot/bots/database/models.py` public API
- [ ] asyncdb is default backend; `backend="sqlalchemy"` works for PostgreSQL

---

## 6. Codebase Contract

### Verified Imports

```python
# Toolkit infrastructure
from parrot.tools.toolkit import AbstractToolkit       # parrot/tools/toolkit.py:140
from parrot.tools.manager import ToolManager           # parrot/tools/manager.py:192

# Bot infrastructure
from parrot.bots.abstract import AbstractBot           # parrot/bots/abstract.py:92

# Models (all preserved)
from parrot.bots.database.models import (
    UserRole,                    # models.py:15
    OutputComponent,             # models.py:24
    OutputFormat,                # models.py:45
    QueryIntent,                 # models.py:72
    SchemaMetadata,              # models.py:84
    TableMetadata,               # models.py:104
    QueryExecutionRequest,       # models.py:170
    QueryExecutionResponse,      # models.py:180
    RouteDecision,               # models.py:241
    DatabaseResponse,            # models.py:269
    get_default_components,      # models.py:412
    components_from_string,      # models.py:432
    ROLE_COMPONENT_DEFAULTS,     # models.py:197
    INTENT_COMPONENT_MAPPING,    # models.py:459
)

# Cache (to be extended)
from parrot.bots.database.cache import SchemaMetadataCache  # cache.py:11

# Router (to be extended)
from parrot.bots.database.router import SchemaQueryRouter   # router.py:15

# Retry (to be extended)
from parrot.bots.database.retries import QueryRetryConfig, SQLRetryHandler  # retries.py:6,31

# Stores
from parrot.stores.abstract import AbstractStore            # parrot/stores/abstract.py

# Response models
from parrot.models import AIMessage, CompletionUsage        # parrot/models.py

# Memory
from parrot.memory import ConversationTurn                  # parrot/memory/__init__.py

# External
from asyncdb import AsyncDB                                  # external package
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine  # external

…(truncated)…
