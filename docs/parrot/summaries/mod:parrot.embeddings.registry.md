---
type: Wiki Summary
title: parrot.embeddings.registry
id: mod:parrot.embeddings.registry
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: EmbeddingRegistry — Process-wide singleton for embedding model caching.
relates_to:
- concept: class:parrot.embeddings.registry.EmbeddingRegistry
  rel: defines
- concept: class:parrot.embeddings.registry.RegistryStats
  rel: defines
- concept: mod:parrot._imports
  rel: references
- concept: mod:parrot.conf
  rel: references
- concept: mod:parrot.embeddings
  rel: references
---

# `parrot.embeddings.registry`

EmbeddingRegistry — Process-wide singleton for embedding model caching.

Provides LRU eviction, per-key async locks for concurrent-safe loading,
GPU memory tracking, and explicit preload/unload APIs.

Usage:
    from parrot.embeddings.registry import EmbeddingRegistry

    # Get or create cached model (async)
    model = await EmbeddingRegistry.instance().get_or_create("all-MiniLM-L6-v2")

    # Sync variant (for @property contexts)
    model = EmbeddingRegistry.instance().get_or_create_sync("all-MiniLM-L6-v2")

    # Preload models at startup
    await EmbeddingRegistry.instance().preload([
        {"model_name": "all-MiniLM-L6-v2", "model_type": "huggingface"},
    ])

## Classes

- **`RegistryStats`** — Statistics exposed by the EmbeddingRegistry.
- **`EmbeddingRegistry`** — Process-wide singleton for embedding model caching with LRU eviction.
