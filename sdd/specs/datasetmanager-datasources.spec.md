# Feature Specification: DatasetManager Lazy Data Sources

**Feature ID**: FEAT-030
**Date**: 2026-03-07
**Author**: Jesus Lara
**Status**: approved
**Target version**: 1.x.x
**Proposal**: `sdd/proposals/datasetmanager-datasources.md`

---

## 1. Motivation & Business Requirements

### Problem Statement

The current `DatasetManager` (`parrot/tools/dataset_manager.py`) distinguishes only two kinds of entries:

- **Loaded** — a `pd.DataFrame` already in memory (`add_dataframe`)
- **Lazy (partial)** — a QuerySource slug resolved on `load_data()` (`add_query`), executed and converted into a Pandas DataFrame

This has two structural problems:

1. **Scalability**: every new source type (BigQuery table, raw SQL, S3 Parquet, REST API) requires ad-hoc handling inside `DatasetManager` itself, bloating the class.
2. **Blind schema**: the LLM cannot reason about a dataset's structure until data has been fetched — meaning either an eager load or a blind first call.

### Goals

- Introduce a `DataSource` abstraction so `DatasetManager` only manages lifecycle (register, materialize, cache, evict) while each source type encapsulates its own fetch and schema-discovery logic.
- Enable the LLM to receive column names and types **without materializing any rows** (for `TableSource`).
- Support lazy materialization with per-entry Redis caching (Parquet format for efficiency).
- Provide backward-compatible `add_dataframe` and `add_query` APIs.
- Reorganize `dataset_manager.py` into a sub-package for extensibility.

### Non-Goals (explicitly out of scope)

- Real-time streaming of large datasets into memory
- Direct S3/GCS/Azure Blob source types (future `FileSource` extension)
- Multi-tenant dataset isolation (handled by existing session scoping in FEAT-021)
- Schema migrations or DDL operations
- Automatic query optimization

---

## 2. Architectural Design

### Overview

Four new source types implement a common `DataSource` ABC. `DatasetEntry` becomes a thin lifecycle wrapper around a `DataSource`. `DatasetManager` orchestrates registration, materialization, and caching without any source-specific logic.

```
┌──────────────────────────────────────────────────────────────────────┐
│                          DatasetManager                              │
│  register / materialize / evict / cache / LLM tool exposure         │
└───────────┬──────────────────────────────────────────────────────────┘
            │  owns N
            ▼
┌──────────────────────────────────────────────────────────────────────┐
│                           DatasetEntry                               │
│  name / source / _df / metadata / is_active / cache_ttl             │
│  materialize() / evict()                                             │
└───────────┬──────────────────────────────────────────────────────────┘
            │  delegates to
            ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         DataSource (ABC)                                    │
│  prefetch_schema() / fetch(**params) / describe() / cache_key               │
├─────────────┬──────────────────┬──────────────────┬──────────────────────── ┤
│ InMemory    │  QuerySlugSource │  SQLQuerySource  │  TableSource            │
│ Source      │  (+ MultiQS)     │                  │  (schema prefetch)      │
└─────────────┴──────────────────┴──────────────────┴─────────────────────────┘
```

### Separation of Concerns

| Layer | Responsibility |
|---|---|
| `DataSource` | HOW to get data; schema discovery |
| `DatasetEntry` | WHETHER data is in memory; lifecycle |
| `DatasetManager` | Orchestrates registration, caching, LLM tool exposure |

### `DataSource` — Abstract Base

```python
from abc import ABC, abstractmethod
from typing import Dict
import pandas as pd


class DataSource(ABC):
    """Abstract base for all data sources. Knows how to fetch data and describe itself."""

    async def prefetch_schema(self) -> Dict[str, str]:
        """Return column→type mapping without fetching rows. Override when cheap schema is available."""
        return {}

    @abstractmethod
    async def fetch(self, **params) -> pd.DataFrame:
        """Execute and return a DataFrame. Expensive — called only on demand."""
        ...

    @abstractmethod
    def describe(self) -> str:
        """Human-readable description for the LLM guide."""
        ...

    @property
    @abstractmethod
    def cache_key(self) -> str:
        """Stable, unique string for Redis keying. Shared across agents for the same source."""
        ...
```

**Key rule:** `prefetch_schema` must be cheap — a single metadata query, no data rows.

### Concrete Source Types

#### `InMemorySource`
Wraps an already-loaded `pd.DataFrame`. Used internally by `add_dataframe()` for backward compatibility.
- `prefetch_schema()`: returns column dtypes from the df directly.
- `fetch()`: returns the df as-is.
- `cache_key`: `mem:{name}`

