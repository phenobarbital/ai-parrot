---
type: Wiki Entity
title: DatasetEntry
id: class:parrot.tools.dataset_manager.tool.DatasetEntry
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Lifecycle wrapper around a DataSource.
---

# DatasetEntry

Defined in [`parrot.tools.dataset_manager.tool`](../summaries/mod:parrot.tools.dataset_manager.tool.md).

```python
class DatasetEntry
```

Lifecycle wrapper around a DataSource.

Knows WHETHER data is in memory and manages its lifecycle:
- materialize(**params): fetch from source, cache result in _df
- evict(): release _df from memory (source reference and schema are retained)

Provides backward-compatible properties (df, query_slug, _column_metadata)
so existing DatasetManager methods continue to work without changes.

Computed columns (``computed_columns``) are applied post-materialization
and before type categorization, so they appear as regular columns
throughout the DatasetManager API.

## Methods

- `async def materialize(self, force: bool=False, **params) -> pd.DataFrame` — Fetch data from source if not already loaded (or if force=True).
- `def evict(self) -> None` — Release DataFrame from memory.
- `def loaded(self) -> bool` — True if data has been materialized into memory.
- `def shape(self) -> Tuple[int, int]` — Shape of the loaded DataFrame, or (0, 0) if not loaded.
- `def columns(self) -> List[str]` — Column names. Falls back to source schema (TableSource) when not loaded.
- `def memory_usage_mb(self) -> float` — Memory usage of the loaded DataFrame in MB.
- `def null_count(self) -> int` — Total null count across all columns.
- `def column_types(self) -> Optional[Dict[str, str]]` — Semantic column types (populated after materialization).
- `def df(self) -> Optional[pd.DataFrame]` — Backward-compat: return the loaded DataFrame (same as _df).
- `def df(self, value: Optional[pd.DataFrame]) -> None` — Backward-compat setter used by _load_query and legacy code paths.
- `def query_slug(self) -> Optional[str]` — Backward-compat: return slug if source is a QuerySlugSource.
- `def to_info(self, alias: Optional[str]=None) -> DatasetInfo` — Serialize this entry to a DatasetInfo Pydantic model.
