# Feature Specification: DatasetManager New Sources (Iceberg, MongoDB, DeltaTable)

**Feature ID**: FEAT-060
**Date**: 2026-03-24
**Author**: Jesus Lara
**Status**: approved
**Target version**: 1.x.x
**Depends on**: FEAT-030 (DatasetManager Lazy Data Sources — approved)

---

## 1. Motivation & Business Requirements

### Problem Statement

`DatasetManager` currently supports six source types (InMemory, QuerySlug, SQL, Table, Airtable, Smartsheet), but lacks support for modern lakehouse and document-oriented data sources. Teams working with Apache Iceberg catalogs, Delta Lake tables, or MongoDB/DocumentDB collections must export data manually before registering it — losing the lazy-materialization and schema-prefetch benefits that `TableSource` provides for SQL databases.

All three new sources have mature asyncdb drivers (`asyncdb.drivers.iceberg`, `asyncdb.drivers.delta`, `asyncdb.drivers.mongo`) that follow the same connection/query patterns, making integration straightforward.

### Goals

- Add **`IcebergSource`**: query Apache Iceberg tables via asyncdb's iceberg driver, with schema prefetch and the ability to create new Iceberg tables from existing DataFrames (register-as-dataset workflow).
- Add **`MongoSource`**: read-only, filter-required queries against MongoDB/DocumentDB collections via asyncdb's mongo driver. No full-collection scans allowed.
- Add **`DeltaTableSource`**: query Delta Lake tables (local, S3, or GCS paths) via asyncdb's delta driver, with optional creation from Parquet files.
- Expose registration methods: `add_iceberg_source()`, `add_mongo_source()`, `add_deltatable_source()` on `DatasetManager`.
- Follow the existing `DataSource` ABC pattern (prefetch_schema, fetch, describe, cache_key).

### Non-Goals (explicitly out of scope)

- Write-back to MongoDB (read-only reference source)
- Full Iceberg catalog management (namespace CRUD is only for the create-from-DataFrame workflow)
- Streaming/incremental ingestion from any of these sources
- Delta Lake time-travel queries (future extension)
- Schema evolution or DDL operations

---

## 2. Architectural Design

### Overview

Three new `DataSource` subclasses are added to `parrot/tools/dataset_manager/sources/`, each wrapping its asyncdb driver. `DatasetManager` gains three new registration methods. The existing lifecycle (register → prefetch schema → lazy materialize → cache → evict) applies unchanged.

### Component Diagram

```
DatasetManager
  │
  ├── add_iceberg_source()     → IcebergSource
  ├── add_mongo_source()       → MongoSource
  ├── add_deltatable_source()  → DeltaTableSource
  │
  └── (existing)
      ├── add_table_source()   → TableSource
      ├── add_sql_source()     → SQLQuerySource
      ├── add_query()          → QuerySlugSource
      ├── add_dataframe()      → InMemorySource
      ├── add_airtable_source()→ AirtableSource
      └── add_smartsheet_source() → SmartsheetSource

All ──→ DataSource ABC ──→ DatasetEntry ──→ materialize/evict/cache
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `DataSource` ABC | extends | Three new subclasses |
| `DatasetManager` (tool.py) | extends | Three new `add_*` registration methods |
| `DatasetInfo` | extends | Add `iceberg`, `mongo`, `deltatable` to `source_type` literal |
| `sources/__init__.py` | extends | Export new sources |
| `asyncdb.drivers.iceberg` | uses | Iceberg driver for queries and table creation |
| `asyncdb.drivers.delta` | uses | Delta Lake driver for queries and table creation |
| `asyncdb.drivers.mongo` | uses | MongoDB driver for filtered queries |
| `_resolve_credentials` (table.py) | reuses | Credential resolution for MongoDB connections |
| Redis caching | uses | Same Parquet-based cache flow as existing sources |

### Data Models

```python
# IcebergSource configuration
class IcebergSource(DataSource):
    def __init__(
        self,
        table_id: str,              # e.g. "demo.cities"
        name: str,
        catalog_params: Dict[str, Any],  # asyncdb connection params (uri, warehouse, etc.)
        factory: str = "pandas",
        credentials: Optional[Dict] = None,
        dsn: Optional[str] = None,
    ): ...

