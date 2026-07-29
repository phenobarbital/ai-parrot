---
type: Wiki Entity
title: SemanticVectorCache
id: class:parrot.stores.cache.SemanticVectorCache
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: A class to handle caching of semantic vectors using Redis.
---

# SemanticVectorCache

Defined in [`parrot.stores.cache`](../summaries/mod:parrot.stores.cache.md).

```python
class SemanticVectorCache
```

A class to handle caching of semantic vectors using Redis.
It allows storing and retrieving semantically similar query results
based on cosine similarity of embeddings.
It uses Redis for storage and retrieval, with a configurable similarity threshold.

## Methods

- `async def get_similar_cached_results(self, query_embedding: np.ndarray, top_k: int=10) -> Optional[List[Dict]]` — Search for semantically similar cached queries
- `async def cache_search_results(self, query_embedding: np.ndarray, results: List[Dict], ttl: int=1800)` — Cache search results with semantic indexing
