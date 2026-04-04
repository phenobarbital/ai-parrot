# Brainstorm: sqlagent-repair

**Date**: 2026-04-04
**Author**: Jesus Lara + Claude
**Status**: exploration
**Recommended Option**: Option B

---

## Problem Statement

AI-Parrot has two overlapping database agent packages that solve complementary halves of the same problem:

- **`parrot/bots/db/`** (6,386 lines) — Supports multiple database types (PostgreSQL, BigQuery, InfluxDB, Elasticsearch, DocumentDB) via one-agent-per-database-type pattern. Uses individual `AbstractTool` subclasses (not toolkits). Lacks user roles, output components, intent routing, and retry logic. Schema cache is Redis-only with basic TTL.

- **`parrot/bots/database/`** (4,396 lines) — Rich model layer with `UserRole`, `OutputComponent` (bitwise flags), `QueryIntent`, `RouteDecision`, `DatabaseResponse`, `QueryRetryConfig`/`SQLRetryHandler`, and two-tier caching (LRU + vector store). Only supports SQL databases via SQLAlchemy async.

Neither package is complete on its own. The `bots/db` package has all the drivers but poor architecture. The `bots/database` package has the right abstractions but only one driver. Both are partially broken due to recent refactoring. The goal is to unify them into a single package at `parrot/bots/database/` with:

1. All database drivers from `bots/db` (PostgreSQL, BigQuery, InfluxDB, Elasticsearch, DocumentDB)
2. All rich models from `bots/database` (UserRole, OutputComponent, QueryIntent, etc.)
3. **Toolkit-based architecture** (one `AbstractToolkit` subclass per database type)
4. **One unified Agent** with multiple toolkits, hybrid routing, and role-aware output
5. **CacheManager** with namespaced partitions per database (shared Redis pool + vector store)
6. **asyncdb as default backend** with sqlalchemy-async as configurable alternative

**Who is affected:** Any developer building database-powered agents with AI-Parrot.
**Why now:** Both packages are broken post-refactoring; merging prevents further divergence.

## Constraints & Requirements

- Must keep `parrot/bots/database/` as the canonical location
- `parrot/bots/db/` will be deleted after unification is complete
- No existing consumers to migrate (clean break)
- asyncdb is the default backend; sqlalchemy-async is opt-in via `backend` config
- Toolkits must be explicitly instantiated (not auto-registered by string)
- Multi-database support requires a hybrid router (explicit database selection when provided, LLM-inferred otherwise)
- **User role is per-request, not per-agent**: `ask(query, user_role=...)` overrides the agent's default role. When no role is provided, the router infers it from query intent (e.g., "optimize this query" -> `DATABASE_ADMIN`, "show me sales" -> `BUSINESS_USER`). Agent constructor sets a fallback default only.
- Cache must use a single CacheManager with per-database namespaced partitions
- Per-database toolkit inheritance: `SQLToolkit` -> `PostgresToolkit(SQLToolkit)` where subclasses only override what differs
- All async, no blocking I/O
- Must preserve `QueryRetryConfig`/`SQLRetryHandler` for error recovery
- Must preserve all models: `UserRole`, `OutputComponent`, `QueryIntent`, `RouteDecision`, `DatabaseResponse`

---

## Options Explored

### Option A: Incremental Migration — Port Drivers into Existing `bots/database`

Port each driver from `bots/db` into the existing `AbstractDBAgent` in `bots/database/abstract.py` by adding database-type-specific methods directly into the agent class hierarchy. Keep the current tool-based approach (individual `AbstractTool` subclasses), extending it with more tools per database.

**Pros:**
- Least disruptive — existing `bots/database` code stays mostly intact
- Lower effort — no toolkit refactoring needed
- Models, router, cache, retries all stay untouched

**Cons:**
- Agent class becomes enormous (the current `abstract.py` is already 3,071 lines)
- Individual tool classes proliferate (one per action per database type)
- Doesn't solve the core problem: tools aren't grouped, can't share state within a database context
- Adding a new database type requires creating 4-6 separate tool classes + agent subclass
- Multi-database routing remains awkward without toolkit encapsulation