# MongoSource configuration
class MongoSource(DataSource):
    def __init__(
        self,
        collection: str,            # e.g. "orders"
        name: str,
        database: str,              # e.g. "mydb"
        credentials: Optional[Dict] = None,
        dsn: Optional[str] = None,
        required_filter: bool = True,  # enforce filter on every fetch
    ): ...

# DeltaTableSource configuration
class DeltaTableSource(DataSource):
    def __init__(
        self,
        path: str,                  # local path, s3://, or gs://
        name: str,
        table_name: Optional[str] = None,  # alias for SQL queries
        mode: str = "error",        # overwrite, append, error, ignore
        credentials: Optional[Dict] = None,
    ): ...
```

### New Public Interfaces

```python
class DatasetManager:
    # --- Iceberg ---
    async def add_iceberg_source(
        self,
        name: str,
        table_id: str,
        *,
        catalog_params: Optional[Dict[str, Any]] = None,
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        cache_ttl: int = 3600,
        factory: str = "pandas",
        is_active: bool = True,
    ) -> str: ...

    async def create_iceberg_from_dataframe(
        self,
        name: str,
        df: pd.DataFrame,
        table_id: str,
        *,
        namespace: str = "default",
        catalog_params: Optional[Dict[str, Any]] = None,
        description: Optional[str] = None,
        mode: str = "overwrite",
    ) -> str:
        """Write a DataFrame to a new Iceberg table and register it as a dataset."""
        ...

    # --- MongoDB ---
    async def add_mongo_source(
        self,
        name: str,
        collection: str,
        database: str,
        *,
        dsn: Optional[str] = None,
        credentials: Optional[Dict[str, Any]] = None,
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        cache_ttl: int = 3600,
        is_active: bool = True,
    ) -> str: ...

    # --- DeltaTable ---
    async def add_deltatable_source(
        self,
        name: str,
        path: str,
        *,
        table_name: Optional[str] = None,
        mode: str = "error",
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        cache_ttl: int = 3600,
        is_active: bool = True,
    ) -> str: ...

    async def create_deltatable_from_parquet(
        self,
        name: str,
        parquet_path: str,
        delta_path: str,
        *,
        table_name: Optional[str] = None,
        mode: str = "overwrite",
        description: Optional[str] = None,
    ) -> str:
        """Create a Delta table from a Parquet file and register it as a dataset."""
        ...
