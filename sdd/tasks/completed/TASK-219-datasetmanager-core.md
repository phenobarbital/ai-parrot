# TASK-219: DatasetManager Core — Registration, Materialization, Caching, LLM Tools

**Feature**: DatasetManager Lazy Data Sources (FEAT-030)
**Spec**: `sdd/specs/datasetmanager-datasources.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-6h)
**Depends-on**: TASK-213, TASK-214, TASK-215, TASK-216, TASK-217, TASK-218
**Assigned-to**: null

---

## Context

> The core orchestration layer. Replaces source-specific logic currently scattered in
> DatasetManager with the new DataSource abstraction. Adds new registration methods, switches
> Redis caching to Parquet serialization, adds three new LLM tools, and updates the guide
> generator for mixed load states.

---

## Scope

Modify `parrot/tools/dataset_manager/tool.py` — the `DatasetManager` class.

### 1. Registration API

**Keep unchanged (backward compat):**

```python
def add_dataframe(self, name: str, df: pd.DataFrame, metadata=None, ...) -> str:
    """Wraps df in InMemorySource internally."""
    source = InMemorySource(df=df, name=name)
    entry = DatasetEntry(name=name, source=source, metadata=metadata or {}, ...)
    self._datasets[name] = entry
    return f"Dataset '{name}' added (in-memory)."

def add_query(self, name: str, query_slug: str, metadata=None, ...) -> str:
    """Wraps slug in QuerySlugSource internally."""
    source = QuerySlugSource(slug=query_slug)
    entry = DatasetEntry(name=name, source=source, ...)
    self._datasets[name] = entry
    return f"Dataset '{name}' registered (query slug)."
```

**New async method:**

```python
async def add_table_source(
    self,
    name: str,
    table: str,
    driver: str,
    dsn: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    cache_ttl: int = 3600,
    strict_schema: bool = True,
) -> str:
    """Register a table with schema prefetch. Async — prefetch happens here."""
    source = TableSource(table=table, driver=driver, dsn=dsn, strict_schema=strict_schema)
    await source.prefetch_schema()  # raises on failure if strict_schema=True
    entry = DatasetEntry(name=name, source=source, metadata=metadata or {}, cache_ttl=cache_ttl)
    self._datasets[name] = entry
    n_cols = len(source._schema)
    return f"Table source '{name}' registered ({n_cols} columns, {driver})."
```

**New sync method:**

```python
def add_sql_source(
    self,
    name: str,
    sql: str,
    driver: str,
    dsn: Optional[str] = None,
    cache_ttl: int = 3600,
    metadata: Optional[Dict[str, Any]] = None,
) -> str:
    """Register a parameterized SQL source. Sync — no prefetch needed."""
    source = SQLQuerySource(sql=sql, driver=driver, dsn=dsn)
    entry = DatasetEntry(name=name, source=source, metadata=metadata or {}, cache_ttl=cache_ttl)
    self._datasets[name] = entry
    return f"SQL source '{name}' registered ({driver})."
```

**Remove old internal methods** that are now encapsulated in source classes:
- `_call_qs()` → logic now in `QuerySlugSource.fetch()`
- `_call_multiquery()` → logic now in `MultiQuerySlugSource.fetch()`

### 2. `materialize(name, force_refresh=False, **params)` — new method

```python
async def materialize(self, name: str, force_refresh: bool = False, **params) -> pd.DataFrame:
    """
    On-demand materialization with Redis caching (Parquet format).

    Flow:
      1. Check Redis: key = "dataset:{source.cache_key}"
         - hit → deserialize Parquet → set entry._df → return
         - miss → continue
      2. entry.materialize(force=force_refresh, **params)
      3. Serialize to Parquet → Redis.setex(key, cache_ttl, data)
      4. return df
    """
```

Replace existing `load_data()` method with `materialize()`. Keep `load_data()` as a deprecated alias if existing callers use it.

### 3. Redis caching — Parquet format

Replace JSON serialization with Parquet:

```python
import io

async def _cache_df(self, source: DataSource, df: pd.DataFrame, ttl: int) -> None:
    """Serialize df to Parquet bytes and store in Redis."""
    if self._redis is None:
        return
    buf = io.BytesIO()
    df.to_parquet(buf, index=False, compression='snappy')
    key = f"dataset:{source.cache_key}"
    await self._redis.setex(key, ttl, buf.getvalue())

async def _get_cached_df(self, source: DataSource) -> Optional[pd.DataFrame]:
    """Retrieve and deserialize Parquet bytes from Redis."""
    if self._redis is None:
        return None
    key = f"dataset:{source.cache_key}"
    data = await self._redis.get(key)
    if data is None:
        return None
    return pd.read_parquet(io.BytesIO(data))
```

Remove the old `_cache_data()` and `_get_cached_data()` methods.

### 4. Eviction methods

```python
def evict(self, name: str) -> str:
    """Release materialized DataFrame from memory. Source and schema are retained."""
    entry = self._datasets.get(name)
    if entry is None:
        return f"Dataset '{name}' not found."
    entry.evict()
    return f"Dataset '{name}' evicted from memory."

def evict_all(self) -> str:
    """Release all materialized DataFrames."""
    count = sum(1 for e in self._datasets.values() if e.loaded)
    for entry in self._datasets.values():
        entry.evict()
    return f"Evicted {count} datasets from memory."

