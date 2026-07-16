---
type: Wiki Entity
title: EmbeddingRegistry
id: class:parrot.embeddings.registry.EmbeddingRegistry
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Process-wide singleton for embedding model caching with LRU eviction.
---

# EmbeddingRegistry

Defined in [`parrot.embeddings.registry`](../summaries/mod:parrot.embeddings.registry.md).

```python
class EmbeddingRegistry
```

Process-wide singleton for embedding model caching with LRU eviction.

Caches instances by ``(model_name, model_type)`` key.  Multiple
bots/stores/KBs sharing the same model name reuse a single instance.

Eviction is LRU (Least Recently Used) and triggers when the cache
exceeds ``max_models``.  Eviction calls ``model.free()`` and logs a
warning so operators can tune ``max_models``.

Thread-safety:
    - Singleton creation is protected by a ``threading.Lock``.
    - Async concurrent first-access for the *same* key is serialised
      by a per-key ``asyncio.Lock``.  Different keys do NOT block each
      other.
    - The sync variant (``get_or_create_sync``) uses a ``threading.Lock``
      and NEVER calls ``asyncio.run()`` — safe to call from within a
      running event loop.

## Methods

- `def instance(cls, max_models: int=None) -> 'EmbeddingRegistry'` — Get or create the process-wide singleton.
- `async def get_or_create(self, model_name: str, model_type: str='huggingface', **kwargs) -> Any` — Get a cached model or create and cache it on first access.
- `async def preload(self, models: List[Dict[str, str]]) -> None` — Eagerly load a list of models into the registry cache.
- `async def unload(self, model_name: str, model_type: str='huggingface') -> bool` — Remove a model from the cache and free its resources.
- `def get_or_create_sync(self, model_name: str, model_type: str='huggingface', **kwargs) -> Any` — Sync variant of ``get_or_create`` for non-async contexts.
- `def loaded_models(self) -> List[CacheKey]` — Return the list of currently cached ``(model_name, model_type)`` keys.
- `def stats(self) -> RegistryStats` — Return a snapshot of cache statistics.
- `def clear(self) -> None` — Remove all cached models and free their GPU resources.