**Effort:** Medium

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `asyncdb` | Unified async DB connections | Already in use, supports pg/bigquery/influx/elastic/documentdb |
| `sqlalchemy[asyncio]` | Alternative SQL backend | Optional, for databases not covered by asyncdb |
| `cachetools` | LRU cache | Already used in `bots/database/cache.py` |
| `redis[hiredis]` | Redis connection for cache | Adding Redis tier to existing LRU cache |

**Existing Code to Reuse:**
- `parrot/bots/database/abstract.py` — Base agent (keep as-is, extend)
- `parrot/bots/database/models.py` — All models (untouched)
- `parrot/bots/db/sql.py` — Port SQL-specific connection/query logic
- `parrot/bots/db/bigquery.py` — Port BigQuery connection/query logic
- `parrot/bots/db/influx.py` — Port InfluxDB connection/query logic
- `parrot/bots/db/elastic.py` — Port Elasticsearch connection/query logic
- `parrot/bots/db/documentdb.py` — Port DocumentDB connection/query logic

---

### Option B: Toolkit-First Rewrite — One Agent + Per-Database Toolkits

Refactor the architecture around `AbstractToolkit` subclasses. Create a toolkit inheritance hierarchy: `DatabaseToolkit` (base) -> `SQLToolkit` -> `PostgresToolkit`, `BigQueryToolkit`, etc. Each toolkit encapsulates all operations for its database type (`search_schema`, `generate_query`, `execute_query`, `explain_query`). The agent becomes thin — it owns the router, cache manager, and LLM interaction, delegating database operations to its registered toolkits.

**Architecture:**

```
DatabaseAgent (thin, owns router + cache + LLM)
  ├── PostgresToolkit(SQLToolkit(DatabaseToolkit))
  ├── BigQueryToolkit(SQLToolkit(DatabaseToolkit))
  ├── InfluxDBToolkit(DatabaseToolkit)
  ├── ElasticToolkit(DatabaseToolkit)
  └── DocumentDBToolkit(DatabaseToolkit)
```

Each toolkit method becomes an LLM-callable tool automatically via `AbstractToolkit._generate_tools()`.

**Pros:**
- Clean separation of concerns: agent handles orchestration, toolkits handle database operations
- Adding a new database = one new toolkit class (no agent changes)
- `SQLToolkit` base handles common SQL patterns; subclasses override only what differs (EXPLAIN syntax, information_schema queries, DSN format)
- Tools are naturally grouped and can share connection/state within a toolkit instance
- Multi-database is natural: agent holds N toolkits, router picks which toolkit's tools to expose per-turn
- Explicit instantiation gives full control over configuration per database
- Aligns with AI-Parrot's existing toolkit patterns (76 toolkits already use `AbstractToolkit`)

**Cons:**
- Higher effort — requires restructuring `AbstractDBAgent` significantly
- Must carefully split 3,071 lines of `abstract.py` between agent and toolkits
- Some cross-cutting concerns (schema cache, retry handler) need to be injected into toolkits
- Integration testing across all database types is substantial

**Effort:** High

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `asyncdb` | Default async DB connections | Supports pg, bigquery, influx, elastic, documentdb |
| `sqlalchemy[asyncio]` | Alternative SQL backend | Opt-in via `backend="sqlalchemy"` |
| `cachetools` | LRU cache partitions | Per-toolkit namespace within CacheManager |
| `redis[hiredis]` | Shared Redis connection pool | Single pool, namespaced keys |
| `parrot.tools.toolkit` | AbstractToolkit base | Auto-generates tools from async methods |