```

---

## 3. Module Breakdown

### Module 1: `IcebergSource`
- **Path**: `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/iceberg.py`
- **Responsibility**: `DataSource` subclass wrapping `asyncdb.drivers.iceberg`. Implements:
  - `prefetch_schema()`: calls `driver.load_table(table_id)` then `driver.schema()` to get column names/types without fetching rows.
  - `fetch(**params)`: supports `sql` param (DuckDB SQL via `driver.query()`), `table_id` param (full table via `driver.to_df()`), and filter-based queries via `driver.queryrow()`.
  - `describe()`: returns source description with table_id and catalog info.
  - `cache_key`: `iceberg:{table_id}`
  - Static helper `create_table_from_df()`: creates namespace if needed, defines PyArrow schema from DataFrame, calls `driver.create_table()` + `driver.write()`.
- **Depends on**: `DataSource` ABC, `asyncdb.drivers.iceberg`

### Module 2: `MongoSource`
- **Path**: `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/mongo.py`
- **Responsibility**: `DataSource` subclass wrapping `asyncdb.drivers.mongo`. Implements:
  - `prefetch_schema()`: runs a `find_one()` (single document) to infer field names and types.
  - `fetch(**params)`: **requires** a `filter` dict parameter. Raises `ValueError` if no filter provided (prevents full collection scans). Calls `driver.query()` with the filter and converts results to DataFrame.
  - `describe()`: returns source description with collection name and database.
  - `cache_key`: `mongo:{database}:{collection}`
  - Enforces `required_filter=True` by default.
- **Depends on**: `DataSource` ABC, `asyncdb.drivers.mongo`

### Module 3: `DeltaTableSource`
- **Path**: `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/deltatable.py`
- **Responsibility**: `DataSource` subclass wrapping `asyncdb.drivers.delta`. Implements:
  - `prefetch_schema()`: opens connection, calls `conn.schema()` to get column names/types.
  - `fetch(**params)`: supports `sql` param (DuckDB SQL via `conn.query(sentence=sql, tablename=table_name)`), `columns` param (selective column fetch via `conn.to_df(columns=...)`), and filter expressions via `conn.query(sentence=filter_expr)`.
  - `describe()`: returns source description with path and table name.
  - `cache_key`: `delta:{md5(path)[:12]}`
  - Static helper `create_from_parquet()`: calls `driver.create(delta_path, parquet_path, name=table_name, mode=mode)`.
  - Supports local paths, S3 (`s3://`), and GCS (`gs://`) via asyncdb's built-in support.
- **Depends on**: `DataSource` ABC, `asyncdb.drivers.delta`

### Module 4: DatasetManager registration methods + DatasetInfo update
- **Path**: `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py`
- **Responsibility**:
  - Add `add_iceberg_source()`, `add_mongo_source()`, `add_deltatable_source()` registration methods.
  - Add `create_iceberg_from_dataframe()` and `create_deltatable_from_parquet()` creation+registration methods.
  - Update `DatasetInfo.source_type` literal to include `"iceberg"`, `"mongo"`, `"deltatable"`.
  - Update `_generate_dataframe_guide()` to render new source types appropriately (Iceberg with SQL hint, Mongo with filter requirement, Delta with query options).
- **Depends on**: Modules 1-3

### Module 5: Source exports + `__init__.py` updates
- **Path**: `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/__init__.py`, `packages/ai-parrot/src/parrot/tools/dataset_manager/__init__.py`
- **Responsibility**: Export `IcebergSource`, `MongoSource`, `DeltaTableSource` from the sources and main package.
- **Depends on**: Modules 1-3