#### `QuerySlugSource` / `MultiQuerySlugSource`
Replaces current `add_query` logic. Wraps the existing `QS` / `MultiQS` pattern.
- No schema prefetch (QuerySource does not expose column metadata cheaply). Alternative: call `QS(slug=slug, conditions={"querylimit": 1})` after first registration to prefetch one row and infer schema.
- `fetch(**params)`: any params become `conditions=` in the `QS()` call.
- `cache_key`: `qs:{slug}`

#### `SQLQuerySource`
User provides full SQL and AsyncDB driver name. Supports `{param}` interpolation validated by Pydantic at `fetch()` time.
- No schema prefetch needed — the user already knows the shape.
- Escaping is applied to interpolated values to prevent SQL injection.
- `cache_key`: `sql:{driver}:{md5(sql)[:8]}`

#### `TableSource`
User provides a table reference and driver. On registration, `prefetch_schema()` is called automatically via an `INFORMATION_SCHEMA` query. The LLM receives column names + types **before any rows are fetched**.
- `fetch(sql=...)` — LLM-generated SQL required at fetch time.
- SQL is validated: `self.table` must appear in the SQL string (simple allowlist check).
- `cache_key`: `table:{driver}:{table}`

### `DatasetEntry` — Revised

```python
@dataclass
class DatasetEntry:
    name: str
    source: DataSource
    _df: Optional[pd.DataFrame]    # None = not materialized
    metadata: Dict[str, Any]
    is_active: bool
    cache_ttl: int                 # per-entry TTL in seconds
    _column_types: Optional[Dict[str, str]]  # from prefetch or post-fetch

    @property
    def loaded(self) -> bool:
        return self._df is not None

    async def materialize(self, force: bool = False, **params) -> pd.DataFrame:
        if self._df is None or force:
            self._df = await self.source.fetch(**params)
            self._column_types = DatasetManager.categorize_columns(self._df)
        return self._df

    def evict(self) -> None:
        """Release df from memory. Source reference and schema are retained."""
        self._df = None
        self._column_types = None
```

### Schema Prefetch Strategy — `TableSource`

Driver-aware `INFORMATION_SCHEMA` queries at registration time:

| Driver | Schema Query |
|---|---|
| `bigquery` | `SELECT column_name, data_type FROM {dataset}.INFORMATION_SCHEMA.COLUMNS WHERE table_name = '{table}'` |
| `pg` / `postgresql` | `SELECT column_name, data_type FROM information_schema.columns WHERE table_schema = '{schema}' AND table_name = '{table}'` |
| `mysql` / `mariadb` | `SELECT column_name, data_type FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = '{table}'` |
| fallback | `SELECT * FROM {table} LIMIT 0` (zero-row fetch) |

Prefetch failure policy: **strict by default** (`strict_schema=True`) — registration fails if schema cannot be fetched. Configurable per source with `strict_schema=False` to allow soft failure (log warning, register with empty schema).

### Credential Resolution

Each `DataSource` holds its own `credentials` attribute. If `None` is provided at construction, the source calls the existing credential helper from `parrot/tools/databasequery.py` to resolve defaults for the given driver. No new credential registry is introduced.

### Caching

Redis cache flow:
```
materialize(name, **params)
    │
    ├─► check Redis: key = "dataset:{source.cache_key}"
    │       hit  → deserialize (Parquet bytes) → set entry._df → return
    │       miss ↓
    ├─► source.fetch(**params)
    ├─► entry._df = result
    ├─► serialize (Parquet via io.BytesIO) → Redis.setex(key, cache_ttl, data)
    └─► return df
```

Cache serialization: **Parquet** (`df.to_parquet()` / `pd.read_parquet()`) via `io.BytesIO`. Faster and dtype-preserving compared to the current JSON approach. The `cache_key` is owned by `DataSource`, not by agent name — two agents registering the same `QuerySlugSource("troc_finance")` share the same Redis entry.

`force_refresh=True` bypasses Redis, re-fetches, and overwrites the cache entry.

### Updated `DatasetInfo` Model