**Existing Code to Reuse:**
- `parrot/tools/toolkit.py:140` — `AbstractToolkit` base class with auto-tool-generation
- `parrot/bots/database/models.py` — All models (untouched)
- `parrot/bots/database/router.py` — `SchemaQueryRouter` (extend for multi-database)
- `parrot/bots/database/cache.py` — `SchemaMetadataCache` (wrap in CacheManager)
- `parrot/bots/database/retries.py` — `QueryRetryConfig`/`SQLRetryHandler` (inject into toolkits)
- `parrot/bots/db/sql.py:616-820` — SQL query generation/execution logic (move into SQLToolkit)
- `parrot/bots/db/bigquery.py:123-200` — BigQuery connection/schema logic (move into BigQueryToolkit)
- `parrot/bots/db/influx.py:89-190` — InfluxDB connection/query logic (move into InfluxDBToolkit)
- `parrot/bots/db/elastic.py:92-150` — Elasticsearch connection/query logic (move into ElasticToolkit)
- `parrot/bots/db/documentdb.py:101-200` — DocumentDB connection/query logic (move into DocumentDBToolkit)
- `parrot_tools/querytoolkit.py:89` — `QueryToolkit` (reference for asyncdb patterns)
- `parrot_tools/database/pg.py:10` — `PgSchemaSearchTool` (absorb into PostgresToolkit)
- `parrot_tools/database/bq.py:10` — `BQSchemaSearchTool` (absorb into BigQueryToolkit)

---

### Option C: Plugin Architecture — Database Adapters as Entry Points

Create a plugin system where each database type is a separate installable package (or at minimum a separate module) that registers itself via entry points or a registry pattern. The core agent knows nothing about specific databases — it discovers available adapters at runtime.

**Pros:**
- Maximum extensibility — third parties can add database support without touching core
- Cleanest separation — core agent has zero database-specific code
- Each database adapter is independently testable and deployable
- Could support community-contributed adapters

**Cons:**
- Over-engineered for the current need (5 known database types)
- Runtime discovery adds complexity and debugging difficulty
- Entry point registration adds deployment complexity
- No existing precedent in AI-Parrot for this pattern
- Harder to share infrastructure (cache, retry) across adapters without tight coupling

**Effort:** High

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `asyncdb` | DB connections | Same as other options |
| `importlib.metadata` | Entry point discovery | stdlib |
| `parrot.tools.toolkit` | Base toolkit | Same as Option B |

**Existing Code to Reuse:**
- `parrot/tools/registry.py` — `ToolkitRegistry` (extend for database adapters)
- Same code from `bots/db/` and `bots/database/` as Option B

---

## Recommendation

**Option B** is recommended because:

1. **Aligns with project patterns**: AI-Parrot already has 76+ toolkits inheriting from `AbstractToolkit`. Database toolkits follow the same proven pattern.
2. **Natural multi-database**: One agent with N toolkits is exactly how `AbstractToolkit` + `ToolManager` were designed to work. The agent registers toolkits explicitly, and the LLM sees all tools with clear database-context prefixes.
3. **Inheritance solves the SQL dialect problem**: `SQLToolkit` handles 90% of SQL operations; `PostgresToolkit` overrides `_get_explain_query()`, `_get_information_schema_query()`, etc. BigQuery overrides dataset-specific methods. This avoids duplicating SQL logic across all SQL databases.
4. **CacheManager with partitions**: Each toolkit gets its own partition (own LRU maxsize + TTL) but shares one Redis connection pool and one vector store. This gives isolation without resource proliferation.
5. **Manageable effort**: While higher than Option A, the `AbstractToolkit` auto-generates tools from methods, so each toolkit is just a class with well-typed async methods — no separate tool class boilerplate.

The tradeoff vs Option A is effort, but the payoff is a maintainable architecture where adding a new database type is one file, not six.

The tradeoff vs Option C is that we're not getting plugin extensibility, but we don't need it — the 5 database types are all first-party and will live in the same package.

---

## Feature Description

### User-Facing Behavior

A developer creates a `DatabaseAgent` by explicitly instantiating one or more database toolkits and passing them to the agent:

