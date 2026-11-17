---
id: F013
query_id: Q001
type: wiki_page
intent: "Orient: DatasetManager lazy data sources design and spec (Q001 + Q002 + Q003)."
executed_at: 2026-11-11T22:20:00Z
duration_ms: 0
parent_id: null
depth: 0
lane_id: FW-001
---

# F013 — The designed source contract is a 4-member `DataSource` ABC; DatasetManager owns lifecycle and a Parquet/Redis cache keyed by the source

## Summary

The lazy-sources spec makes `DataSource` the only extension point: `prefetch_schema()` (cheap, no rows),
`fetch(**params) -> pd.DataFrame`, `describe()` and a `cache_key` property. `DatasetEntry` is a thin
lifecycle wrapper (`_df` is `None` until materialized) and `DatasetManager` holds no source-specific
logic — a new source kind is "one `DataSource` subclass + one `add_*` registration method". Materialized
data is a pandas DataFrame held in the entry and cached in Redis as Parquet under
`dataset:{source.cache_key}`; the key is owned by the source, **not** by the agent, so identical sources
share a cache entry across agents. `SQLQuerySource.cache_key` is `sql:{driver}:{md5(sql)[:8]}`. Each
source carries its own `credentials`, defaulting to the driver's default-credentials helper.

## Citations

- wiki: `file:sdd/specs/datasetmanager-datasources.spec.md` (Q001 score=0.90)

- path: `sdd/specs/datasetmanager-datasources.spec.md`
  lines: 89-108
  symbol: `DataSource`
  excerpt: |
    class DataSource(ABC):
        async def prefetch_schema(self) -> Dict[str, str]:
        async def fetch(self, **params) -> pd.DataFrame:
        def cache_key(self) -> str:

- path: `sdd/specs/datasetmanager-datasources.spec.md`
  lines: 129-135
  symbol: `SQLQuerySource`
  excerpt: |
    #### `SQLQuerySource`
    - `cache_key`: `sql:{driver}:{md5(sql)[:8]}`

- path: `sdd/specs/datasetmanager-datasources.spec.md`
  lines: 148
  symbol: `DatasetEntry`
  excerpt: |
    _df: Optional[pd.DataFrame]    # None = not materialized

- path: `sdd/specs/datasetmanager-datasources.spec.md`
  lines: 183-204
  symbol: `Credential Resolution / Caching`
  excerpt: |
    ├─► check Redis: key = "dataset:{source.cache_key}"
    Cache serialization: **Parquet** (`df.to_parquet()` / `pd.read_parquet()`) via `io.BytesIO`.
    `force_refresh=True` bypasses Redis, re-fetches, and overwrites the cache entry.
- wiki: `file:wiki/tools/datasetmanager_design.md` (Q002; score=0.22 on the DuckDB query)

- path: `wiki/tools/datasetmanager_design.md`
  lines: 1-20
  symbol: `DatasetManager Implementation Walkthrough`
  excerpt: |
    Implemented a `DatasetManager` class that acts as a data catalog and toolkit for `PandasAgent`

## Notes

- `wiki/tools/datasetmanager_design.md` is an **old session walkthrough** (pre-subpackage: paths
  `parrot/tools/dataset_manager.py`, tools `get_dataframe` / `store_dataframe`, guide generation). It
  says nothing about sources, caching or storage — do not treat it as the current design.
- Later source specs follow the same pattern (wiki hits: `sdd/specs/datasetmanager-sources.spec.md`
  for Iceberg/Mongo/DeltaTable; `sdd/specs/composite-datasets.spec.md` exists on disk).
- Nothing in the spec gives a source a per-subject cache key: a semantic source whose rows depend on
  the caller's RLS/masks cannot reuse a source-owned, cross-agent shared key as-is.
- [cross-lane: type=read, intent=confirm the current DataSource ABC in sources/base.py still matches this 4-member contract and how tool.py builds the Redis key today (any subject/tenant component)]
