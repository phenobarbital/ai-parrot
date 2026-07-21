---
type: Wiki Entity
title: QuerySlugSource
id: class:parrot.tools.dataset_manager.sources.query_slug.QuerySlugSource
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: DataSource backed by a single QuerySource slug.
relates_to:
- concept: class:parrot.tools.dataset_manager.sources.base.DataSource
  rel: extends
---

# QuerySlugSource

Defined in [`parrot.tools.dataset_manager.sources.query_slug`](../summaries/mod:parrot.tools.dataset_manager.sources.query_slug.md).

```python
class QuerySlugSource(DataSource)
```

DataSource backed by a single QuerySource slug.

Wraps QS(slug=..., conditions=params) and exposes it as a lazy DataSource.
Schema prefetch performs a 1-row query to infer column names and dtypes.

Args:
    slug: The QuerySource slug identifier.
    prefetch_schema_enabled: When True, prefetch_schema() will call QS with
        querylimit=1 to infer the schema. Defaults to True.
    permanent_filter: Optional dict of conditions that are always merged
        into every fetch() call. Permanent filter keys take precedence
        over runtime params (cannot be overridden by the caller).

## Methods

- `def has_builtin_cache(self) -> bool`
- `def cache_key(self) -> str` — Stable Redis cache key for this source.
- `def describe(self) -> str` — Human-readable description for the LLM.
- `async def prefetch_schema(self) -> Dict[str, str]` — Fetch one row to infer column names and dtypes.
- `async def fetch(self, **params) -> pd.DataFrame` — Execute the QuerySource and return a DataFrame.