```python
# Single database
pg_toolkit = PostgresToolkit(
    dsn="postgresql://user:pass@host/db",
    allowed_schemas=["public", "sales"],
    backend="asyncdb"  # or "sqlalchemy"
)
agent = DatabaseAgent(
    name="SalesDB",
    toolkits=[pg_toolkit],
    default_user_role=UserRole.DATA_ANALYST,  # fallback when not specified per-request
    vector_store=my_pgvector_store
)
await agent.configure()

# Per-request role override
response = await agent.ask("Show me top 10 customers by revenue", user_role=UserRole.BUSINESS_USER)

# No role specified — router infers from intent
response = await agent.ask("How can I optimize this query: SELECT * FROM orders WHERE...")
# Router detects optimization intent → infers DATABASE_ADMIN role

# Multi-database
bq_toolkit = BigQueryToolkit(
    project_id="my-project",
    dataset="analytics",
    credentials_file="/path/to/creds.json"
)
agent = DatabaseAgent(
    name="MultiDB",
    toolkits=[pg_toolkit, bq_toolkit],
    default_user_role=UserRole.DATABASE_ADMIN  # fallback default
)
await agent.configure()
# Explicit database + explicit role
response = await agent.ask("EXPLAIN ANALYZE SELECT * FROM orders", database="sales_pg", user_role=UserRole.QUERY_DEVELOPER)
# LLM-inferred database, router-inferred role
response = await agent.ask("What are the BigQuery costs for last month?")
```

**Role resolution order** (per-request):
1. Explicit `user_role=` parameter in `ask()` — highest priority
2. Router-inferred role from query intent (e.g., optimization keywords → `DATABASE_ADMIN`, "show me data" → `BUSINESS_USER`)
3. Agent's `default_user_role` — fallback

The agent responds according to the resolved role:
- `BUSINESS_USER` gets data results only
- `DATA_ANALYST` gets SQL + data + explanations + schema context
- `DATABASE_ADMIN` gets SQL + execution plans + performance metrics + optimization tips
- etc.

### Internal Behavior

1. **Agent receives query** via `ask()` method
2. **Role resolution**: explicit `user_role` param → router-inferred from intent → `default_user_role` fallback
3. **Router determines intent + role** (`SchemaQueryRouter.route()`) → `RouteDecision` (now includes role inference when no explicit role is provided)
4. **Database selection** (hybrid):
   - If `database=` is provided, use that toolkit directly
   - Otherwise, LLM sees all registered toolkit tools and picks the right one based on system prompt context
5. **Schema context building**:
   - CacheManager checks hot cache (LRU) → schema cache → vector store → on-fly extraction
   - Relevant table metadata is formatted as YAML context for the LLM prompt
6. **LLM generates response** using toolkit tools:
   - `search_schema(query)` — find relevant tables
   - `generate_query(natural_language, tables)` — create database-specific query
   - `execute_query(query, limit, timeout)` — run query and return results
   - `explain_query(query)` — get execution plan (database-specific syntax)
   - `validate_query(sql)` — validate user-provided SQL
7. **Response formatting** via `DatabaseResponse` with role-appropriate `OutputComponent` flags (using the resolved role from step 2)
8. **Error recovery** via `QueryRetryConfig`/`SQLRetryHandler` — if query fails with retryable error, agent gets sample data from problematic column and retries with enriched context

### Edge Cases & Error Handling

- **Table not in cache**: Toolkit extracts metadata on-the-fly from database, stores in cache
- **Query fails**: `SQLRetryHandler` checks if error is retryable, fetches sample data for context, retries up to `max_retries`
- **Database unreachable**: Toolkit raises connection error; agent reports to user without crashing
- **Multi-database ambiguity**: If LLM can't determine which database to use, system prompt instructs it to ask the user
- **Schema not in allowed list**: Security validation rejects queries targeting schemas outside `allowed_schemas`
- **Cache growth**: Each CacheManager partition has independent `maxsize` and TTL; LRU eviction handles growth naturally within each partition
- **Backend mismatch**: If `backend="sqlalchemy"` is specified for a database not supported by SQLAlchemy (e.g., InfluxDB), raise configuration error at init time

---

## Capabilities

### New Capabilities
- `database-toolkit-base`: Abstract `DatabaseToolkit` base class inheriting from `AbstractToolkit`
- `sql-toolkit`: `SQLToolkit(DatabaseToolkit)` with common SQL operations
- `postgres-toolkit`: `PostgresToolkit(SQLToolkit)` with PostgreSQL-specific overrides
- `bigquery-toolkit`: `BigQueryToolkit(SQLToolkit)` with BigQuery-specific overrides
- `influxdb-toolkit`: `InfluxDBToolkit(DatabaseToolkit)` with Flux query support
- `elastic-toolkit`: `ElasticToolkit(DatabaseToolkit)` with Elasticsearch DSL support
- `documentdb-toolkit`: `DocumentDBToolkit(DatabaseToolkit)` with MongoDB query language support
- `cache-manager`: `CacheManager` with namespaced partitions per database toolkit
- `database-agent-unified`: Single `DatabaseAgent` supporting multiple toolkits with hybrid routing

