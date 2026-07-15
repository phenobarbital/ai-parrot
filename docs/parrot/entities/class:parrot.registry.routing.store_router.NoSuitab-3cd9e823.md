---
type: Wiki Entity
title: NoSuitableStoreError
id: class:parrot.registry.routing.store_router.NoSuitableStoreError
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Raised by ``StoreRouter.execute`` when ``fallback_policy=RAISE``
---

# NoSuitableStoreError

Defined in [`parrot.registry.routing.store_router`](../summaries/mod:parrot.registry.routing.store_router.md).

```python
class NoSuitableStoreError(RuntimeError)
```

Raised by ``StoreRouter.execute`` when ``fallback_policy=RAISE``
and no store scored above the confidence floor.