### Module 6: Unit Tests
- **Path**: `packages/ai-parrot/tests/tools/test_dataset_new_sources.py`
- **Responsibility**: Unit tests for all three new sources and the registration methods.
- **Depends on**: Modules 1-5

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_iceberg_source_prefetch_schema` | 1 | `prefetch_schema()` calls `load_table` + `schema()` and returns column→type dict |
| `test_iceberg_source_fetch_with_sql` | 1 | `fetch(sql=...)` calls `driver.query()` with correct table_id and factory |
| `test_iceberg_source_fetch_full_table` | 1 | `fetch()` without sql calls `driver.to_df()` |
| `test_iceberg_source_cache_key` | 1 | `cache_key` format: `iceberg:{table_id}` |
| `test_iceberg_source_describe` | 1 | `describe()` includes table_id |
| `test_iceberg_create_table_from_df` | 1 | Creates namespace, defines schema, writes df to Iceberg |
| `test_mongo_source_prefetch_schema` | 2 | `prefetch_schema()` calls `find_one()` and infers field types |
| `test_mongo_source_fetch_with_filter` | 2 | `fetch(filter={...})` queries collection with filter |
| `test_mongo_source_fetch_no_filter_raises` | 2 | `fetch()` without filter raises `ValueError` |
| `test_mongo_source_cache_key` | 2 | `cache_key` format: `mongo:{database}:{collection}` |
| `test_mongo_source_describe` | 2 | `describe()` includes collection and database |
| `test_deltatable_source_prefetch_schema` | 3 | `prefetch_schema()` calls `conn.schema()` |
| `test_deltatable_source_fetch_with_sql` | 3 | `fetch(sql=...)` calls `conn.query()` with tablename |
| `test_deltatable_source_fetch_with_columns` | 3 | `fetch(columns=[...])` calls `conn.to_df(columns=...)` |
| `test_deltatable_source_fetch_with_filter` | 3 | `fetch(filter=...)` calls `conn.query(sentence=filter)` |
| `test_deltatable_source_cache_key` | 3 | `cache_key` format: `delta:{md5(path)[:12]}` |
| `test_deltatable_source_describe` | 3 | `describe()` includes path and table name |
| `test_deltatable_create_from_parquet` | 3 | Creates Delta table from Parquet file |
| `test_manager_add_iceberg_source` | 4 | `add_iceberg_source()` registers entry with prefetched schema |
| `test_manager_add_mongo_source` | 4 | `add_mongo_source()` registers entry with prefetched schema |
| `test_manager_add_deltatable_source` | 4 | `add_deltatable_source()` registers entry with prefetched schema |
| `test_manager_create_iceberg_from_df` | 4 | `create_iceberg_from_dataframe()` creates table + registers source |
| `test_manager_create_deltatable_from_parquet` | 4 | `create_deltatable_from_parquet()` creates delta + registers source |
| `test_dataset_info_new_source_types` | 4 | `DatasetInfo.source_type` accepts `iceberg`, `mongo`, `deltatable` |
| `test_llm_guide_iceberg_source` | 4 | Guide renders Iceberg source with SQL hint |
| `test_llm_guide_mongo_source` | 4 | Guide renders Mongo source with filter requirement |
| `test_llm_guide_deltatable_source` | 4 | Guide renders Delta source with query options |

### Integration Tests

| Test | Description |
|---|---|
| `test_iceberg_full_flow` | Register Iceberg source → schema prefetched → guide shows columns → `fetch_dataset(sql=...)` materializes df |
| `test_mongo_full_flow` | Register Mongo source → schema from find_one → `fetch_dataset(filter={...})` materializes df |
| `test_deltatable_full_flow` | Register Delta source → schema prefetched → `fetch_dataset(sql=...)` materializes df |
| `test_create_iceberg_and_query` | Create Iceberg from df → register → query back → verify round-trip |
| `test_create_deltatable_and_query` | Create Delta from Parquet → register → query back → verify round-trip |
| `test_mixed_sources_all_types` | Register all 9 source types in one manager → list_available → metadata correct |

### Test Data / Fixtures

```python
import pytest
import pandas as pd
from unittest.mock import AsyncMock, MagicMock, patch

@pytest.fixture
def sample_df():
    return pd.DataFrame({
        'city': ['Berlin', 'Tokyo', 'Lima'],
        'population': [3432000, 13960000, 9750000],
        'country': ['DE', 'JP', 'PE'],
    })

@pytest.fixture
def mock_iceberg_driver():
    """Mock asyncdb iceberg driver."""
    driver = AsyncMock()
    driver.schema.return_value = {
        'city': 'string',
        'population': 'int64',
        'country': 'string',
    }
    driver.to_df = AsyncMock(return_value=pd.DataFrame({
        'city': ['Berlin'], 'population': [3432000], 'country': ['DE']
    }))
    driver.query = AsyncMock(return_value=(
        pd.DataFrame({'city': ['Tokyo'], 'population': [13960000]}), None
    ))
    return driver

@pytest.fixture
def mock_mongo_driver():
    """Mock asyncdb mongo driver."""
    driver = AsyncMock()
    driver.find_one = AsyncMock(return_value={
        'order_id': '123', 'amount': 99.99, 'status': 'shipped'
    })
    driver.query = AsyncMock(return_value=[
        {'order_id': '123', 'amount': 99.99, 'status': 'shipped'},
        {'order_id': '456', 'amount': 49.99, 'status': 'pending'},
    ])
    return driver

