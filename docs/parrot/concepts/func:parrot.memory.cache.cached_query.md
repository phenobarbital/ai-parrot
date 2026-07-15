---
type: Concept
title: cached_query()
id: func:parrot.memory.cache.cached_query
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Decorator to cache the result of async methods in classes
---

# cached_query

```python
def cached_query(query_type: str, ttl: Optional[int]=None) -> Callable[[Callable[P, asyncio.Future[T]]], Callable[P, asyncio.Future[T]]]
```

Decorator to cache the result of async methods in classes
that inherit from CacheMixin.

Usage:
```python
@cached_query("get_superiors", ttl=600)
def get_all_superiors(self, employee_oid: str):
    ...
```
