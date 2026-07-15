---
type: Wiki Summary
title: parrot.bots.database.cache
id: mod:parrot.bots.database.cache
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Multi-database cache with partitioned namespaces.
relates_to:
- concept: class:parrot.bots.database.cache.CacheManager
  rel: defines
- concept: class:parrot.bots.database.cache.CachePartition
  rel: defines
- concept: class:parrot.bots.database.cache.CachePartitionConfig
  rel: defines
- concept: class:parrot.bots.database.cache.SchemaMetadataCache
  rel: defines
- concept: mod:parrot.bots.database.models
  rel: references
- concept: mod:parrot.stores.abstract
  rel: references
---

# `parrot.bots.database.cache`

Multi-database cache with partitioned namespaces.

Replaces the monolithic ``SchemaMetadataCache`` with a ``CacheManager`` that
creates ``CachePartition`` instances per database.  Each partition has its own
LRU sizing and TTL while optionally sharing a Redis connection pool and a
vector store for similarity search.

## Classes

- **`CachePartitionConfig(BaseModel)`** — Configuration for a single cache partition.
- **`CachePartition`** — Namespaced cache partition with the same API as ``SchemaMetadataCache``.
- **`SchemaMetadataCache(CachePartition)`** — Backward-compatible wrapper around ``CachePartition``.
- **`CacheManager`** — Manages namespaced cache partitions with shared Redis + vector store.