### Modified Capabilities
- `schema-metadata-cache`: Extended with Redis tier + per-database namespacing
- `query-router`: Extended with database selection (hybrid: explicit + LLM-inferred) and role inference from query intent
- `query-retry`: Generalized for non-SQL databases (not just SQLAlchemy errors)

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/bots/database/abstract.py` | **rewrite** | Slim down to orchestration only; move DB logic to toolkits |
| `parrot/bots/database/cache.py` | **extends** | Wrap in CacheManager with partitions and Redis tier |
| `parrot/bots/database/router.py` | **extends** | Add database selection to RouteDecision |
| `parrot/bots/database/retries.py` | **extends** | Generalize for non-SQL databases |
| `parrot/bots/database/models.py` | **minor extends** | Add database identifier to RouteDecision |
| `parrot/bots/database/sql.py` | **rewrite** | Becomes thin wrapper creating agent + toolkit |
| `parrot/bots/db/` | **delete** | After unification is complete |
| `parrot_tools/database/pg.py` | **delete** | Absorbed into PostgresToolkit |
| `parrot_tools/database/bq.py` | **delete** | Absorbed into BigQueryToolkit |
| `parrot_tools/database/abstract.py` | **delete** | Absorbed into DatabaseToolkit base |
| `parrot/tools/toolkit.py` | **no change** | Used as base class |
| `parrot_tools/querytoolkit.py` | **no change** | Reference for asyncdb patterns |

---

## Code Context

### User-Provided Code
```python
# Source: user-provided (UserRole enum)
class UserRole(str, Enum):
    """Define user roles with specific output preferences."""
    BUSINESS_USER = "business_user"      # Data only, no limits, minimal explanation
    DATA_ANALYST = "data_analyst"        # Explanations, samples, schema context
    DATA_SCIENTIST = "data_scientist"    # Schema context + DataFrame conversion (no limits)
    DATABASE_ADMIN = "database_admin"    # SQL, execution plans, performance, optimization, sample data
    DEVELOPER = "developer"              # SQL/schema, explanations, examples, no data
    QUERY_DEVELOPER = "query_developer"  # SQL/schema, execution plans, performance, optimization, no data
```

### Verified Codebase References

#### Classes & Signatures
```python
# From parrot/tools/toolkit.py:140
class AbstractToolkit(ABC):
    input_class: Optional[Type[BaseModel]] = None  # line 168
    return_direct: bool = False  # line 169
    exclude_tools: tuple[str, ...] = ()  # line 177
    def __init__(self, **kwargs):  # line 179
    def get_tools(self) -> List[ToolkitTool]:  # line 216
    def get_tool(self, name: str) -> Optional[ToolkitTool]:  # line 308
    def _generate_tools(self):  # line 248 — auto-generates tools from async methods
    def _create_tool_from_method(self, method) -> ToolkitTool:  # line 335

# From parrot/bots/database/abstract.py:54
class AbstractDBAgent(AbstractBot, ABC):
    _default_temperature: float = 0.0  # line 56
    max_tokens: int = 8192  # line 57
    def __init__(self, name, dsn, allowed_schemas, primary_schema, vector_store, auto_analyze_schema, client_id, database_type, system_prompt_template, **kwargs):  # line 59
    async def configure(self, app=None) -> None:  # line 139
    async def connect_database(self) -> None:  # line 195 (approx)
    async def analyze_schema(self) -> None:  # line 238 (approx)
    async def ask(self, query, context, user_role, ...) -> AIMessage:  # line 454

# From parrot/bots/database/cache.py:11
class SchemaMetadataCache:
    def __init__(self, vector_store, lru_maxsize=500, lru_ttl=1800):  # line 14
    async def get_table_metadata(self, schema_name, table_name) -> Optional[TableMetadata]:  # line 44
    async def store_table_metadata(self, metadata: TableMetadata):  # line 80
    async def search_similar_tables(self, schema_names, query, limit=5) -> List[TableMetadata]:  # line 106
    def get_hot_tables(self, schema_names, limit=10) -> List[tuple]:  # line 240
    def get_schema_overview(self, schema_name) -> Optional[SchemaMetadata]:  # line 236

