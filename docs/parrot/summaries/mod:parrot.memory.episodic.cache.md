---
type: Wiki Summary
title: parrot.memory.episodic.cache
id: mod:parrot.memory.episodic.cache
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Redis hot cache for episodic memory.
relates_to:
- concept: class:parrot.memory.episodic.cache.EpisodeRedisCache
  rel: defines
- concept: mod:parrot.memory.episodic.models
  rel: references
---

# `parrot.memory.episodic.cache`

Redis hot cache for episodic memory.

Caches recent episodes and failures per namespace using Redis data structures:
- ZSET (sorted by timestamp) for recent episodes.
- HASH for full episode data.
- LIST for failure episode IDs.

All operations degrade gracefully when Redis is unavailable.

## Classes

- **`EpisodeRedisCache`** — Redis-based hot cache for episodic memory.
