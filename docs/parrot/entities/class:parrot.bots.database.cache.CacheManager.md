---
type: Wiki Entity
title: CacheManager
id: class:parrot.bots.database.cache.CacheManager
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Manages namespaced cache partitions with shared Redis + vector store.
---

# CacheManager

Defined in [`parrot.bots.database.cache`](../summaries/mod:parrot.bots.database.cache.md).

```python
class CacheManager
```

Manages namespaced cache partitions with shared Redis + vector store.

Args:
    redis_url: Optional Redis connection string.  ``None`` for LRU-only mode.
    vector_store: Optional ``AbstractStore`` for similarity search.
    owns_vector_store: When ``True`` (default) :meth:`close` disposes the
        ``vector_store`` (releasing its connection pool / SQLAlchemy engine).
        Set to ``False`` when the store is shared and its lifecycle is
        managed elsewhere.

## Methods

- `def create_partition(self, config: CachePartitionConfig) -> CachePartition` — Create a new cache partition with the given configuration.
- `def get_partition(self, namespace: str) -> Optional[CachePartition]` — Return the partition for *namespace*, or ``None``.
- `async def search_across_databases(self, query: str, limit: int=5) -> List[TableMetadata]` — Search for tables across all partitions.
- `async def close(self) -> None` — Close shared resources (Redis pool + owned vector store).