```python
class DatasetInfo(BaseModel):
    name: str
    alias: Optional[str]
    description: str = ""
    source_type: Literal["dataframe", "query_slug", "sql", "table"]
    source_description: str           # from source.describe()

    # Schema — available even when loaded=False (for TableSource)
    columns: List[str] = []
    column_types: Optional[Dict[str, str]] = None

    # Only meaningful when loaded=True
    shape: Optional[Tuple[int, int]] = None
    loaded: bool
    memory_usage_mb: float = 0.0
    null_count: int = 0

    is_active: bool
    cache_ttl: int
    cache_key: str
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot/tools/dataset_manager.py` | refactored → subpackage | moved to `parrot/tools/dataset_manager/` |
| `parrot/tools/databasequery.py` | reused | credential resolution helper |
| `PandasAgent` | unchanged | uses `add_dataframe`, `add_query` — backward compat |
| `DatasetManagerHandler` (FEAT-021) | unchanged | `DatasetManager` public API preserved |
| Redis (`REDIS_DATASET_URL`) | extended | Parquet serialization replaces JSON |
| `QS` / `MultiQS` (QuerySource) | wrapped | `QuerySlugSource` delegates to these |
| AsyncDB drivers | new use | `TableSource` and `SQLQuerySource` use AsyncDB |

---

## 3. Module Breakdown

### Module 1: Subpackage scaffold + `DataSource` ABC
- **Path**: `parrot/tools/dataset_manager/__init__.py`, `parrot/tools/dataset_manager/sources/__init__.py`, `parrot/tools/dataset_manager/sources/base.py`
- **Responsibility**: Move existing file, create package structure, define `DataSource` ABC
- **Depends on**: Nothing new

### Module 2: `InMemorySource`
- **Path**: `parrot/tools/dataset_manager/sources/memory.py`
- **Responsibility**: Wrap existing `pd.DataFrame` as a `DataSource`
- **Depends on**: Module 1

### Module 3: `QuerySlugSource` / `MultiQuerySlugSource`
- **Path**: `parrot/tools/dataset_manager/sources/query_slug.py`
- **Responsibility**: Wrap existing `QS` / `MultiQS` pattern; one-row schema prefetch option
- **Depends on**: Module 1

### Module 4: `SQLQuerySource`
- **Path**: `parrot/tools/dataset_manager/sources/sql.py`
- **Responsibility**: User-provided SQL with `{param}` interpolation; Pydantic validation at fetch time; SQL injection escaping
- **Depends on**: Module 1, `parrot/tools/databasequery.py`

### Module 5: `TableSource`
- **Path**: `parrot/tools/dataset_manager/sources/table.py`
- **Responsibility**: Driver-aware schema prefetch from `INFORMATION_SCHEMA`; SQL validation at fetch time; strict/soft schema failure policy
- **Depends on**: Module 1, `parrot/tools/databasequery.py`

### Module 6: Revised `DatasetEntry` + `DatasetInfo`
- **Path**: `parrot/tools/dataset_manager/tool.py`
- **Responsibility**: `DatasetEntry` dataclass with `materialize()`/`evict()`; updated `DatasetInfo` Pydantic model with `source_type`, `source_description`, `cache_key`
- **Depends on**: Modules 1-5

### Module 7: `DatasetManager` — trimmed core
- **Path**: `parrot/tools/dataset_manager/tool.py` (continued)
- **Responsibility**: Registration API (`add_table_source`, `add_sql_source`, `add_query`, `add_dataframe`); `materialize()`; Redis caching with Parquet serialization; `evict()`/`evict_all()`/`evict_unactive()`; updated LLM tools (`list_available`, `get_metadata`, `fetch_dataset`, `evict_dataset`, `get_source_schema`); updated LLM guide generation for mixed load states
- **Depends on**: Module 6

### Module 8: Unit Tests
- **Path**: `tests/tools/test_datasources.py`
- **Responsibility**: Unit tests for all source types and the updated `DatasetManager`
- **Depends on**: Modules 1-7

