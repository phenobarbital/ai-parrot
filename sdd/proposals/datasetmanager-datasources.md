# DatasetManager — Lazy Data Sources: Spec & Brainstorm

> **Status:** Draft / Brainstorm  
> **Target:** AI-Parrot `agents/tools/dataset_manager.py`  
> **Author:** Jesus  
> **Intent:** Extend DatasetManager from a "DataFrame catalog" to a "Data Source catalog" with lazy materialization, schema prefetch, and per-source Redis caching.

---

## 1. Motivation & Problem Statement

The current `DatasetManager` distinguishes between two kinds of entries:

- **Loaded** — a `pd.DataFrame` already in memory (`add_dataframe`)
- **Lazy (partial)** — a QuerySource slug that gets resolved on `load_data()` (`add_query`), is executed and converted into a Pandas Dataframe.

This works but has two structural problems:

1. **It will not scale.** Every new source type (BigQuery table, raw SQL, S3 Parquet, REST API) requires ad-hoc handling in `DatasetManager` itself, bloating the class.
2. **Schema is only available after materialization.** The LLM cannot reason about a dataset's structure until data has been fetched — meaning either an eager load or a blind first call.

**Goal:** Introduce a `DataSource` abstraction so that `DatasetManager` only cares about *lifecycle* (register, materialize, cache, evict) while each source type encapsulates its own fetch logic and schema discovery.

---

## 2. Core Concepts

### 2.1 `DataSource` — Abstract Base

A `DataSource` is a **reference** to data. It knows how to:

- **`prefetch_schema()`** — retrieve column names and types cheaply (no rows).
- **`fetch(**params)`** — execute and return a `pd.DataFrame`.
- **`describe()`** — produce a human-readable string for the LLM (including schema if available).
- **`cache_key`** — a stable, unique string for Redis keying.

```python
class DataSource(ABC):
    async def prefetch_schema(self) -> Dict[str, str]:
        """Optional. Subclasses override when cheap schema is available."""
        return {}

    @abstractmethod
    async def fetch(self, **params) -> pd.DataFrame: ...

    @abstractmethod
    def describe(self) -> str: ...

    @property
    @abstractmethod
    def cache_key(self) -> str: ...
```

**Key rule:** `prefetch_schema` must be cheap — a single metadata query, no data rows. `fetch` is the expensive call, only triggered on demand.

---

### 2.2 Concrete Source Types

#### `QuerySlugSource` (replaces current `add_query`)

```
QuerySlugSource(slug="troc_finance_visits_details")

qs.fetch(filter=**filter)
```