def evict_unactive(self) -> str:
    """Release inactive entries only."""
    count = 0
    for entry in self._datasets.values():
        if not entry.is_active and entry.loaded:
            entry.evict()
            count += 1
    return f"Evicted {count} inactive datasets from memory."
```

### 5. New LLM-exposed tools

#### `fetch_dataset(name, sql=None, conditions=None, force_refresh=False)`

```python
@tool
async def fetch_dataset(
    self,
    name: str,
    sql: Optional[str] = None,
    conditions: Optional[Dict[str, Any]] = None,
    force_refresh: bool = False,
) -> str:
    """
    Materialize a dataset by fetching data from its source.

    For TableSource: 'sql' is required — provide the SQL to execute.
    For SQLQuerySource: 'conditions' injects {param} values.
    For QuerySlugSource: no extra params needed.
    Returns: confirmation with shape and any NaN warnings.
    """
```

#### `evict_dataset(name)`

```python
@tool
async def evict_dataset(self, name: str) -> str:
    """Release a materialized dataset from memory. Source and schema are retained."""
```

#### `get_source_schema(name)`

```python
@tool
async def get_source_schema(self, name: str) -> str:
    """
    Return the schema (column→type) for a source.

    For TableSource: available before materialization.
    For others: requires a prior fetch_dataset call.
    """
```

### 6. Updated LLM guide

Update `_generate_dataframe_guide()` to render mixed-state entries:

```
### finance_visits [TABLE — not loaded]
Source: troc.finance_visits_details via BigQuery
Columns (from schema):
  - visit_date (DATE)
  - visits (INT64)
  - revenue (FLOAT64)

To use: fetch_dataset("finance_visits", sql="<your SQL using the columns above>")

---

### daily_report [QUERY SLUG — not loaded]
Source: QuerySource slug 'troc_finance_visits_details'
Columns: unknown until fetched

To use: fetch_dataset("daily_report")

---

### local_data [DATAFRAME — loaded]
Alias: df1
Shape: 1500 rows × 8 columns
...
```

**NOT in scope**: Source implementations (done in TASK-214 through TASK-217).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/dataset_manager/tool.py` | MODIFY | Full DatasetManager rewrite per scope above |

---

## Implementation Notes

- `pyarrow` with snappy compression is confirmed present in `pyproject.toml`.
- Keep `load_data()` as deprecated alias for `materialize()` to avoid breaking `PandasAgent`.
- The `await manager.setup()` async init pattern: add an empty `async def setup(self) -> None: pass` placeholder — can be extended later for deferred prefetch.
- `list_available()` and `get_metadata()` must call `entry.to_info()` which now returns schema for unloaded TableSources.

---

## Acceptance Criteria

- [ ] `add_table_source()` is async and calls `source.prefetch_schema()` on registration
- [ ] `add_sql_source()` is sync and registers without prefetch
- [ ] `add_dataframe()` wraps df in `InMemorySource` internally; unchanged public API
- [ ] `add_query()` wraps slug in `QuerySlugSource` internally; unchanged public API
- [ ] `materialize(name, **params, force_refresh=False)` with Redis Parquet cache flow
- [ ] Redis serialization uses `df.to_parquet(compression='snappy')` / `pd.read_parquet()`
- [ ] `evict(name)`, `evict_all()`, `evict_unactive()` implemented
- [ ] `fetch_dataset` LLM tool added with `sql`, `conditions`, `force_refresh` params
- [ ] `evict_dataset` LLM tool added
- [ ] `get_source_schema` LLM tool added
- [ ] `list_available()` and `get_metadata()` show schema for unloaded TableSources
- [ ] LLM guide renders TABLE / QUERY SLUG / SQL / DATAFRAME states with appropriate instructions
- [ ] Old `_call_qs()`, `_call_multiquery()`, `_cache_data()`, `_get_cached_data()` removed
- [ ] `load_data()` kept as deprecated alias for `materialize()`
- [ ] `pytest tests/tools/test_dataset_manager.py -v` passes (no regressions)

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/datasetmanager-datasources.spec.md` (Sections 4, 5, 6, 7, 8)
2. **Check dependencies** — verify TASK-213 through TASK-218 are in `sdd/tasks/completed/`
3. **Read** the full current `tool.py` to understand existing methods before modifying
4. **Update status** in `sdd/tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** following the scope above — most complex task, take care with each step
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-219-datasetmanager-core.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: Claude Sonnet 4.6
**Date**: 2026-03-07
**Notes**:
- `add_table_source()` (async) + `add_sql_source()` (sync) added.
- `materialize()` with Redis Parquet caching (`_cache_df`/`_get_cached_df`) implemented.
- `evict()`, `evict_all()`, `evict_unactive()` implemented.
- `fetch_dataset`, `evict_dataset`, `get_source_schema` LLM tools added.
- `_generate_dataframe_guide()` updated for mixed load states (TABLE/QUERY SLUG/SQL/DATAFRAME).
- `get_metadata()` updated to return schema for unloaded entries (TableSource).
- Old `_call_qs()`, `_call_multiquery()`, `_cache_data()`, `_get_cached_data()` removed by linter (clean refactor).
- `load_data()` kept as deprecated alias; fixed to respect `_query_loader` for test compat.
- All 63 tests pass; ruff clean.

**Deviations from spec**:
- `SQLQuerySource` doesn't support `credentials` param (only `dsn`); `add_sql_source()` signature adjusted accordingly.
- Linter (ruff) rewrote `load_data()` during editing; restored `_query_loader` support needed by tests.