@pytest.fixture
def mock_delta_connection():
    """Mock asyncdb delta connection."""
    conn = AsyncMock()
    conn.schema.return_value = {
        'pickup_datetime': 'timestamp',
        'passenger_count': 'int64',
        'fare_amount': 'float64',
    }
    conn.to_df = AsyncMock(return_value=(
        pd.DataFrame({'passenger_count': [1, 2], 'fare_amount': [10.5, 20.0]}), None
    ))
    conn.query = AsyncMock(return_value=(
        pd.DataFrame({'passenger_count': [6], 'fare_amount': [35.0]}), None
    ))
    return conn
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `IcebergSource` implemented at `sources/iceberg.py` with `prefetch_schema`, `fetch`, `describe`, `cache_key`
- [ ] `IcebergSource.fetch()` supports SQL queries (via `driver.query()`) and full-table fetch (via `driver.to_df()`)
- [ ] `create_table_from_df()` static helper creates Iceberg tables from DataFrames via asyncdb
- [ ] `MongoSource` implemented at `sources/mongo.py` with `prefetch_schema`, `fetch`, `describe`, `cache_key`
- [ ] `MongoSource.fetch()` **requires** a filter parameter — raises `ValueError` without one
- [ ] `MongoSource.prefetch_schema()` uses `find_one()` to infer schema from a single document
- [ ] `DeltaTableSource` implemented at `sources/deltatable.py` with `prefetch_schema`, `fetch`, `describe`, `cache_key`
- [ ] `DeltaTableSource.fetch()` supports SQL queries, column selection, and filter expressions
- [ ] `create_from_parquet()` static helper creates Delta tables from Parquet files
- [ ] `DeltaTableSource` supports local, S3, and GCS paths
- [ ] `DatasetManager.add_iceberg_source()` registers and prefetches schema
- [ ] `DatasetManager.add_mongo_source()` registers and prefetches schema
- [ ] `DatasetManager.add_deltatable_source()` registers and prefetches schema
- [ ] `DatasetManager.create_iceberg_from_dataframe()` creates Iceberg table + registers source
- [ ] `DatasetManager.create_deltatable_from_parquet()` creates Delta table + registers source
- [ ] `DatasetInfo.source_type` updated to include `iceberg`, `mongo`, `deltatable`
- [ ] LLM guide renders new source types with appropriate usage hints
- [ ] All new sources exported from `sources/__init__.py` and `dataset_manager/__init__.py`
- [ ] All unit tests pass
- [ ] No breaking changes to existing source types or registration methods

---

## 6. Implementation Notes & Constraints

### Patterns to Follow

- Inherit from `DataSource` ABC — implement `fetch()`, `describe()`, `cache_key`; optionally override `prefetch_schema()`
- Use `asyncdb.AsyncDB` for driver instantiation (same pattern as `TableSource` and `SQLQuerySource`)
- Use `self.logger` from `logging.getLogger(__name__)` — no `print` statements
- Use `lazy_import` for asyncdb driver imports to avoid hard dependency at import time
- Follow credential resolution pattern from `TableSource._resolve_credentials()`
- All `fetch()` implementations must be `async`
- Use `factory="pandas"` for asyncdb query calls to get DataFrame output directly

### Source-Specific Implementation Notes

#### IcebergSource
- asyncdb iceberg driver uses DuckDB under the hood for SQL queries
- `table_id` format: `"namespace.table_name"` (e.g. `"demo.cities"`)
- `driver.load_table(table_id)` must be called before `driver.schema()`
- `driver.tables(namespace)` lists tables in a namespace
- For `create_table_from_df()`: infer PyArrow schema from DataFrame dtypes, call `driver.create_table()`, then `driver.write(df, table_id, mode="append")`

