---
type: Wiki Summary
title: parrot.memory.episodic.store
id: mod:parrot.memory.episodic.store
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: EpisodicMemoryStore — main orchestrator for episodic memory.
relates_to:
- concept: class:parrot.memory.episodic.store.EpisodicMemoryStore
  rel: defines
- concept: mod:parrot.memory.episodic.backends.abstract
  rel: references
- concept: mod:parrot.memory.episodic.backends.faiss
  rel: references
- concept: mod:parrot.memory.episodic.backends.pgvector
  rel: references
- concept: mod:parrot.memory.episodic.backends.redis_vector
  rel: references
- concept: mod:parrot.memory.episodic.cache
  rel: references
- concept: mod:parrot.memory.episodic.embedding
  rel: references
- concept: mod:parrot.memory.episodic.models
  rel: references
- concept: mod:parrot.memory.episodic.recall
  rel: references
- concept: mod:parrot.memory.episodic.reflection
  rel: references
- concept: mod:parrot.memory.episodic.scoring
  rel: references
---

# `parrot.memory.episodic.store`

EpisodicMemoryStore — main orchestrator for episodic memory.

Coordinates backend storage, embedding, reflection, and caching to provide
a unified API for recording, recalling, and maintaining agent episodes.

## Classes

- **`EpisodicMemoryStore`** — Main orchestrator for episodic memory operations.
