---
type: Wiki Entity
title: SchemaMetadataCache
id: class:parrot.bots.database.cache.SchemaMetadataCache
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Backward-compatible wrapper around ``CachePartition``.
relates_to:
- concept: class:parrot.bots.database.cache.CachePartition
  rel: extends
---

# SchemaMetadataCache

Defined in [`parrot.bots.database.cache`](../summaries/mod:parrot.bots.database.cache.md).

```python
class SchemaMetadataCache(CachePartition)
```

Backward-compatible wrapper around ``CachePartition``.

Preserves the old constructor signature::

    SchemaMetadataCache(vector_store=None, lru_maxsize=500, lru_ttl=1800)

so that existing code (e.g. ``abstract.py``) continues to work until the
cleanup task (TASK-579) removes it.
