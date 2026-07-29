---
type: Wiki Entity
title: RedisVectorBackend
id: class:parrot.memory.episodic.backends.redis_vector.RedisVectorBackend
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Redis Stack (RediSearch) backend for episodic memory vector search.
---

# RedisVectorBackend

Defined in [`parrot.memory.episodic.backends.redis_vector`](../summaries/mod:parrot.memory.episodic.backends.redis_vector.md).

```python
class RedisVectorBackend
```

Redis Stack (RediSearch) backend for episodic memory vector search.

Stores episodes as Redis HASHes with a RediSearch index for
vector similarity (HNSW) and tag-based namespace filtering.

Requires Redis Stack with the RediSearch module enabled.
Use ``configure()`` to create the index before performing any operations.

Graceful degradation: all methods return empty results (or None) on
connection failure, logging a warning rather than raising.

Args:
    redis_url: Redis connection URL (e.g., ``redis://localhost:6379``).
    index_name: RediSearch index name. Default ``idx:episodes``.
    embedding_dim: Dimension of the embedding vectors. Default 384.
    hnsw_m: HNSW graph connectivity parameter. Default 16.
    hnsw_ef_construction: HNSW build-time search depth. Default 200.

Example:
    backend = RedisVectorBackend(redis_url="redis://localhost:6379")
    await backend.configure()
    await backend.store(episode)
    results = await backend.search_similar(embedding=[...], namespace_filter={...})
    await backend.cleanup()

## Methods

- `async def configure(self) -> None` — Connect to Redis and create the RediSearch index.
- `async def cleanup(self) -> None` — Close the Redis connection pool.
- `async def store(self, episode: EpisodicMemory) -> str` — Store an episode as a Redis HASH.
- `async def search_similar(self, embedding: list[float], namespace_filter: dict[str, Any], top_k: int=5, score_threshold: float=0.3, include_failures_only: bool=False) -> list[EpisodeSearchResult]` — Search episodes by KNN vector similarity with namespace pre-filtering.
- `async def get_recent(self, namespace_filter: dict[str, Any], limit: int=10, since: datetime | None=None) -> list[EpisodicMemory]` — Get recent episodes by namespace, ordered by created_at DESC.
- `async def get_failures(self, agent_id: str, tenant_id: str='default', limit: int=5) -> list[EpisodicMemory]` — Get recent failure episodes for an agent.
- `async def delete_expired(self) -> int` — Delete episodes that have passed their expires_at timestamp.
- `async def count(self, namespace_filter: dict[str, Any]) -> int` — Count episodes matching a namespace filter.