- Wraps the existing `QS` / `MultiQS` pattern.
- No schema prefetch (QuerySource doesn't expose column metadata cheaply).
- `cache_key`: `qs:{slug}`
- QuerySource supports filtering by passing a dictionary with a "filter" attribute like:
```json
{
    "filter": {
        "project": "EPSON"
    }
}
```

#### `SQLQuerySource` (new)

```
SQLQuerySource(sql="SELECT ...", driver="pg")
SQLQuerySource(sql="SELECT ...", driver="bigquery")
```

- User provides the full SQL and the AsyncDB driver name.
- No schema prefetch needed — the user already knows the shape.
- Supports simple `{param}` interpolation for reusable queries, but escaping to avoid SQL-inyections.
- `cache_key`: `sql:{driver}:{md5(sql)[:8]}`

#### `TableSource` (new — the interesting one)

```
TableSource(table="troc.finance_visits_details", driver="bigquery")
TableSource(table="public.orders", driver="pg")
```

- User provides a table reference and driver.
- **On registration**, `prefetch_schema()` is called automatically → fetches from `INFORMATION_SCHEMA`.
- The LLM receives column names + types **without materializing any rows**.
- `fetch(sql=...)` — the LLM-generated SQL is required at fetch time.
- `cache_key`: `table:{driver}:{table}`

#### `InMemorySource` (compatibility wrapper)

```
InMemorySource(df=existing_dataframe)
```

- Wraps an already-loaded `pd.DataFrame` so it fits the `DataSource` protocol.
- `prefetch_schema()` returns column types from the df directly.
- `fetch()` returns the df as-is.
- Used internally by `add_dataframe()` for backward compatibility.

---

### 2.3 `DatasetEntry` — Revised

`DatasetEntry` becomes a thin lifecycle wrapper:

```python
@dataclass
class DatasetEntry:
    name: str
    source: DataSource           # the "how to get data" contract
    _df: Optional[pd.DataFrame]  # in-memory cache (None = not materialized)
    metadata: Dict[str, Any]
    is_active: bool
    cache_ttl: int               # per-entry TTL in seconds
    _column_types: Optional[Dict[str, str]]

    @property
    def loaded(self) -> bool:
        return self._df is not None

    async def materialize(self, force: bool = False, **params) -> pd.DataFrame:
        if self._df is None or force:
            self._df = await self.source.fetch(**params)
            # build column metadata and types from the fresh df
        return self._df

    def evict(self) -> None:
        """Release df from memory. Source reference is kept."""
        self._df = None
        self._column_types = None
```

**Separation of concerns:**
- `DataSource` → knows HOW to get data and what the schema looks like.
- `DatasetEntry` → knows WHETHER data is in memory and manages its lifecycle.
- `DatasetManager` → orchestrates registration, caching, and LLM tool exposure.

---

## 3. Schema Prefetch Strategy

### For `TableSource`

At registration time (`add_table_source`), `DatasetManager` calls `prefetch_schema()` which runs a driver-aware `INFORMATION_SCHEMA` query:

| Driver | Schema Query |
|--------|-------------|
| `bigquery` | `SELECT column_name, data_type FROM {dataset}.INFORMATION_SCHEMA.COLUMNS WHERE table_name = '{table}'` |
| `pg` / `postgresql` | `SELECT column_name, data_type FROM information_schema.columns WHERE table_schema = '{schema}' AND table_name = '{table}'` |
| `mysql` / `mariadb` | `SELECT column_name, data_type FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = '{table}'` |
| fallback | `SELECT * FROM {table} LIMIT 0` (zero-row fetch) |

The result is stored in `TableSource._schema: Dict[str, str]` and exposed through `DatasetEntry` so it flows into `DatasetInfo` and the LLM-facing guide — **even when `loaded=False`**.

### For `QuerySlugSource` and `SQLQuerySource`

No schema prefetch. Schema becomes available only after first materialization (existing behavior). The LLM guide shows them as `[schema unavailable until first fetch]`.

Alternative Apprach: in case of QuerySlugSource, calling QS(slug={slug}, conditions={"querylimit"=1}) can help to prefetch one single row to know columns and types.

---

## 4. Registration API

### `add_table_source` — async (prefetch happens here)

```python
await manager.add_table_source(
    name="finance_visits",
    table="troc.finance_visits_details",
    driver="bigquery",
    dsn=None,           # uses config default if None
    metadata={"description": "Finance visits detail table"},
    cache_ttl=3600,
)
```

- Calls `prefetch_schema()` internally.
- On prefetch failure: logs warning, continues registration with empty schema.
- Returns: `"Table source 'finance_visits' registered (12 columns, BigQuery)"`

### `add_sql_source` — sync (no prefetch needed)

```python
manager.add_sql_source(
    name="weekly_report",
    sql="SELECT date, SUM(revenue) FROM orders WHERE date >= '{start_date}' GROUP BY 1",
    driver="pg",
    cache_ttl=3600 * 24 * 7,
)
```

### `add_query` — unchanged (backward compat)

```python
manager.add_query(name="daily_report", query_slug="troc_finance_visits_details")
```

Internally wraps slug in `QuerySlugSource`.

### `add_dataframe` — unchanged (backward compat)

```python
manager.add_dataframe(name="local_data", df=df)
```

Internally wraps df in `InMemorySource`.

---

## 5. Materialization & Caching

### On-demand materialization

`DatasetManager` exposes `materialize(name, **params)`:

```python
df = await manager.materialize("finance_visits", sql="SELECT * FROM troc.finance_visits_details LIMIT 100")
df = await manager.materialize("weekly_report", start_date="2024-01-01")
df = await manager.materialize("daily_report", start_date="2024-01-01")  # any parameter sent to a queryslug is added into the argument "conditions=" of QS() call.
```

### Redis cache flow

```
materialize(name, **params)
    │
    ├─► check Redis: key = "dataset:{source.cache_key}"
    │       hit  → deserialize → set entry._df → return
    │       miss ↓
    ├─► source.fetch(**params)
    ├─► entry._df = result
    ├─► serialize → Redis.setex(key, cache_ttl, data)
    └─► return df
```

**Cache key ownership:** The `cache_key` is owned by `DataSource`, not by the agent name. Two different agents registering the same `QuerySlugSource("troc_finance")` will share the same Redis cache entry.

### `force_refresh`

```python
df = await manager.materialize("finance_visits", sql="...", force_refresh=True)
```

Bypasses Redis, re-fetches, overwrites cache.

### Memory eviction

```python
manager.evict("finance_visits")     # free RAM, source + schema stay
manager.evict_all()                  # free all materialized dfs
manager.evict_unactive()             # free inactive entries only
```

---

## 6. `DatasetInfo` — Updated Schema

`DatasetInfo` must reflect the new reality: a dataset can have **known schema but no data**.

```python
class DatasetInfo(BaseModel):
    name: str
    alias: Optional[str]
    description: str = ""
    source_type: Literal["dataframe", "query_slug", "sql", "table"]
    source_description: str           # from source.describe()

    # Schema — available even when loaded=False (for TableSource)
    columns: List[str] = []
    column_types: Optional[Dict[str, str]] = None   # col → semantic type

    # Only meaningful when loaded=True
    shape: Optional[Tuple[int, int]] = None
    loaded: bool
    memory_usage_mb: float = 0.0
    null_count: int = 0

    is_active: bool
    cache_ttl: int
    cache_key: str
```

---

## 7. LLM-Facing Tools (Updated)

### Existing tools — behavior changes

| Tool | Change |
|------|--------|
| `list_available()` | Now shows `source_type`, `loaded` status, and columns even for unloaded TableSources |
| `get_metadata(name)` | Returns `DatasetInfo` including schema for unloaded entries |
| `get_active()` | No change |
| `activate / deactivate` | No change |

### New tools

#### `fetch_dataset(name, sql=None, conditions=None, force_refresh=False)`

Triggers materialization. The LLM calls this when it decides it needs the actual data.

- For `TableSource`: `sql` is **required** (LLM builds it using the schema from `DatasetInfo`).
- For `SQLQuerySource`: `conditions` can inject `{param}` values into the template.
- For `QuerySlugSource`: no extra params needed.
- Returns: confirmation + shape of resulting DataFrame + any NaN warnings.

#### `evict_dataset(name)`

Releases a materialized df from memory. Useful for long sessions with many datasets.

#### `get_source_schema(name)`

Returns the raw schema (`Dict[str, str]`) for a source. For `TableSource`, this is available before materialization. For others, requires a prior `fetch_dataset`.

---

## 8. LLM Guide — Handling Mixed States

The `_generate_dataframe_guide()` needs to handle entries that are registered but not yet loaded:

```
## Available Datasets

### finance_visits [TABLE — not loaded]
Source: troc.finance_visits_details via BigQuery
Columns (from schema):
  - visit_date (DATE)
  - visits (INT64)
  - source (STRING)
  - revenue (FLOAT64)
  - campaign_id (INT64)

To use this dataset, call fetch_dataset("finance_visits", sql="<your SQL>")
Build the SQL using the columns listed above.

---

### daily_report [QUERY SLUG — not loaded]
Source: QuerySource slug 'troc_finance_visits_details'
Columns: unknown until fetched

To use this dataset, call fetch_dataset("daily_report")

---

### local_data [DATAFRAME — loaded ✓]
Alias: df1
Shape: 1500 rows × 8 columns
...
```

---

## 9. Open Questions / To Decide

1. **DSN resolution:** Should each `DataSource` hold its own `dsn` string, or should `DatasetManager` hold a registry of named connections (e.g. `connections={"bigquery": ..., "pg": ...}`) and sources reference by name? The latter is cleaner for multi-environment configs (dev/prod/staging via navconfig): each `DataSource` hold its own "credentials" (to use same attribute for all), in `parrot/tools/databasequery.py` the is a function for getting default credentials for several databases, let's re-use that function for datasource get the credentials if None is provided.

2. **`SQLQuerySource` with LLM-generated params:** If the user registers a template SQL (`WHERE date >= '{start_date}'`), who validates that the LLM provides the right interpolation keys? Should this be Pydantic-validated at `fetch()` time?: yes, use pydantic validation.

3. **Prefetch failure policy:** If `prefetch_schema()` fails (e.g., BigQuery permissions error), should registration fail hard or soft? Current proposal: soft (log warning, register with empty schema). This should probably be configurable per-source (`strict_schema=True`): is preferable an strict_schema=True (by default) to avoid adding empty schemas if we dont have permissions.

4. **Cache serialization format:** Current impl uses `json_encoder(df.to_dict('records'))`. For large DataFrames this is slow and lossy (dtype info lost). Consider Parquet bytes via `io.BytesIO` as an alternative Redis storage format, gated behind a `cache_format: Literal["json", "parquet"] = "json"` option on `DatasetManager`: if is faster, I'm agree for using Parquet instead JSON.

5. **`TableSource` SQL validation:** Should the manager validate that the SQL in `fetch_dataset()` actually references `self.table` (prevent the LLM from running arbitrary SQL)? A simple `table in sql` check plus optional allowlist: Yes

6. **Async registration in sync contexts:** `add_table_source` is async because of `prefetch_schema`. This could be a friction point if `DatasetManager` is being set up in a sync `__init__`. Pattern options:
   - `await manager.setup()` method that runs all pending prefetches after sync init.
   - `add_table_source_lazy()` sync variant that defers prefetch to first `list_available()` call.

---

## 10. Migration Path from Current DatasetManager

| Current method | New equivalent | Notes |
|----------------|---------------|-------|
| `add_dataframe(name, df)` | unchanged | wraps in `InMemorySource` internally |
| `add_dataframe_from_file(name, path)` | unchanged | wraps in `FileSource` internally |
| `add_query(name, slug)` | unchanged | wraps in `QuerySlugSource` internally |
| `load_data(query, agent_name)` | `materialize(name)` | per-entry instead of batch |
| `_call_qs()` | `QuerySlugSource.fetch()` | moved out of manager |
| `_call_multiquery()` | `MultiQuerySlugSource.fetch()` | new source type |
| `_cache_data()` | `DatasetManager._cache_df(source, df)` | cache_key from source |
| `_get_cached_data()` | `DatasetManager._get_cached_df(source)` | idem |

All existing `PandasAgent` code that calls `add_dataframe` or `add_query` continues to work unchanged.

---

## 11. File / Module Structure Proposal

move current `parrot/tools/dataset_manager.py` into own subpackage `parrot/tools/dataset_manager/` (renamed to tool.py and import `DatasetManager` on `__init__.py`)

```
agents/
  tools/
    dataset_manager/
      __init__.py
      tool.py          # DatasetManager (trimmed — no source logic)
      sources/
        __init__.py               # exports all source types
        base.py                   # DataSource ABC
        memory.py                 # InMemorySource
        query_slug.py             # QuerySlugSource, MultiQuerySlugSource
        sql.py                    # SQLQuerySource
        table.py                  # TableSource (+ schema dialect handlers)
        file.py                   # FileSource (CSV, Excel)
```

This keeps `dataset_manager` as pure lifecycle/catalog logic, and lets new source types be added without touching the manager.