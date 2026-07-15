---
type: Wiki Entity
title: MultiQuerySlugSource
id: class:parrot.tools.dataset_manager.sources.query_slug.MultiQuerySlugSource
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: DataSource backed by multiple QuerySource slugs whose results are merged.
relates_to:
- concept: class:parrot.tools.dataset_manager.sources.base.DataSource
  rel: extends
---

# MultiQuerySlugSource

Defined in [`parrot.tools.dataset_manager.sources.query_slug`](../summaries/mod:parrot.tools.dataset_manager.sources.query_slug.md).

```python
class MultiQuerySlugSource(DataSource)
```

DataSource backed by multiple QuerySource slugs whose results are merged.

Fetches each slug independently and concatenates the resulting DataFrames.
Schema prefetch performs a 1-row fetch per slug and merges the schema dicts.

Args:
    slugs: List of QuerySource slug identifiers to merge.

## Methods

- `def has_builtin_cache(self) -> bool`
- `def cache_key(self) -> str` — Stable Redis cache key for this multi-slug source.
- `def describe(self) -> str` — Human-readable description for the LLM.
- `async def prefetch_schema(self) -> Dict[str, str]` — Fetch one row per slug and merge the inferred schemas.
- `async def fetch(self, **params) -> pd.DataFrame` — Execute all slugs and concatenate the resulting DataFrames.