### Module 9: Integration Tests
- **Path**: `tests/tools/test_datasetmanager_integration.py`
- **Responsibility**: End-to-end tests using mocked AsyncDB drivers and Redis
- **Depends on**: Module 7

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_inmemory_source_schema` | 2 | `prefetch_schema()` returns correct dtype map from DataFrame |
| `test_inmemory_source_fetch` | 2 | `fetch()` returns the wrapped DataFrame unchanged |
| `test_inmemory_cache_key` | 2 | `cache_key` format: `mem:{name}` |
| `test_queryslug_fetch_no_params` | 3 | `fetch()` calls QS with no conditions |
| `test_queryslug_fetch_with_params` | 3 | `fetch()` passes params as `conditions=` |
| `test_queryslug_schema_prefetch` | 3 | Single-row QS call infers schema columns |
| `test_queryslug_cache_key` | 3 | `cache_key` format: `qs:{slug}` |
| `test_sql_source_param_interpolation` | 4 | `{start_date}` interpolated correctly |
| `test_sql_source_missing_param_raises` | 4 | Pydantic validation raises on missing param |
| `test_sql_source_sql_injection_escaped` | 4 | Injected value is escaped, not executed |
| `test_sql_source_cache_key` | 4 | `cache_key` format: `sql:{driver}:{md5[:8]}` |
| `test_table_source_prefetch_pg` | 5 | `INFORMATION_SCHEMA` query run for pg driver |
| `test_table_source_prefetch_bigquery` | 5 | `INFORMATION_SCHEMA` query run for bigquery |
| `test_table_source_prefetch_fallback` | 5 | Fallback `LIMIT 0` when driver unknown |
| `test_table_source_strict_schema_fails` | 5 | Registration fails when prefetch errors with `strict_schema=True` |
| `test_table_source_soft_schema_continues` | 5 | Registration continues with empty schema when `strict_schema=False` |
| `test_table_source_sql_validation_pass` | 5 | SQL containing table name passes validation |
| `test_table_source_sql_validation_fail` | 5 | SQL not referencing table name raises error |
| `test_table_source_cache_key` | 5 | `cache_key` format: `table:{driver}:{table}` |
| `test_dataset_entry_materialize` | 6 | `materialize()` calls `source.fetch()` and stores result |
| `test_dataset_entry_materialize_cached` | 6 | Second `materialize()` skips fetch if already loaded |
| `test_dataset_entry_evict` | 6 | `evict()` clears `_df` and `_column_types`, preserves source |
| `test_dataset_entry_force_refresh` | 6 | `materialize(force=True)` re-fetches even if loaded |
| `test_dataset_info_unloaded_table` | 6 | `DatasetInfo` exposes schema columns when `loaded=False` |
| `test_manager_add_table_source_async` | 7 | `add_table_source()` calls prefetch and registers entry |
| `test_manager_add_sql_source_sync` | 7 | `add_sql_source()` registers without prefetch |
| `test_manager_add_query_backward_compat` | 7 | `add_query()` wraps slug in `QuerySlugSource` |
| `test_manager_add_dataframe_backward_compat` | 7 | `add_dataframe()` wraps df in `InMemorySource` |
| `test_manager_materialize_redis_hit` | 7 | Redis hit skips source fetch, restores Parquet df |
| `test_manager_materialize_redis_miss` | 7 | Redis miss fetches, serializes to Parquet, stores |
| `test_manager_materialize_force_refresh` | 7 | `force_refresh=True` bypasses Redis |
| `test_manager_evict_single` | 7 | `evict("name")` releases df, source retained |
| `test_manager_evict_all` | 7 | `evict_all()` releases all materialized dfs |
| `test_manager_evict_unactive` | 7 | `evict_unactive()` only evicts inactive entries |
| `test_llm_tool_list_available` | 7 | `list_available()` shows unloaded TableSource with schema |
| `test_llm_tool_get_metadata` | 7 | `get_metadata()` returns DatasetInfo with schema for unloaded |
| `test_llm_tool_fetch_dataset_table` | 7 | `fetch_dataset()` requires sql for TableSource |
| `test_llm_tool_fetch_dataset_query_slug` | 7 | `fetch_dataset()` works without sql for QuerySlugSource |
| `test_llm_tool_evict_dataset` | 7 | `evict_dataset()` frees memory |
| `test_llm_tool_get_source_schema` | 7 | `get_source_schema()` returns schema pre-fetch for TableSource |
| `test_llm_guide_mixed_states` | 7 | Guide renders TABLE/QUERY/DATAFRAME states correctly |
| `test_cache_key_shared_across_agents` | 7 | Two managers with same slug share same Redis key |

### Integration Tests

| Test | Description |
|---|---|
| `test_table_source_full_flow_pg` | Register TableSource → schema prefetched → LLM guide shows columns → `fetch_dataset(sql=...)` materializes df |
| `test_table_source_full_flow_bigquery` | Same flow against BigQuery mock driver |
| `test_sql_source_parameterized_query` | Register SQLQuerySource → materialize with params → Redis caches result → second call hits cache |
| `test_query_slug_force_refresh` | Materialize → Redis write → `force_refresh=True` re-fetches and overwrites |
| `test_backward_compat_add_dataframe` | Existing `PandasAgent` `add_dataframe` + `load_data` flow still works |
| `test_backward_compat_add_query` | Existing `add_query` + `load_data` flow still works |
| `test_parquet_roundtrip_dtypes` | Serialize df to Parquet → deserialize → dtypes preserved |
| `test_multiple_sources_same_manager` | Mix of InMemory, QuerySlug, SQL, Table in one manager |

### Test Data / Fixtures

```python
import pytest
import pandas as pd
from unittest.mock import AsyncMock, MagicMock, patch