# From parrot/bots/database/router.py:15
class SchemaQueryRouter:
    def __init__(self, primary_schema, allowed_schemas):  # line 18
    async def route(self, query, user_role, output_components, intent_override) -> RouteDecision:  # line 93
    def _detect_intent(self, query) -> QueryIntent:  # line 140

# From parrot/bots/database/retries.py:6
class QueryRetryConfig:
    def __init__(self, max_retries=3, retry_on_errors=None, sample_data_on_error=True, max_sample_rows=3):  # line 9

# From parrot/bots/database/retries.py:31
class SQLRetryHandler:
    def __init__(self, agent, config=None):  # line 34
    def _is_retryable_error(self, error) -> bool:  # line 39
    async def _get_sample_data_for_error(self, schema_name, table_name, column_name) -> str:  # line 50

# From parrot/bots/database/models.py:15-82
class UserRole(str, Enum):  # line 15
class OutputComponent(Flag):  # line 24
class OutputFormat(str, Enum):  # line 45
class QueryIntent(str, Enum):  # line 72
class SchemaMetadata:  # line 84 (dataclass)
class TableMetadata:  # line 104 (dataclass)
class QueryExecutionRequest(BaseModel):  # line 170
class QueryExecutionResponse(BaseModel):  # line 180
class RouteDecision:  # line 241 (dataclass)
class DatabaseResponse:  # line 269 (dataclass)

# From parrot_tools/querytoolkit.py:89
class QueryToolkit(AbstractToolkit):
    def __init__(self, dsn, schema, credentials, driver='pg', program, agent_id, **kwargs):  # line 102
    def _get_driver(self) -> AsyncDB:  # line 146
    async def _fetch_one(self, query, output_format, structured_obj):  # line 207
    async def _get_dataset(self, query, output_format, structured_obj):  # line 258

# From parrot_tools/database/pg.py:10
class PgSchemaSearchTool(AbstractSchemaManagerTool):
    async def _execute(self, search_term, schema_name, table_name, search_type, limit) -> ToolResult:  # line 16
    async def _search_in_cache(self, ...) -> List[TableMetadata]:  # line 89
    async def _search_in_database(self, ...) -> List[TableMetadata]:  # line 114
    async def analyze_schema(self, schema_name) -> int:  # line 201
    async def analyze_table(self, session, schema_name, table_name, table_type, comment) -> TableMetadata:  # line 243