#### MongoSource
- MongoDB documents are schema-less — `find_one()` gives a best-effort schema from one document
- Exclude `_id` field from schema prefetch (internal MongoDB field)
- Filter must be a dict (MongoDB query syntax, e.g. `{"status": "active", "amount": {"$gt": 100}}`)
- Convert MongoDB cursor results to list, then to DataFrame
- Credential resolution: use DSN (MongoDB connection string) or credentials dict with host/port/user/password

#### DeltaTableSource
- asyncdb delta driver wraps `deltalake` + DuckDB
- `path` can be local filesystem, `s3://bucket/path`, or `gs://bucket/path`
- For S3/GCS: asyncdb handles storage options internally; if additional credentials needed, pass via `credentials` dict
- `conn.schema()` returns column→type mapping from the Delta table metadata
- `table_name` is used as the DuckDB alias for SQL queries (e.g. `SELECT * FROM {table_name} WHERE ...`)
- `mode` parameter for creation: `overwrite`, `append`, `error`, `ignore`

### Known Risks / Gotchas

- **Iceberg catalog availability**: Iceberg requires a catalog backend (REST, Hive, Glue, etc.). The asyncdb driver handles this via connection params, but misconfiguration will fail at prefetch time. Use `strict_schema=True` pattern from `TableSource`.
- **MongoDB full-collection scans**: The `required_filter=True` default prevents accidental `find({})` calls that could return millions of documents. This is a safety guardrail, not just a preference.
- **Delta table path permissions**: S3/GCS paths require appropriate IAM or credential configuration. Prefetch will fail with clear error if permissions are insufficient.
- **asyncdb driver availability**: All three drivers are optional extras in asyncdb. Users must install the appropriate extras (`asyncdb[iceberg]`, `asyncdb[mongo]`, `asyncdb[delta]`). Import failures should produce clear error messages.
- **Memory**: Iceberg and Delta queries can return large datasets. The LLM guide should include row-count estimation where possible and recommend LIMIT clauses.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `asyncdb` | existing (with extras) | Iceberg, Delta, Mongo drivers |
| `pyarrow` | existing | Iceberg schema definition, Parquet serialization |
| `deltalake` | optional | Delta Lake support (via asyncdb[delta]) |
| `pyiceberg` | optional | Iceberg support (via asyncdb[iceberg]) |
| `motor` / `pymongo` | optional | MongoDB support (via asyncdb[mongo]) |
| `pandas` | existing | DataFrame operations |

---

## 7. Open Questions

- [ ] **Iceberg catalog params default**: Should `DatasetManager` support a default Iceberg catalog configuration (similar to how `TableSource` resolves default DB credentials), or always require explicit `catalog_params`? — *Owner: Jesus*: always required explicit catalog.
- [ ] **MongoDB projection support**: Should `MongoSource.fetch()` accept a `projection` dict to limit returned fields, or is column selection always done post-fetch in pandas? — *Owner: Jesus*: always required explicit projection.
- [ ] **Delta Lake S3 credentials**: Should we use `boto3` session credentials, asyncdb's built-in storage options, or the FileManager interface for S3 access? — *Owner: Jesus*: there is a AWSInterface in parrot/interfaces with default credentials, use that.
- [ ] **Row count estimation**: Should `IcebergSource` and `DeltaTableSource` implement row-count estimation (like `TableSource.prefetch_row_count()`) for LLM size warnings? — *Owner: Jesus*: yes, implement row-count estimation for IcebergSource and DeltaTableSource.

---

## Worktree Strategy

- **Isolation unit**: per-spec (sequential tasks)
- Modules 1-3 are independent source files but Module 4 depends on all three; sequential execution is simpler and avoids merge conflicts in `tool.py`.
- **Cross-feature dependencies**: FEAT-030 (DatasetManager Lazy Data Sources) must be merged first — provides the `DataSource` ABC and subpackage structure. FEAT-059 (add-description-datasetmanager) should also be merged for the `description` parameter on registration methods.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-03-24 | Jesus Lara | Initial draft |