@pytest.fixture
def sample_df():
    return pd.DataFrame({
        'date': pd.to_datetime(['2024-01-01', '2024-01-02']),
        'visits': [100, 150],
        'revenue': [1000.0, 1500.0],
    })

@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.setex = AsyncMock()
    return redis

@pytest.fixture
def mock_asyncdb_pg():
    """Mock pg AsyncDB driver returning INFORMATION_SCHEMA rows."""
    driver = AsyncMock()
    driver.fetch = AsyncMock(return_value=[
        {'column_name': 'visit_date', 'data_type': 'date'},
        {'column_name': 'visits', 'data_type': 'integer'},
        {'column_name': 'revenue', 'data_type': 'numeric'},
    ])
    return driver

@pytest.fixture
def mock_qs():
    qs = AsyncMock()
    qs.get_result = AsyncMock(return_value=pd.DataFrame({'col1': [1, 2]}))
    return qs
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `parrot/tools/dataset_manager.py` moved to `parrot/tools/dataset_manager/` subpackage; `DatasetManager` importable from `parrot/tools/dataset_manager` unchanged
- [ ] `DataSource` ABC defined at `parrot/tools/dataset_manager/sources/base.py` with `prefetch_schema`, `fetch`, `describe`, `cache_key`
- [ ] `InMemorySource` implemented; `add_dataframe()` wraps df in `InMemorySource` internally
- [ ] `QuerySlugSource` and `MultiQuerySlugSource` implemented; `add_query()` wraps slug internally
- [ ] `SQLQuerySource` implemented with Pydantic-validated `{param}` interpolation and SQL injection escaping
- [ ] `TableSource` implemented with driver-aware `INFORMATION_SCHEMA` prefetch for pg, bigquery, mysql/mariadb, and fallback
- [ ] `strict_schema=True` default: registration of `TableSource` fails if prefetch fails
- [ ] `DatasetEntry` is a dataclass with `source: DataSource`, `materialize()`, and `evict()`
- [ ] `DatasetInfo` updated: `source_type`, `source_description`, `cache_key` added; `columns`/`column_types` available when `loaded=False`
- [ ] `DatasetManager.materialize(name, **params)` with Redis cache (Parquet serialization)
- [ ] `DatasetManager.materialize()` accepts `force_refresh=True` to bypass cache
- [ ] `DatasetManager.evict()`, `evict_all()`, `evict_unactive()` implemented
- [ ] `add_table_source()` is async and calls `prefetch_schema()` on registration
- [ ] `add_sql_source()` is sync (no prefetch)
- [ ] `TableSource.fetch()` validates that `self.table` appears in the provided SQL
- [ ] Credential resolution uses existing helper from `parrot/tools/databasequery.py`
- [ ] LLM tool `fetch_dataset(name, sql=None, conditions=None, force_refresh=False)` added
- [ ] LLM tool `evict_dataset(name)` added
- [ ] LLM tool `get_source_schema(name)` added
- [ ] `list_available()` and `get_metadata()` show schema for unloaded `TableSource` entries
- [ ] LLM guide (`_generate_dataframe_guide`) renders TABLE / QUERY SLUG / SQL / DATAFRAME states correctly
- [ ] All existing `PandasAgent` code using `add_dataframe` or `add_query` continues to work unchanged
- [ ] All unit tests pass: `pytest tests/tools/test_datasources.py -v`
- [ ] All integration tests pass: `pytest tests/tools/test_datasetmanager_integration.py -v`

---

## 6. Implementation Notes & Constraints

### Patterns to Follow

- Inherit `AbstractToolkit` for `DatasetManager` (unchanged)
- Use `self.logger` from `navconfig.logging` (no `print`)
- All `DataSource.fetch()` implementations must be `async`
- Use `datamodel.parsers.json.json_encoder` / `json_decoder` only for non-DataFrame payloads
- Use `io.BytesIO` + `df.to_parquet()` / `pd.read_parquet()` for Redis serialization
- Follow existing `REDIS_DATASET_URL` connection from `parrot/conf`

### Subpackage `__init__.py` exports

