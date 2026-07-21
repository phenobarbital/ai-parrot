---
type: Wiki Summary
title: parrot.memory.episodic.embedding
id: mod:parrot.memory.episodic.embedding
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Embedding provider for episodic memory.
relates_to:
- concept: class:parrot.memory.episodic.embedding.EpisodeEmbeddingProvider
  rel: defines
- concept: mod:parrot._imports
  rel: references
- concept: mod:parrot.memory.episodic.models
  rel: references
---

# `parrot.memory.episodic.embedding`

Embedding provider for episodic memory.

Lazy-loads sentence-transformers on first use. Uses asyncio.to_thread()
for non-blocking embedding in async contexts.

## Classes

- **`EpisodeEmbeddingProvider`** — Lazy-loading sentence-transformers embedding provider.
