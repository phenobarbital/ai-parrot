---
id: F002
query_id: Q013, Q014, Q024, Q030
type: read
intent: "DatasetEntry lifecycle (lazy fetch, caching, materialization) and how DatasetManager holds data at runtime; any DuckDB usage."
executed_at: 2026-11-11T22:12:00Z
duration_ms: 0
parent_id: null
depth: 0
lane_id: FC-002
---

# F002 — Data is held as in-memory pandas DataFrames, cached in Redis as Parquet; no DuckDB store

## Summary

`DatasetManager` keeps `self._datasets: Dict[str, DatasetEntry]`; each `DatasetEntry` owns one
`self._df: Optional[pd.DataFrame]` filled by `source.fetch(**params)` on first `materialize()` and
dropped by `evict()`. The manager-level `materialize()` adds a Redis layer (snappy Parquet bytes keyed
by `source.cache_key`) that is skipped when `source.has_builtin_cache` or `entry.no_cache`. There is no
DuckDB-backed storage of datasets: every `duckdb` hit inside the package is either a dialect-map entry
or the Delta/Iceberg sources, which use DuckDB only as the *query engine* of that remote table.

## Citations

- path: `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py`
  lines: 337-365
  symbol: `DatasetEntry.materialize`
  excerpt: |
    async def materialize(self, force: bool = False, **params) -> pd.DataFrame:
        if self._df is None or force:
            self._df = await self.source.fetch(**params)
            if self._df is not None and self._computed_columns:
                self._apply_computed_columns()
            if self.auto_detect_types and self._df is not None:
                self._column_types = DatasetManager.categorize_columns(self._df)
        return self._df
    def evict(self) -> None:
        self._df = None

- path: `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py`
  lines: 633-660
  symbol: `DatasetManager.__init__`
  excerpt: |
    def __init__(self, df_prefix="df", generate_guide=True, include_summary_stats=False,
                 auto_detect_types=True, policy_guard=None, dataplane_guard=None, usage_rules=None, **kwargs):
        self._datasets: Dict[str, DatasetEntry] = {}
        self._redis: Optional[aioredis.Redis] = None
        self._policy_guard = policy_guard
        self._dataplane_guard = dataplane_guard

- path: `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py`
  lines: 4270-4335
  symbol: `DatasetManager.materialize`
  excerpt: |
    if entry.loaded and not force_refresh:
        return entry._df
    if entry.source.has_builtin_cache:
        df = await entry.materialize(force=True, force_refresh=force_refresh, **params)
        return df
    if not force_refresh and not entry.no_cache:
        cached = await self._get_cached_df(entry.source)
    df = await entry.materialize(force=True, **params)
    if not entry.no_cache:
        await self._cache_df(entry.source, df, entry.cache_ttl)

- path: `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py`
  lines: 4244-4263
  symbol: `DatasetManager._cache_df`
  excerpt: |
    df.to_parquet(buf, index=False, compression="snappy")
    ...
    return pd.read_parquet(io.BytesIO(data))

- path: `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py`
  lines: 613-631
  symbol: `DatasetManager.DEFAULT_USAGE_RULES`
  excerpt: |
    "1. **Loaded DataFrames are ready now.** Datasets shown as *loaded* already "
    "exist in the `python_repl_pandas` environment under their name and `dfN` alias ..."
    "2. **Aggregate tables in SQL, not pandas.** For a count / sum / ranking / "
    "filter over an *unloaded* table, call `fetch_dataset` with a SQL query ..."

- path: `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/deltatable.py`
  lines: 241-249
  symbol: `DeltaTableSource.fetch`
  excerpt: |
    1. ``sql`` — DuckDB SQL query via ``conn.query(sentence=sql, tablename=...)``

- path: `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/dialects.py`
  lines: 23-38
  symbol: `_DRIVER_DIALECT_MAP`
  excerpt: |
    "pg": "postgres", "mysql": "mysql", "bigquery": "bigquery", "mssql": "tsql", ...
    "duckdb": "duckdb", "sqlite": "sqlite", ...

## Notes

- `grep -i duckdb` over `dataset_manager/` returned 15 hits in 4 files (`deltatable.py`, `iceberg.py`,
  `dialects.py`, `tool.py` docstrings at 1963 and 2304). None stores a fetched DataFrame in DuckDB.
- Runtime accessors that read `_df` directly: `get_active_dataframes` (tool.py:2417),
  `get_active_dataframes_lazy` (2421), `get_dataframe` (3287), `fetch_dataset` (3415), `evict_dataset`
  (3836), `evict` (4339), `evict_all` (4358), `evict_table_sources` (4369), `evict_unactive` (4395).
  A DuckDB-backed store would have to sit behind all of them, and behind the pandas REPL hand-over
  described in `DEFAULT_USAGE_RULES` (datasets appear as `dfN` variables in a worker process).
- The Redis cache key is `source.cache_key` only — no user or subject component. A source whose rows
  depend on the caller (RLS, masks) must not use this layer as-is: either `has_builtin_cache = True`
  /`no_cache`, or a subject-scoped key.
- `tool.py` is 229 KB / 5360 lines; `DatasetManager` spans L582-5360.
- [cross-lane: type=wiki_query, intent=is there a design note on replacing in-memory DataFrames with a DuckDB store (FEAT-713 constraints)?]