```

#### Verified Imports
```python
# These imports have been confirmed to work:
from parrot.tools.toolkit import AbstractToolkit  # parrot/tools/toolkit.py:140
from parrot.tools.manager import ToolManager  # parrot/tools/manager.py:192
from parrot.bots.abstract import AbstractBot  # parrot/bots/abstract.py
from parrot.bots.database.models import UserRole, OutputComponent, QueryIntent, RouteDecision, TableMetadata, SchemaMetadata, DatabaseResponse, QueryExecutionRequest, QueryExecutionResponse  # parrot/bots/database/models.py
from parrot.bots.database.models import get_default_components, components_from_string, INTENT_COMPONENT_MAPPING, ROLE_COMPONENT_DEFAULTS  # parrot/bots/database/models.py
from parrot.bots.database.cache import SchemaMetadataCache  # parrot/bots/database/cache.py:11
from parrot.bots.database.router import SchemaQueryRouter  # parrot/bots/database/router.py:15
from parrot.bots.database.retries import QueryRetryConfig, SQLRetryHandler  # parrot/bots/database/retries.py
from parrot.stores.abstract import AbstractStore  # parrot/stores/abstract.py
from parrot.models import AIMessage, CompletionUsage  # parrot/models.py
from parrot.memory import ConversationTurn  # parrot/memory/__init__.py
from asyncdb import AsyncDB  # external
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine  # external
from cachetools import TTLCache  # external
```

#### Key Attributes & Constants
- `AbstractToolkit.exclude_tools` -> `tuple[str, ...]` (parrot/tools/toolkit.py:177) — methods to exclude from tool generation
- `ROLE_COMPONENT_DEFAULTS` -> `Dict[UserRole, OutputComponent]` (parrot/bots/database/models.py:197)
- `INTENT_COMPONENT_MAPPING` -> `Dict[QueryIntent, OutputComponent]` (parrot/bots/database/models.py:459)
- `SchemaMetadataCache.hot_cache` -> `TTLCache` (parrot/bots/database/cache.py:21)
- `SchemaMetadataCache.schema_cache` -> `Dict[str, SchemaMetadata]` (parrot/bots/database/cache.py:28)

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.bots.database.DatabaseToolkit`~~ — does not exist yet (to be created)
- ~~`parrot.bots.database.CacheManager`~~ — does not exist yet (to be created)
- ~~`parrot.bots.database.DatabaseAgent`~~ — the current class is `AbstractDBAgent`, not `DatabaseAgent`
- ~~`AbstractToolkit.register_with_agent()`~~ — no such method; toolkits don't know about agents
- ~~`AbstractDBAgent.add_toolkit()`~~ — no such method; current agent doesn't use toolkits
- ~~`SchemaMetadataCache.get_partition()`~~ — no partitioning support exists yet
- ~~`SchemaMetadataCache` Redis support~~ — current implementation is LRU + vector only, no Redis
- ~~`QueryRetryConfig` for non-SQL databases~~ — current implementation is SQL-specific (uses `sqlalchemy.text`)
- ~~`SchemaQueryRouter.select_database()`~~ — no multi-database routing exists; current router is schema-only
- ~~`parrot.bots.db.abstract.AbstractDBAgent` inherits from `AbstractBot`~~ — it inherits from `BaseBot` (different from `bots/database` which uses `AbstractBot`)

---

## Parallelism Assessment

**Internal parallelism**: High. The feature decomposes naturally into independent toolkit implementations:
- `DatabaseToolkit` base + `CacheManager` (foundational, must be first)
- `SQLToolkit` + `PostgresToolkit` (depends on base)
- `BigQueryToolkit`, `InfluxDBToolkit`, `ElasticToolkit`, `DocumentDBToolkit` (each independent after base exists)
- `DatabaseAgent` refactoring (depends on base toolkit + at least one concrete toolkit)
- Router extension for multi-database (depends on agent refactoring)

**Cross-feature independence**: No known conflicts with in-flight specs. The `parrot/bots/database/` directory is not touched by any current feature branches.

**Recommended isolation**: `per-spec` — tasks are sequential dependencies (base -> SQL -> concrete toolkits -> agent -> router). While individual toolkit implementations *could* parallelize, they all depend on the base classes and would need to merge cleanly.

**Rationale**: The inheritance chain (`DatabaseToolkit` -> `SQLToolkit` -> `PostgresToolkit`) creates serial dependencies for the core path. Non-SQL toolkits could theoretically run in parallel after the base is ready, but the shared `CacheManager` and `DatabaseAgent` changes make coordination easier in one worktree.

---

## Open Questions

- [ ] Should `QueryToolkit` in `parrot_tools/querytoolkit.py` be refactored or deprecated in favor of the new `DatabaseToolkit`? It serves a different purpose (pre-built queries via slugs) but has overlapping AsyncDB patterns. — *Owner: Jesus Lara*
- [ ] Should the `MultiDatabaseAgent` in `bots/db/multi.py` (keyword-based routing) be preserved as a fallback, or is the hybrid router (explicit + LLM-inferred) sufficient? — *Owner: Jesus Lara*
- [ ] What is the Redis URL/config source for the new CacheManager? Current `bots/db/cache.py` uses `querysource.conf.CACHE_URL`; `bots/database/cache.py` has no Redis at all. — *Owner: Jesus Lara*
- [ ] Should each toolkit expose a `health_check()` method for connection validation? — *Owner: Jesus Lara*
- [ ] For InfluxDB and Elasticsearch, the "query language" is Flux and Query DSL respectively — should `generate_query()` in those toolkits generate Flux/DSL from natural language, or delegate entirely to the LLM? — *Owner: Jesus Lara*
