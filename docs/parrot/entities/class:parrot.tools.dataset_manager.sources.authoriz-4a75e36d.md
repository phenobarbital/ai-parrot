---
type: Wiki Entity
title: AuthorizingDataSource
id: class:parrot.tools.dataset_manager.sources.authorizing.AuthorizingDataSource
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Decorator that wraps a DataSource with authorization + RLS enforcement.
relates_to:
- concept: class:parrot.tools.dataset_manager.sources.base.DataSource
  rel: extends
---

# AuthorizingDataSource

Defined in [`parrot.tools.dataset_manager.sources.authorizing`](../summaries/mod:parrot.tools.dataset_manager.sources.authorizing.md).

```python
class AuthorizingDataSource(DataSource)
```

Decorator that wraps a DataSource with authorization + RLS enforcement.

The ``fetch()`` method runs the full enforcement chain before delegating
to the inner source's ``fetch()``.  All other :class:`DataSource`
properties are transparently delegated.

Args:
    inner: The wrapped :class:`DataSource` instance.
    guard: :class:`~parrot.auth.dataplane_guard.DataPlanePolicyGuard`
        that performs PBAC evaluation and RLS predicate collection.
    pctx_provider: Callable with no arguments that returns the current
        :class:`~parrot.auth.permission.PermissionContext` (typically
        ``lambda: _pctx_var.get(None)``).  Called at ``fetch()`` time
        so the context is fresh for each invocation.

## Methods

- `async def fetch(self, **params) -> pd.DataFrame` — Run the enforcement chain then delegate to inner.fetch().
- `def describe(self) -> str` — Delegate to inner source.
- `def has_builtin_cache(self) -> bool` — Delegate to inner source.
- `def cache_key(self) -> str` — Delegate to inner source.
- `async def prefetch_schema(self)` — Delegate schema prefetch to inner source.
