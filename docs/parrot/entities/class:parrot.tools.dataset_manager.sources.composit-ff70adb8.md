---
type: Wiki Entity
title: CompositeDataSource
id: class:parrot.tools.dataset_manager.sources.composite.CompositeDataSource
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Virtual DataSource that JOINs existing datasets on demand.
relates_to:
- concept: class:parrot.tools.dataset_manager.sources.base.DataSource
  rel: extends
---

# CompositeDataSource

Defined in [`parrot.tools.dataset_manager.sources.composite`](../summaries/mod:parrot.tools.dataset_manager.sources.composite.md).

```python
class CompositeDataSource(DataSource)
```

Virtual DataSource that JOINs existing datasets on demand.

Components are fetched independently and JOINed sequentially using
``pd.merge()``.  Per-component filters are applied before each JOIN:
a filter key is only forwarded to a component if that component has
a column with that name.

Attributes:
    name: Name of this composite dataset (used for logging and cache_key).
    joins: Ordered list of ``JoinSpec`` objects describing the JOINs.
    _dm: Back-reference to the owning ``DatasetManager`` (runtime only,
        not type-checked at import to avoid circular imports).
    description: Optional human-readable description.

## Methods

- `def component_names(self) -> List[str]` — All unique dataset names referenced by the join specs (insertion order).
- `async def prefetch_schema(self) -> Dict[str, str]` — Return a merged schema from all component schemas.
- `async def fetch(self, filters: Optional[Dict[str, Any]]=None, **params: Any) -> pd.DataFrame` — Materialize all components, apply per-component filters, then JOIN.
- `def describe(self) -> str` — Return a human-readable join description for the LLM guide.
- `def has_builtin_cache(self) -> bool` — Always True — DatasetManager skips Redis for the composite result.
- `def cache_key(self) -> str` — Stable cache key derived from the composite name.
