---
type: Wiki Summary
title: parrot.memory.episodic.backends.redis_vector
id: mod:parrot.memory.episodic.backends.redis_vector
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Redis Stack (RediSearch) vector backend for episodic memory.
relates_to:
- concept: class:parrot.memory.episodic.backends.redis_vector.RedisVectorBackend
  rel: defines
- concept: mod:parrot.memory.episodic.models
  rel: references
---

# `parrot.memory.episodic.backends.redis_vector`

Redis Stack (RediSearch) vector backend for episodic memory.

Implements AbstractEpisodeBackend using Redis Stack with HNSW vector index
and RediSearch FT.SEARCH for namespace-filtered vector similarity search.

Requires Redis Stack with the RediSearch module installed.

## Classes

- **`RedisVectorBackend`** — Redis Stack (RediSearch) backend for episodic memory vector search.
