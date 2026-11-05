# Database Agent

AI-Parrot's **Database Agent** is a conversational AI system that connects to databases, understands natural language questions, generates queries, executes them, and returns formatted results tailored to the user's role. It supports SQL, NoSQL, time-series, and search databases through a unified toolkit architecture.

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [User Roles](#user-roles)
- [Output Components and Formats](#output-components-and-formats)
- [Query Intents](#query-intents)
- [Types of Questions the Agent Can Answer](#types-of-questions-the-agent-can-answer)
- [Supported Database Drivers](#supported-database-drivers)
- [Database Toolkits (Bot Framework)](#database-toolkits-bot-framework)
- [Database Sources (Tool Framework)](#database-sources-tool-framework)
- [Caching System](#caching-system)
- [Query Routing](#query-routing)
- [Retry and Error Recovery](#retry-and-error-recovery)
- [Safety and Security](#safety-and-security)
- [REST API Helpers](#rest-api-helpers)
- [System Prompts](#system-prompts)
- [Usage Examples](#usage-examples)

---

## Architecture Overview

The Database Agent is composed of two complementary frameworks:

| Framework | Location | Purpose |
|-----------|----------|---------|
| **Bot Framework** | `parrot/bots/database/` | Conversational agent with multi-toolkit orchestration, caching, routing, and role-based output |
| **Tool Framework** | `parrot/tools/database/` | Standalone tools for agents using tool-calling (schema discovery, query validation, execution) |

### Class Hierarchy

```
AbstractBot
  └── DatabaseAgent              # Main conversational agent (agent.py)
        ├── CacheManager         # Three-tier cache (cache.py)
        ├── SchemaQueryRouter    # Intent detection & routing (router.py)
        └── DatabaseToolkit[]    # Per-database toolkit instances
              ├── SQLToolkit         # Common SQL with dialect hooks
              │   ├── PostgresToolkit
              │   └── BigQueryToolkit
              ├── InfluxDBToolkit    # Flux query language
              ├── ElasticToolkit     # Elasticsearch DSL
              └── DocumentDBToolkit  # MongoDB Query Language

AbstractToolkit
  └── DatabaseToolkit (tools)    # Tool-calling interface (toolkit.py)
        └── AbstractDatabaseSource[]
              ├── PostgresSource     ├── MySQLSource
              ├── SQLiteSource       ├── BigQuerySource
              ├── OracleSource       ├── ClickHouseSource
              ├── DuckDBSource       ├── MSSQLSource
              ├── MongoSource        ├── DocumentDBSource
              ├── AtlasSource        ├── InfluxSource
              └── ElasticSource
```

---

## User Roles

The agent tailors its output based on six predefined user roles. Each role determines which output components are included by default, data limits, and execution behavior.

### Role Definitions

| Role | Enum Value | Description | Default Output |
|------|------------|-------------|----------------|
| **Business User** | `business_user` | End users who need data results without technical details | Data results only |
| **Data Analyst** | `data_analyst` | Analysts who need SQL, data, documentation, and schema context | SQL + Data + Docs + Schema + Samples |
| **Data Scientist** | `data_scientist` | Scientists who work with DataFrames and need schema context | SQL + DataFrame + Schema + Docs |
| **Database Admin** | `database_admin` | DBAs focused on performance, execution plans, and optimization | SQL + EXPLAIN + Perf Metrics + Optimization |
| **Developer** | `developer` | Developers who need SQL/schema reference without actual data | SQL + Docs + Examples + Schema (no data) |
| **Query Developer** | `query_developer` | Query specialists focused on SQL performance tuning | SQL + EXPLAIN + Perf Metrics + Optimization + Schema (no data) |

### Role-Specific Behavior

| Role | Data Limit | Executes Queries | DataFrame | EXPLAIN ANALYZE | Timeout |
|------|-----------|-----------------|-----------|-----------------|---------|
| Business User | 100,000 rows | Yes (full data) | No | No | Default |
| Data Analyst | 5,000 rows | Yes | No | No | Default |
| Data Scientist | 10,000 rows | Yes | Yes (auto-convert) | No | Default |
| Database Admin | 100 rows | Yes (samples only) | No | Yes | 60s |
| Developer | N/A | No (by default) | No | No | Default |
| Query Developer | N/A | No (by default) | No | Yes | Default |

### Three-Tier Role Resolution

The agent resolves the user role through a priority chain:

1. **Explicit** — `user_role` parameter passed to `ask()` (highest priority)
2. **Inferred** — Detected from query intent patterns (e.g., "optimize this query" infers `database_admin`)
3. **Default** — Falls back to the agent's `default_user_role` (default: `data_analyst`)

---

## Output Components and Formats

### Output Components (Flag Enum)

Individual components can be combined using bitwise OR:

| Component | Description |
|-----------|-------------|
| `SQL_QUERY` | The generated or validated SQL query |
| `EXECUTION_PLAN` | EXPLAIN ANALYZE results |
| `DATA_RESULTS` | Actual query result rows |
| `DOCUMENTATION` | Table/schema metadata documentation |
| `EXAMPLES` | Usage examples for the schema |
| `PERFORMANCE_METRICS` | Query performance analysis |
| `SCHEMA_CONTEXT` | Available tables, columns, relationships |
| `OPTIMIZATION_TIPS` | Query optimization suggestions |
| `SAMPLE_DATA` | Sample rows from tables |
| `DATAFRAME_OUTPUT` | Results converted to pandas DataFrame |

### Convenience Combinations

| Preset | Components |
|--------|------------|
| `BASIC_QUERY` | SQL_QUERY + DATA_RESULTS |
| `FULL_ANALYSIS` | SQL_QUERY + EXECUTION_PLAN + PERFORMANCE_METRICS + OPTIMIZATION_TIPS |
| `DEVELOPER_FOCUS` | SQL_QUERY + DOCUMENTATION + EXAMPLES + SCHEMA_CONTEXT |
| `BUSINESS_FOCUS` | DATA_RESULTS |
| `QUERY_DEVELOPER_FOCUS` | SQL_QUERY + EXECUTION_PLAN + PERFORMANCE_METRICS + OPTIMIZATION_TIPS + SCHEMA_CONTEXT |

### Output Formats

| Format | Enum Value | Description |
|--------|------------|-------------|
| Query Only | `query_only` | Just the generated SQL |
| Data Only | `data_only` | Just the query results |
| Query and Data | `query_and_data` | SQL + result rows |
| Explanation Only | `explanation_only` | Natural language explanation |
| Documentation Only | `documentation_only` | Schema/table documentation |
| Query with Explanation | `query_with_explanation` | SQL + natural language walkthrough |
| Query with Docs | `query_with_docs` | SQL + schema documentation |
| Full Analysis | `full_analysis` | Complete analysis with all components |
| Developer Format | `developer_format` | SQL + docs + examples |
| DBA Format | `dba_format` | SQL + EXPLAIN + performance |
| Analyst Format | `analyst_format` | Balanced SQL + data + docs |
| Business Format | `business_format` | Data-focused, minimal technical |
| Explain Plan | `explain_plan` | EXPLAIN ANALYZE output |
| Performance Analysis | `performance_analysis` | Detailed performance breakdown |
| Query Optimization | `query_optimization` | Optimization recommendations |
| Full Response | `full_response` | Query + data + explanation |

### Response Object (`DatabaseResponse`)

Every response includes:

| Field | Type | Description |
|-------|------|-------------|
| `query` | `str` | Generated SQL/Flux/DSL query |
| `data` | `List[Dict] \| DataFrame` | Query result rows |
| `execution_plan` | `str` | EXPLAIN output |
| `documentation` | `str` | Schema documentation |
| `examples` | `List[str]` | Usage examples |
| `performance_metrics` | `Dict` | Timing, row counts |
| `schema_context` | `str` | Table/column info |
| `optimization_tips` | `List[str]` | Optimization suggestions |
| `sample_data` | `List[Dict]` | Sample rows |
| `row_count` | `int` | Number of result rows |
| `execution_time_ms` | `float` | Query execution time |

**Serialization methods:** `to_markdown()`, `to_json()`, `to_dict()`, `get_data_summary()`

---

## Query Intents

The router automatically detects query intent from natural language patterns:

| Intent | Trigger Patterns | Description |
|--------|-----------------|-------------|
| **Show Data** | "show me", "display", "list all", "get all", "select from" | Direct data retrieval |
| **Generate Query** | "find where", "calculate", "count", "sum" | SQL generation for computed results |
| **Analyze Data** | "analyze", "trends", "insights", "patterns", "statistics" | Analytical questions requiring aggregation |
| **Explore Schema** | "what tables", "list tables", "schema structure" | Schema discovery and navigation |
| **Validate Query** | "validate this SQL", "check my query" | SQL syntax and logic validation |
| **Optimize Query** | "optimize", "performance", "slow", "index", "explain analyze" | Query performance tuning |
| **Explain Metadata** | "describe table", "metadata of", "document table" | Table/column documentation |
| **Create Examples** | "examples", "how to use", "usage" | Generate usage examples |
| **Generate Report** | "generate report on" | Comprehensive reporting |

### Intent-to-Role Inference

When no explicit role is provided, the agent infers a suitable role from the detected intent:

| Intent | Inferred Role |
|--------|--------------|
| Show Data | Business User |
| Generate Query | Data Analyst |
| Analyze Data | Data Scientist |
| Explore Schema | Developer |
| Validate Query | Query Developer |
| Optimize Query | Database Admin |
| Explain Metadata | Developer |
| Create Examples | Developer |
| Generate Report | Data Analyst |

---

## Types of Questions the Agent Can Answer

### 1. Data Retrieval

Natural language queries that fetch and display data from database tables.

> "Show me the top 10 customers by revenue"
> "Get all active employees with their department names"
> "List products with price above $100 sorted by rating"

### 2. Analytical Questions

Questions requiring aggregation, grouping, and statistical operations.

> "What are the monthly sales trends for the last year?"
> "Compare average order values across regions"
> "Which product categories have the highest return rate?"

### 3. Schema Exploration

Questions about database structure, tables, columns, and relationships.

> "What tables are available in the public schema?"
> "Show me the columns and their types in the orders table"
> "What foreign key relationships exist between customers and orders?"

### 4. Metadata Documentation

Requests for detailed documentation about database objects.

> "Document the inventory table in markdown format"
> "Describe the columns in the users table with their constraints"
> "What indexes exist on the transactions table?"

### 5. Query Generation

Requests to build SQL queries without necessarily executing them.

> "Write a query to find duplicate email addresses"
> "Generate SQL to calculate running totals by month"
> "Create a query joining orders with customers and products"

### 6. Query Validation

Syntax and logic checking for user-provided queries.

> "Is this SQL valid? SELECT * FROM users WHERE active = 1"
> "Check if my query has any syntax errors"

### 7. Performance Analysis

Questions about query efficiency and optimization.

> "Why is this query slow? SELECT * FROM large_table WHERE unindexed_col = 'x'"
> "Show the execution plan for this join query"
> "What indexes should I add to improve performance?"

### 8. Query Optimization

Requests for improved versions of existing queries.

> "Optimize this query for better performance"
> "Suggest a more efficient way to write this subquery"
> "How can I reduce the execution time of this report query?"

### 9. Data Analysis with Business Context

Complex analytical questions requiring domain understanding.

> "Analyze customer churn patterns over the last quarter"
> "What are the key drivers of revenue growth?"
> "Identify anomalies in the transaction data from last month"

### 10. Troubleshooting

Help with database errors and unexpected behavior.

> "I'm getting 'column does not exist' — what's wrong with my query?"
> "Why does this query return empty results when I expect data?"

---

## Supported Database Drivers

### Complete Driver Matrix

| Database | Tool Source | Bot Toolkit | AsyncDB Driver | Query Language | Dialect (sqlglot) | Metadata Source |
|----------|-----------|-------------|----------------|----------------|-------------------|-----------------|
| **PostgreSQL** | `PostgresSource` | `PostgresToolkit` | `pg` | SQL | `postgres` | `information_schema` + `pg_class`/`pg_namespace` |
| **MySQL/MariaDB** | `MySQLSource` | — | `mysql` | SQL | `mysql` | `information_schema.COLUMNS` |
| **SQLite** | `SQLiteSource` | — | `sqlite` | SQL | `sqlite` | `PRAGMA table_info()` + `sqlite_master` |
| **Google BigQuery** | `BigQuerySource` | `BigQueryToolkit` | `bigquery` | SQL | `bigquery` | `{dataset}.INFORMATION_SCHEMA` |
| **Oracle** | `OracleSource` | — | `oracle` | SQL | `oracle` | `ALL_TAB_COLUMNS` + `ALL_CONS_COLUMNS` |
| **ClickHouse** | `ClickHouseSource` | — | `clickhouse` | SQL | `clickhouse` | `system.columns` |
| **DuckDB** | `DuckDBSource` | — | `duckdb` | SQL | `duckdb` | `information_schema.columns` |
| **MS SQL Server** | `MSSQLSource` | — | `mssql` | T-SQL | `tsql` | `INFORMATION_SCHEMA` + `sys.procedures` |
| **MongoDB** | `MongoSource` | `DocumentDBToolkit` | `mongo` | MQL (JSON) | N/A | `$sample` inference |
| **AWS DocumentDB** | `DocumentDBSource` | `DocumentDBToolkit` | `mongo` | MQL (JSON) | N/A | `$sample` inference (SSL enforced) |
| **MongoDB Atlas** | `AtlasSource` | — | `mongo` | MQL (JSON) | N/A | `$sample` inference (`mongodb+srv://`) |
| **InfluxDB** | `InfluxSource` | `InfluxDBToolkit` | `influx` | Flux | N/A | `buckets()` + `schema.fieldKeys()` |
| **Elasticsearch** | `ElasticSource` | `ElasticToolkit` | `elastic` | JSON DSL | N/A | `_mapping` API |

### Driver Aliases

The tool framework normalizes driver names through aliases:

| Alias | Resolves To |
|-------|-------------|
| `postgres`, `postgresql` | `pg` |
| `mariadb` | `mysql` |
| `bq` | `bigquery` |
| `sqlserver` | `mssql` |
| `influxdb` | `influx` |
| `mongodb` | `mongo` |
| `opensearch` | `elastic` |

---

## Database Toolkits (Bot Framework)

### Base Toolkit (`DatabaseToolkit`)

All bot-framework toolkits inherit from `DatabaseToolkit` (in `bots/database/toolkits/base.py`).

**Configuration:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `dsn` | `str` | required | Database connection string |
| `allowed_schemas` | `List[str]` | `["public"]` | Schemas the agent can access |
| `primary_schema` | `str` | first allowed | Default schema for queries |
| `backend` | `str` | `"asyncdb"` | Connection backend (`asyncdb` or `sqlalchemy`) |
| `database_type` | `str` | `"postgresql"` | Database type identifier |
| `cache_partition` | `CachePartition` | `None` | Cache for this toolkit |
| `retry_config` | `QueryRetryConfig` | default | Retry configuration |

**Lifecycle Methods:**

| Method | Description |
|--------|-------------|
| `async start()` | Connect to the database |
| `async stop()` | Close connections and dispose engines |
| `async health_check()` | Returns `True` if connection is healthy |
| `async cleanup()` | Alias for `stop()` |

### PostgresToolkit

PostgreSQL-specific toolkit with full introspection support.

**Features:**
- `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` for execution plans
- Column comments via `col_description()`
- Uses `pg_class`/`pg_namespace` for rich metadata
- DSN format: `postgresql+asyncpg://user:pass@host:5432/dbname`

### BigQueryToolkit

Google BigQuery analytics toolkit.

**Additional Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `project_id` | `str` | BigQuery project ID |
| `credentials_file` | `str` | Path to credentials JSON |

**Features:**
- Dry-run cost estimation instead of EXPLAIN ANALYZE
- Dataset-based `INFORMATION_SCHEMA` queries
- DSN format: `bigquery://project/dataset`

### InfluxDBToolkit

Time-series database toolkit using Flux query language.

**Additional Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `org` | `str` | `"default"` | InfluxDB organization |

**LLM Tools:**
- `search_measurements(search_term, bucket, limit)` — Search InfluxDB measurements
- `execute_flux_query(query, limit, timeout)` — Execute Flux queries

### ElasticToolkit

Elasticsearch/OpenSearch search engine toolkit.

**LLM Tools:**
- `search_indices(search_term, limit)` — Search Elasticsearch indices
- `execute_dsl(dsl_dict, limit, timeout)` — Execute Elasticsearch DSL queries

### DocumentDBToolkit

MongoDB and AWS DocumentDB document database toolkit.

**Additional Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `database_name` | `str` | `"default"` | Target database name |

**LLM Tools:**
- `search_collections(search_term, database, limit)` — Search MongoDB collections
- `execute_mql(query, limit, timeout)` — Execute MongoDB Query Language queries

---

## Database Sources (Tool Framework)

The tool framework (`parrot/tools/database/`) provides four LLM-callable tools:

| Tool | Purpose | Call Order |
|------|---------|------------|
| `get_database_metadata` | Schema discovery — tables, columns, types, keys | First |
| `validate_database_query` | Pre-execution syntax/logic validation | Second |
| `execute_database_query` | Multi-row query execution | Third |
| `fetch_database_row` | Single-row lookup | Alternative to execute |

### Tool Input Schemas

**Common base arguments:**
```python
driver: str           # Database driver name (e.g., "pg", "mysql")
credentials: dict     # Connection credentials (dsn, params, etc.)
```

**get_database_metadata** adds:
```python
tables: list[str]     # Optional filter — specific tables to inspect
```

**validate_database_query** adds:
```python
query: str            # SQL/Flux/DSL query to validate
```

**execute_database_query / fetch_database_row** add:
```python
query: str            # Query to execute
params: dict          # Parameterized query values
```

### Tool Output Models

**MetadataResult:**
```python
driver: str
tables: list[TableMeta]    # Each with name, schema, columns, row_count
raw: dict                  # Raw driver-specific metadata
```

**ValidationResult:**
```python
valid: bool
error: str | None
dialect: str | None         # "postgres", "mysql", "json", "flux", "json-dsl"
```

**QueryResult:**
```python
driver: str
rows: list[dict]
row_count: int
columns: list[str]
execution_time_ms: float
```

**RowResult:**
```python
driver: str
row: dict | None
found: bool
execution_time_ms: float
```

### Database-Specific Query Validation

| Database | Validation Method | Valid Format |
|----------|------------------|-------------|
| SQL databases | `sqlglot` parsing with dialect | Standard SQL for the dialect |
| MongoDB | JSON parsing + type check | JSON object (filter) or JSON array (pipeline) |
| InfluxDB | Pattern matching | Must contain `from(bucket:...)` |
| Elasticsearch | JSON parsing + key whitelist | JSON with `query`, `aggs`, `size`, `sort`, etc. |
| MSSQL | SQL + stored procedure detection | T-SQL or `EXEC/EXECUTE procedure` |

---

## Caching System

The agent uses a three-tier caching architecture partitioned by database:

### Cache Tiers

| Tier | Backend | TTL | Purpose |
|------|---------|-----|---------|
| **Tier 1** | In-memory LRU (`TTLCache`) | 30 min | Hot/frequently accessed tables |
| **Tier 2** | Redis (optional) | 60 min | Distributed persistence across instances |
| **Tier 3** | Vector Store (optional) | Persistent | Semantic similarity search for schema discovery |

### Cache Partition Configuration

```python
CachePartitionConfig(
    namespace="postgresql_public",   # Unique per-database partition
    lru_maxsize=500,                 # Max items in LRU cache
    lru_ttl=1800,                    # 30 minutes
    redis_ttl=3600,                  # 1 hour
)
```

### Cache Operations

| Method | Description |
|--------|-------------|
| `get_table_metadata(schema, table)` | Retrieve with access tracking (LRU -> Redis -> Vector) |
| `store_table_metadata(metadata)` | Store across all tiers |
| `search_similar_tables(schemas, query, limit)` | Semantic similarity search |
| `get_hot_tables(schemas, limit)` | Most frequently accessed tables |
| `get_schema_overview(schema)` | Complete schema metadata |
| `search_across_databases(query, limit)` | Cross-partition search |

---

## Query Routing

The `SchemaQueryRouter` analyzes natural language queries and produces a `RouteDecision`:

```python
RouteDecision(
    intent=QueryIntent.GENERATE_QUERY,
    components=OutputComponent.SQL_QUERY | OutputComponent.DATA_RESULTS,
    user_role=UserRole.DATA_ANALYST,
    primary_schema="public",
    allowed_schemas=["public", "analytics"],
    needs_metadata_discovery=True,
    needs_query_generation=True,
    needs_execution=True,
    needs_plan_analysis=False,
    data_limit=5000,
    target_database="postgresql_main",
    role_source="inferred",
    confidence=0.8,
)
```

The router also detects which database to target when multiple toolkits are registered, matching registered database identifiers against query text.

---

## Retry and Error Recovery

### Retry Configuration

```python
QueryRetryConfig(
    max_retries=3,
    retry_on_errors=[
        "InvalidTextRepresentationError",
        "DataError", "ProgrammingError",
        "invalid input syntax",
        "column does not exist",
        "relation does not exist",
        "type", "cast", "convert"
    ],
    sample_data_on_error=True,
    max_sample_rows=3,
    database_type="sql",
)
```

### SQL Retry Handler

When a query fails with a retryable error:

1. **Error Extraction** — Parses the table/column name from the SQL and error message
2. **Sample Data Fetch** — Retrieves sample values from the problematic column (with SQL injection guards)
3. **Context Enrichment** — Provides the LLM with sample data so it can correct type mismatches and column references
4. **Re-generation** — The LLM generates a corrected query with the new context

Specialized retry handlers exist for Flux (InfluxDB) and DSL (Elasticsearch) as extensible stubs.

---

## Safety and Security

### SQL Injection Prevention

1. **Identifier validation** — All schema, table, and column names are validated against `^[a-zA-Z_][a-zA-Z0-9_]*$` before interpolation
2. **Parameterized queries** — All user-provided values are passed as parameters, never interpolated into SQL strings
3. **BigQuery resource validation** — Allows letters, digits, underscores, hyphens, and dots
4. **NoSQL format enforcement** — MongoDB queries must be valid JSON; Elasticsearch queries are validated against a key whitelist

### Access Control

- Schemas are restricted via `allowed_schemas` — the agent cannot access schemas outside this list
- Role-based data limits prevent accidental large data exports
- Developer and Query Developer roles do not execute queries by default
- All REST API endpoints require authentication (`@is_authenticated`, `@user_session`)

### Connection Security

- AWS DocumentDB forces SSL/TLS by default
- MongoDB Atlas enforces `mongodb+srv://` URI scheme
- Connection pooling via AsyncDB prevents credential leaks
- Credentials resolved from environment variables, never hardcoded

---

## REST API Helpers

The `parrot/handlers/database/helpers.py` module exposes REST endpoints for frontend interaction with the Database Agent.

### Endpoints

| Endpoint | Handler Class | Method | Description |
|----------|--------------|--------|-------------|
| `GET /api/v1/agents/database/roles` | `DatabaseRolesHandler` | GET | List available user roles |
| `GET /api/v1/agents/database/formats` | `DatabaseFormatsHandler` | GET | List output format options |
| `GET /api/v1/agents/database/intents` | `DatabaseIntentsHandler` | GET | List query intent options |
| `GET /api/v1/agents/database/drivers` | `DatabaseDriversHandler` | GET | List supported database drivers |
| `GET /api/v1/agents/database/schemas` | `DatabaseSchemasHandler` | GET | List all cached schema metadata |
| `GET /api/v1/agents/database/schemas/{name}` | `DatabaseSchemasHandler` | GET | Detail for a single cached schema |

All endpoints require authentication.

### Helper Functions

#### `_enum_to_list(enum_cls) -> List[Dict[str, str]]`

Serializes a string enum into a list of `{value, label}` dictionaries. Converts member names from `SNAKE_CASE` to `Title Case`.

**Example output:**
```json
[
    {"value": "data_analyst", "label": "Data Analyst"},
    {"value": "business_user", "label": "Business User"}
]
```

#### `_get_database_agent(request, agent_id=None) -> Optional[DatabaseAgent]`

Looks up a `DatabaseAgent` from the application's bot manager.

| Parameter | Type | Description |
|-----------|------|-------------|
| `request` | `web.Request` | The incoming aiohttp request |
| `agent_id` | `str \| None` | Optional agent identifier; returns first `DatabaseAgent` if `None` |

**Resolution logic:**
1. If `agent_id` provided, gets the bot by ID and checks it's a `DatabaseAgent`
2. Otherwise, returns the first registered `DatabaseAgent` from the bot manager
3. Returns `None` if no bot manager or no matching agent

### SUPPORTED_DRIVERS Constant

A static list of supported database drivers exposed via the `/drivers` endpoint:

```python
SUPPORTED_DRIVERS = [
    {"name": "postgresql",     "label": "PostgreSQL",       "toolkit": "PostgresToolkit"},
    {"name": "bigquery",       "label": "Google BigQuery",  "toolkit": "BigQueryToolkit"},
    {"name": "influxdb",       "label": "InfluxDB",         "toolkit": "InfluxDBToolkit"},
    {"name": "elasticsearch",  "label": "Elasticsearch",    "toolkit": "ElasticToolkit"},
    {"name": "documentdb",     "label": "AWS DocumentDB",   "toolkit": "DocumentDBToolkit"},
    {"name": "mongodb",        "label": "MongoDB",          "toolkit": "DocumentDBToolkit"},
    {"name": "sql",            "label": "Generic SQL",      "toolkit": "SQLToolkit"},
]
```

### Schema Endpoint Response Format

**List view** (`GET /schemas`):
```json
{
    "schemas": [
        {
            "database_name": "navigator",
            "schema": "public",
            "database_type": "postgresql",
            "table_count": 42,
            "view_count": 5,
            "total_rows": 1000000,
            "partition": "postgresql_public",
            "tables": ["users", "orders", "products"],
            "views": ["active_users", "monthly_sales"]
        }
    ]
}
```

**Detail view** (`GET /schemas/{name}`):
Returns a single schema object (same structure as above) or `404` if not found.

---

## System Prompts

The agent uses context-aware prompt templates defined in `prompts.py`:

| Prompt | Template Variables | Purpose |
|--------|-------------------|---------|
| `DB_AGENT_PROMPT` | `$role`, `$backstory`, `$user_context`, `$database_context`, `$context`, `$vector_context`, `$chat_history`, `$database_type` | Main system prompt for conversational queries |
| `BASIC_HUMAN_PROMPT` | `$question`, `$session_id` | User message wrapper |
| `DATA_ANALYSIS_PROMPT` | `$analysis_request`, `$business_question`, `$data_sources`, `$user_context` | Deep analysis framework (Understanding, Approach, Insights, Recommendations) |
| `DATABASE_EDUCATION_PROMPT` | `$concept`, `$user_level`, `$focus_area` | Educational explanations (Overview, Examples, Best Practices, Advanced) |
| `DATABASE_TROUBLESHOOTING_PROMPT` | `$problem_description`, `$error_message`, `$attempted_query`, `$expected_outcome`, `$user_context` | Error diagnosis (Analysis, Schema Validation, Query Review, Solutions) |

### Critical Instructions (enforced in all prompts)

1. Never hallucinate schema or data — if unknown, say so
2. Prioritize user safety and data integrity
3. Follow data privacy best practices
4. Try multiple approaches before giving up
5. Every factual statement must be traceable to input data
6. Generate database-specific SQL compatible with the target engine
7. Consider performance implications of large datasets

---

## Usage Examples

### Basic: PostgreSQL with Data Analyst Role

```python
import asyncio
from parrot.bots.database import DatabaseAgent
from parrot.bots.database.models import UserRole
from parrot.bots.database.toolkits.postgres import PostgresToolkit

async def main():
    toolkit = PostgresToolkit(
        dsn="postgresql+asyncpg://user:pass@localhost:5432/mydb",
        allowed_schemas=["public", "analytics"],
        primary_schema="public",
    )

    agent = DatabaseAgent(
        name="MyDatabaseAgent",
        toolkits=[toolkit],
        default_user_role=UserRole.DATA_ANALYST,
    )
    await agent.configure()

    async with agent:
        response = await agent.ask(
            query="Get top 10 products by sales revenue",
            user_role=UserRole.DATA_ANALYST,
        )
        print(response.content)

asyncio.run(main())
```

### Business User: Simple Data Retrieval

```python
response = await agent.ask(
    query="Show me all active employees with their department",
    user_role=UserRole.BUSINESS_USER,
)
# Returns: data results only, up to 100k rows
```

### DBA: Performance Analysis

```python
response = await agent.ask(
    query="Why is the orders join query slow? Analyze the execution plan",
    user_role=UserRole.DATABASE_ADMIN,
)
# Returns: SQL + EXPLAIN ANALYZE + performance metrics + optimization tips
```

### Data Scientist: DataFrame Output

```python
response = await agent.ask(
    query="Get monthly sales trends for the last 12 months",
    user_role=UserRole.DATA_SCIENTIST,
)
# Returns: SQL + auto-converted pandas DataFrame + schema context
```

### Developer: Schema Reference (No Data)

```python
response = await agent.ask(
    query="Document the inventory table with all columns and relationships",
    user_role=UserRole.DEVELOPER,
)
# Returns: SQL examples + documentation + schema context (no actual data)
```

### Multi-Database: PostgreSQL + BigQuery

```python
pg_toolkit = PostgresToolkit(
    dsn="postgresql+asyncpg://user:pass@pg-host/app_db",
    allowed_schemas=["public"],
)

bq_toolkit = BigQueryToolkit(
    project_id="my-gcp-project",
    credentials_file="/path/to/creds.json",
    allowed_schemas=["analytics"],
)

agent = DatabaseAgent(
    name="MultiDBAgent",
    toolkits=[pg_toolkit, bq_toolkit],
    default_user_role=UserRole.DATA_ANALYST,
    redis_url="redis://localhost:6379",  # shared cache
)
await agent.configure()

# The router auto-detects which database to query
response = await agent.ask("Show analytics dashboard data")  # routes to BigQuery
response = await agent.ask("Get user profiles from public.users")  # routes to PostgreSQL
```

### InfluxDB: Time-Series Queries

```python
from parrot.bots.database.toolkits.influx import InfluxDBToolkit

influx_toolkit = InfluxDBToolkit(
    dsn="http://localhost:8086",
    org="my-org",
    allowed_schemas=["monitoring"],
)

agent = DatabaseAgent(
    name="MetricsAgent",
    toolkits=[influx_toolkit],
)
await agent.configure()

response = await agent.ask("Show CPU usage trends for the last 24 hours")
# Generates and executes Flux query:
# from(bucket:"monitoring")
#   |> range(start: -24h)
#   |> filter(fn: (r) => r._measurement == "cpu")
```

### Elasticsearch: Search Queries

```python
from parrot.bots.database.toolkits.elastic import ElasticToolkit

elastic_toolkit = ElasticToolkit(
    dsn="http://localhost:9200",
    allowed_schemas=["logs"],
)

agent = DatabaseAgent(
    name="SearchAgent",
    toolkits=[elastic_toolkit],
)
await agent.configure()

response = await agent.ask("Find all error logs from the last hour with status 500")
# Generates and executes Elasticsearch DSL query
```

### MongoDB: Document Queries

```python
from parrot.bots.database.toolkits.documentdb import DocumentDBToolkit

mongo_toolkit = DocumentDBToolkit(
    dsn="mongodb://localhost:27017",
    database_name="my_app",
    allowed_schemas=["my_app"],
)

agent = DatabaseAgent(
    name="DocAgent",
    toolkits=[mongo_toolkit],
)
await agent.configure()

response = await agent.ask("Find users who signed up in the last 30 days with premium status")
# Generates MongoDB Query Language (MQL) filter or aggregation pipeline
```

### Tool Framework: Direct Tool Usage

```python
from parrot.tools.database import DatabaseToolkit

toolkit = DatabaseToolkit()

# Step 1: Discover schema
metadata_tool = toolkit.get_tool_by_name("get_database_metadata")
result = await metadata_tool.execute(
    driver="pg",
    credentials={"dsn": "postgresql://user:pass@localhost/db"},
    tables=["users", "orders"],
)

# Step 2: Validate a query
validate_tool = toolkit.get_tool_by_name("validate_database_query")
result = await validate_tool.execute(
    driver="pg",
    query="SELECT u.name, COUNT(o.id) FROM users u JOIN orders o ON u.id = o.user_id GROUP BY u.name",
)

# Step 3: Execute
execute_tool = toolkit.get_tool_by_name("execute_database_query")
result = await execute_tool.execute(
    driver="pg",
    credentials={"dsn": "postgresql://user:pass@localhost/db"},
    query="SELECT u.name, COUNT(o.id) as order_count FROM users u JOIN orders o ON u.id = o.user_id GROUP BY u.name ORDER BY order_count DESC LIMIT 10",
)
```

### MySQL Example

```python
# Using the tool framework (MySQL has no bot-framework toolkit yet)
result = await metadata_tool.execute(
    driver="mysql",
    credentials={"dsn": "mysql://user:pass@localhost:3306/mydb"},
)

result = await execute_tool.execute(
    driver="mysql",
    credentials={"dsn": "mysql://user:pass@localhost:3306/mydb"},
    query="SELECT * FROM products WHERE category = %s",
    params={"category": "electronics"},
)
```

### SQLite Example

```python
result = await execute_tool.execute(
    driver="sqlite",
    credentials={"database": "/path/to/local.db"},
    query="SELECT name, price FROM products ORDER BY price DESC LIMIT 5",
)
```

### Oracle Example

```python
result = await metadata_tool.execute(
    driver="oracle",
    credentials={"dsn": "oracle://user:pass@host:1521/orcl"},
    tables=["EMPLOYEES"],
)

result = await execute_tool.execute(
    driver="oracle",
    credentials={"dsn": "oracle://user:pass@host:1521/orcl"},
    query="SELECT * FROM EMPLOYEES WHERE DEPARTMENT_ID = :dept",
    params={"dept": 10},
)
```

### ClickHouse Example

```python
result = await execute_tool.execute(
    driver="clickhouse",
    credentials={"dsn": "clickhouse://user:pass@host:8123/analytics"},
    query="SELECT toDate(event_time) as day, count() FROM events GROUP BY day ORDER BY day",
)
```

### DuckDB Example

```python
result = await execute_tool.execute(
    driver="duckdb",
    credentials={"database": "/path/to/analytics.duckdb"},
    query="SELECT region, SUM(revenue) as total FROM sales GROUP BY region",
)
```

### MS SQL Server Example

```python
# Supports both T-SQL queries and stored procedures
result = await execute_tool.execute(
    driver="mssql",
    credentials={"dsn": "mssql://user:pass@host:1433/mydb"},
    query="EXEC sp_GetTopCustomers @TopN = 10",
)

# Metadata includes stored procedures from sys.procedures
result = await metadata_tool.execute(
    driver="mssql",
    credentials={"dsn": "mssql://user:pass@host:1433/mydb"},
)
```

### AWS DocumentDB Example

```python
# SSL is enforced by default
result = await execute_tool.execute(
    driver="documentdb",
    credentials={
        "dsn": "mongodb://user:pass@docdb-cluster.region.docdb.amazonaws.com:27017",
        "database": "my_database",
    },
    query='{"status": "active", "created_at": {"$gte": "2024-01-01"}}',
)
```

### MongoDB Atlas Example

```python
# Enforces mongodb+srv:// URI scheme
result = await execute_tool.execute(
    driver="atlas",
    credentials={
        "dsn": "mongodb+srv://user:pass@cluster.mongodb.net",
        "database": "my_app",
    },
    query='[{"$match": {"status": "active"}}, {"$group": {"_id": "$category", "count": {"$sum": 1}}}]',
)
```

### Custom Output Components

```python
from parrot.bots.database.models import OutputComponent

# Explicitly request specific components
response = await agent.ask(
    query="Show me the orders table structure",
    output_components=OutputComponent.SCHEMA_CONTEXT | OutputComponent.DOCUMENTATION | OutputComponent.EXAMPLES,
)

# Or use string shorthand
response = await agent.ask(
    query="Get customer data",
    output_components="sql,data",
)
```

### With Redis Cache and Vector Store

```python
from parrot.stores.faiss_store import FaissStore

vector_store = FaissStore(
    embedding_model="sentence-transformers/all-mpnet-base-v2",
)

agent = DatabaseAgent(
    name="CachedAgent",
    toolkits=[pg_toolkit],
    redis_url="redis://localhost:6379",
    vector_store=vector_store,
)
await agent.configure()

# First query: discovers schema, caches in all 3 tiers
response = await agent.ask("Show me the users table")

# Subsequent queries: served from cache, with semantic similarity for schema discovery
response = await agent.ask("Find employee records")  # hits vector store for "users" similarity
```
