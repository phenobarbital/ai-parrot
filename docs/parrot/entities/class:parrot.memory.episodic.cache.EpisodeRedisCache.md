---
type: Wiki Entity
title: EpisodeRedisCache
id: class:parrot.memory.episodic.cache.EpisodeRedisCache
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Redis-based hot cache for episodic memory.
---

# EpisodeRedisCache

Defined in [`parrot.memory.episodic.cache`](../summaries/mod:parrot.memory.episodic.cache.md).

```python
class EpisodeRedisCache
```

Redis-based hot cache for episodic memory.

Stores recent episodes per namespace for fast access without
hitting the backend. All methods return None on Redis errors,
allowing the caller to fall back to the backend transparently.

Args:
    redis_client: An async Redis client (redis.asyncio.Redis).
    default_ttl: TTL in seconds for cached data (default: 1 hour).
    max_recent: Maximum recent episodes per namespace in the ZSET.
    key_prefix: Base prefix for all Redis keys.

## Methods

- `async def cache_episode(self, namespace: MemoryNamespace, episode: EpisodicMemory) -> None` — Cache an episode in Redis.
- `async def get_recent(self, namespace: MemoryNamespace, limit: int=10) -> list[EpisodicMemory] | None` — Get recent episodes from the cache.
- `async def get_failures(self, namespace: MemoryNamespace, limit: int=5) -> list[EpisodicMemory] | None` — Get cached failure episodes.
- `async def get_episode(self, namespace: MemoryNamespace, episode_id: str) -> EpisodicMemory | None` — Get a single cached episode.
- `async def invalidate(self, namespace: MemoryNamespace) -> None` — Invalidate all cached data for a namespace.