```python
# parrot/tools/dataset_manager/__init__.py
from .tool import DatasetManager, DatasetEntry, DatasetInfo
from .sources import DataSource, InMemorySource, QuerySlugSource, SQLQuerySource, TableSource

__all__ = [
    "DatasetManager",
    "DatasetEntry",
    "DatasetInfo",
    "DataSource",
    "InMemorySource",
    "QuerySlugSource",
    "SQLQuerySource",
    "TableSource",
]
```

### Registration API Summary

```python
# async — prefetch happens here
await manager.add_table_source(
    name="finance_visits",
    table="troc.finance_visits_details",
    driver="bigquery",
    dsn=None,          # uses databasequery.py default if None
    metadata={"description": "Finance visits detail table"},
    cache_ttl=3600,
    strict_schema=True,
)

# sync — no prefetch
manager.add_sql_source(
    name="weekly_report",
    sql="SELECT date, SUM(revenue) FROM orders WHERE date >= '{start_date}' GROUP BY 1",
    driver="pg",
    cache_ttl=3600 * 24 * 7,
)

# unchanged — backward compat
manager.add_query(name="daily_report", query_slug="troc_finance_visits_details")
manager.add_dataframe(name="local_data", df=df)
```

### Async Registration in Sync Contexts

`add_table_source` is async due to `prefetch_schema`. To support sync `__init__` usage, expose an `await manager.setup()` method that runs all pending prefetches registered via a deferred list. Alternatively, `add_table_source_deferred()` can be used for sync contexts and prefetch is triggered on first `list_available()` or `materialize()`.

### Known Risks / Gotchas

- **Memory**: Large DataFrames kept in `entry._df` across long sessions. `evict_unactive()` should be called periodically.
- **Parquet deps**: Requires `pyarrow` or `fastparquet`; confirm present in `pyproject.toml`: pyarrow with snappy compression.
- **BigQuery credentials**: Service account or ADC must be configured in environment; `TableSource` will fail at prefetch time if not set.
- **SQL validation is naive**: `table in sql` check prevents most accidents but is not a security boundary; agent permissions still control which sources are accessible.
- **MultiQS**: `MultiQuerySlugSource` follows the same pattern as `QuerySlugSource` but wraps multiple slugs and merges results; schema prefetch is per-slug.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `pandas` | existing | DataFrame operations |
| `pyarrow` | add if missing | Parquet serialization |
| `redis` | existing | Cache via `REDIS_DATASET_URL` |
| `asyncdb` | existing | `TableSource` / `SQLQuerySource` drivers |
| `pydantic` | existing | Param validation in `SQLQuerySource` |

### Migration Path from Current `DatasetManager`

| Current method | New equivalent | Notes |
|---|---|---|
| `add_dataframe(name, df)` | unchanged | wraps in `InMemorySource` internally |
| `add_dataframe_from_file(name, path)` | unchanged | wraps in `FileSource` internally (future) |
| `add_query(name, slug)` | unchanged | wraps in `QuerySlugSource` internally |
| `load_data(query, agent_name)` | `materialize(name)` | per-entry instead of batch |
| `_call_qs()` | `QuerySlugSource.fetch()` | moved out of manager |
| `_call_multiquery()` | `MultiQuerySlugSource.fetch()` | new source type |
| `_cache_data()` | `DatasetManager._cache_df(source, df)` | `cache_key` from source |
| `_get_cached_data()` | `DatasetManager._get_cached_df(source)` | idem |

---

## 7. Open Questions

- [ ] **`add_table_source_deferred()` sync variant**: Decide before Module 7 implementation whether to include a sync deferred registration path or rely solely on `await manager.setup()`. — *Owner: architect*: rely solely on manager.setup()
- [ ] **Parquet vs JSON config flag**: The proposal mentions `cache_format: Literal["json", "parquet"]`. Since Parquet is agreed as the default, decide if a fallback JSON mode is needed for tooling that can't handle Parquet bytes. — *Owner: backend*: we don't need json fallback.
- [ ] **`QuerySlugSource` schema prefetch**: Confirm whether the one-row QS call for schema discovery should be enabled by default or opt-in via `prefetch_schema=True`. — *Owner: architect*: confirmed.
- [ ] **`pyarrow` dependency**: Confirm `pyarrow` is already present in `pyproject.toml`, or add it as part of Module 1. — *Owner: backend*: is already present.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-03-07 | claude-session | Initial draft from proposal `sdd/proposals/datasetmanager-datasources.md` |
