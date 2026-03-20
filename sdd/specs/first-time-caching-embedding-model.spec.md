# Feature Specification: First-Time Caching Embedding Model

**Feature ID**: FEAT-054
**Date**: 2026-03-20
**Author**: Jesus Lara
**Status**: approved
**Target version**: next
**Brainstorm**: `sdd/proposals/first-time-caching-embedding-model.brainstorm.md`

---

## 1. Motivation & Business Requirements

### Problem Statement

Embedding models in AI-Parrot are **re-created on each access** instead of being cached after first load. This causes three concrete problems:

1. **Per-bot duplication**: Each bot creates its own `EmbeddingModel` instance even when using the same `model_name`. On GPU, this wastes VRAM linearly with bot count.
2. **KnowledgeBaseStore eager loading**: `KnowledgeBaseStore.__init__` instantiates `SentenceTransformer` immediately on construction, adding 5-30s startup latency even if KB is never queried.
3. **No process-wide deduplication**: `AbstractStore.create_embedding()` creates a new instance every time — there is no shared cache keyed by `(model_name, model_type)`.

The result: unnecessary GPU/CPU memory usage, unpredictable first-query latency, and no operational control over which models are loaded.

### Goals

- **G1**: Embedding models are loaded once on first use and cached in memory for the process lifetime (or until evicted).
- **G2**: Multiple bots/stores/KBs sharing the same model name reuse a single instance.
- **G3**: LRU eviction with configurable `max_models` (default: 10) prevents unbounded GPU memory growth, with GPU memory tracking via `torch.cuda.memory_allocated`.
- **G4**: Explicit `preload()` and `unload()` APIs for operational control.
- **G5**: Eviction logs a warning so ops can tune `max_models`.
- **G6**: Standalone utility importable as `from parrot.embeddings import EmbeddingRegistry`.
- **G7**: Queue-and-wait semantics — first request awaits model load (async, non-blocking to event loop), subsequent requests are instant.

### Non-Goals (explicitly out of scope)

- Cross-process model sharing (Redis, shared memory, mmap) — single-process async framework.
- Automatic model downloading or version management — models are assumed available locally or via HuggingFace cache.
- Changing the `EmbeddingModel` abstract interface — only adding registry integration.
- Model quantization or optimization — orthogonal concern.

---

## 2. Architectural Design

### Overview

A process-wide **`EmbeddingRegistry`** singleton manages the lifecycle of all embedding models. It caches instances by `(model_name, model_type)`, ensures async-safe concurrent access with per-key locks, and provides LRU eviction when the cache exceeds `max_models`.

All existing embedding consumers (`AbstractStore`, `KnowledgeBaseStore`, `AbstractBot.warmup_embeddings`) are refactored to delegate to the registry instead of creating instances directly.

### Component Diagram

```
                          ┌──────────────────────┐
                          │   EmbeddingRegistry   │  (singleton)
                          │                       │
                          │  cache: OrderedDict   │
                          │  locks: per-key async │
                          │  max_models: 10       │
                          │  gpu_tracker           │
                          └──────┬────────────────┘
                                 │
              ┌──────────────────┼──────────────────┐
              │                  │                   │
              ▼                  ▼                   ▼
     ┌─────────────┐   ┌──────────────┐   ┌──────────────────┐
     │ AbstractStore│   │KnowledgeBase │   │  AbstractBot      │
     │  .create_    │   │  Store       │   │  .warmup_         │
     │  embedding() │   │  .__init__() │   │  embeddings()     │
     └─────────────┘   └──────────────┘   └──────────────────┘
              │                  │                   │
              └──────────────────┼──────────────────┘
                                 │
              ┌──────────────────┼──────────────────┐
              │                  │                   │
              ▼                  ▼                   ▼
     ┌─────────────┐   ┌──────────────┐   ┌──────────────────┐
     │ HuggingFace  │   │   OpenAI     │   │    Google         │
     │ Embedding    │   │  Embedding   │   │   Embedding       │
     └─────────────┘   └──────────────┘   └──────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot/embeddings/base.py` | modifies | `model` property delegates to registry |
| `parrot/embeddings/__init__.py` | extends | Exports `EmbeddingRegistry` |
| `parrot/stores/abstract.py` | modifies | `create_embedding()` calls `registry.get_or_create()` |
| `parrot/stores/kb/store.py` | modifies | `__init__` uses registry instead of direct `SentenceTransformer()` |
| `parrot/bots/abstract.py` | modifies | `warmup_embeddings()` delegates to `registry.preload()` |
| `parrot/conf.py` | extends | Adds `EMBEDDING_REGISTRY_MAX_MODELS` setting |

### Data Models

```python
from typing import Tuple, Optional, Dict
from collections import OrderedDict

CacheKey = Tuple[str, str]  # (model_name, model_type)

class RegistryStats:
    """Statistics exposed by the registry."""
    loaded_models: int
    cache_hits: int
    cache_misses: int
    evictions: int
    gpu_memory_mb: Optional[float]
```

### New Public Interfaces

```python
class EmbeddingRegistry:
    """Process-wide singleton for embedding model caching."""

    @classmethod
    def instance(cls, max_models: int = None) -> "EmbeddingRegistry":
        """Get or create the singleton instance."""
        ...

    async def get_or_create(
        self,
        model_name: str,
        model_type: str = "huggingface",
        **kwargs
    ) -> EmbeddingModel:
        """Get cached model or create+cache on first access.
        Async-safe: concurrent calls for the same key await one load.
        """
        ...

    def get_or_create_sync(
        self,
        model_name: str,
        model_type: str = "huggingface",
        **kwargs
    ) -> EmbeddingModel:
        """Sync variant for non-async contexts (e.g., @property)."""
        ...

    async def preload(
        self,
        models: list[dict]
    ) -> None:
        """Eagerly load a list of models into cache.
        Each dict: {'model_name': ..., 'model_type': ...}
        """
        ...

    async def unload(
        self,
        model_name: str,
        model_type: str = "huggingface"
    ) -> bool:
        """Remove a model from cache and free GPU memory."""
        ...

    def loaded_models(self) -> list[CacheKey]:
        """Return list of currently cached (model_name, model_type) keys."""
        ...

    def stats(self) -> RegistryStats:
        """Return cache statistics."""
        ...

    def clear(self) -> None:
        """Remove all cached models. For testing."""
        ...
```

---

## 3. Module Breakdown

### Module 1: EmbeddingRegistry Core

- **Path**: `parrot/embeddings/registry.py`
- **Responsibility**: Singleton registry with `OrderedDict` cache, per-key `asyncio.Lock`, LRU eviction, GPU memory tracking, `preload()`/`unload()`/`clear()` APIs, `RegistryStats`.
- **Depends on**: `parrot/embeddings/base.py` (EmbeddingModel), `parrot/embeddings/__init__.py` (supported_embeddings), `parrot/conf.py` (EMBEDDING_REGISTRY_MAX_MODELS)

### Module 2: Configuration

- **Path**: `parrot/conf.py`
- **Responsibility**: Add `EMBEDDING_REGISTRY_MAX_MODELS` setting (default: 10).
- **Depends on**: None

### Module 3: Registry Exports

- **Path**: `parrot/embeddings/__init__.py`
- **Responsibility**: Export `EmbeddingRegistry` from the embeddings package.
- **Depends on**: Module 1

### Module 4: AbstractStore Integration

- **Path**: `parrot/stores/abstract.py`
- **Responsibility**: Refactor `create_embedding()` and `get_default_embedding()` to use `EmbeddingRegistry.instance().get_or_create_sync()` instead of direct instantiation.
- **Depends on**: Module 1, Module 3

### Module 5: KnowledgeBaseStore Integration

- **Path**: `parrot/stores/kb/store.py`
- **Responsibility**: Replace direct `SentenceTransformer(embedding_model)` call in `__init__` with registry lookup. Make KB embedding loading lazy (deferred to first `add_facts()` or `search_facts()` call).
- **Depends on**: Module 1, Module 3

### Module 6: Bot Warmup Integration

- **Path**: `parrot/bots/abstract.py`
- **Responsibility**: Simplify `warmup_embeddings()` to delegate to `registry.preload()`. Update `configure()` to pass model configs to registry preload when `warmup_on_configure=True`.
- **Depends on**: Module 1, Module 3

### Module 7: EmbeddingModel Base Integration

- **Path**: `parrot/embeddings/base.py`
- **Responsibility**: Optionally wire the `model` property to use registry when available (for backwards compatibility, direct instantiation remains the fallback if registry is not initialized).
- **Depends on**: Module 1

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_registry_singleton` | Module 1 | `EmbeddingRegistry.instance()` returns same object |
| `test_get_or_create_caches` | Module 1 | Second call returns same instance (identity check) |
| `test_get_or_create_different_models` | Module 1 | Different model names create different instances |
| `test_lru_eviction` | Module 1 | After `max_models+1` distinct models, oldest is evicted |
| `test_eviction_calls_free` | Module 1 | Evicted model's `free()` is called for GPU cleanup |
| `test_eviction_logs_warning` | Module 1 | Eviction emits a warning log |
| `test_concurrent_first_access` | Module 1 | Multiple coroutines requesting same model — only one load |
| `test_preload` | Module 1 | `preload()` populates cache without user request |
| `test_unload` | Module 1 | `unload()` removes from cache, calls `free()` |
| `test_unload_nonexistent` | Module 1 | `unload()` for missing model returns False |
| `test_clear` | Module 1 | `clear()` empties cache, calls `free()` on all |
| `test_stats` | Module 1 | `stats()` returns correct hit/miss/eviction counts |
| `test_gpu_memory_tracking` | Module 1 | `stats().gpu_memory_mb` reports GPU usage when CUDA available |
| `test_sync_get_or_create` | Module 1 | `get_or_create_sync()` works in non-async context |
| `test_loaded_models` | Module 1 | `loaded_models()` returns correct list of keys |
| `test_abstractstore_uses_registry` | Module 4 | `create_embedding()` delegates to registry |
| `test_kbstore_lazy_loading` | Module 5 | `KnowledgeBaseStore.__init__` does NOT load model |
| `test_kbstore_loads_on_first_use` | Module 5 | Model loads on first `add_facts()` or `search_facts()` |
| `test_warmup_uses_preload` | Module 6 | `warmup_embeddings()` calls `registry.preload()` |

### Integration Tests

| Test | Description |
|---|---|
| `test_two_bots_share_model` | Two bots with same embedding config share one model instance |
| `test_bot_and_kbstore_share_model` | Bot vector store and KBStore use same registry instance |
| `test_preload_then_ask` | Preloaded model serves `bot.ask()` with zero additional load time |
| `test_eviction_under_load` | Under concurrent requests, eviction works correctly |

### Test Data / Fixtures

```python
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

@pytest.fixture(autouse=True)
def clean_registry():
    """Reset registry between tests."""
    from parrot.embeddings.registry import EmbeddingRegistry
    registry = EmbeddingRegistry.instance()
    registry.clear()
    yield
    registry.clear()

@pytest.fixture
def mock_embedding_model():
    """Mock EmbeddingModel that doesn't load real weights."""
    model = MagicMock()
    model.free = MagicMock()
    model.model_name = "test-model"
    model.encode.return_value = [[0.1] * 384]
    return model
```

---

## 5. Acceptance Criteria

- [ ] `EmbeddingRegistry` singleton works with `get_or_create()` (async) and `get_or_create_sync()` (sync)
- [ ] Same `(model_name, model_type)` always returns the same instance (identity, not equality)
- [ ] LRU eviction triggers at `max_models` threshold (default 10), calls `model.free()`
- [ ] Eviction logs a warning with model name and current cache size
- [ ] GPU memory tracked via `torch.cuda.memory_allocated` when CUDA available
- [ ] `preload()` populates cache eagerly; `unload()` removes and frees
- [ ] Concurrent first-access for same model key loads exactly once (per-key async lock)
- [ ] `AbstractStore.create_embedding()` uses registry — verified by test
- [ ] `KnowledgeBaseStore` no longer loads model in `__init__` — lazy via registry
- [ ] `AbstractBot.warmup_embeddings()` delegates to `registry.preload()`
- [ ] All unit tests pass: `pytest tests/embeddings/ -v`
- [ ] All integration tests pass
- [ ] No breaking changes to existing public API (backwards compatible)
- [ ] `from parrot.embeddings import EmbeddingRegistry` works as standalone import
- [ ] `registry.clear()` properly isolates tests

---

## 6. Implementation Notes & Constraints

### Patterns to Follow

- **Singleton**: Use class-level `_instance` with `@classmethod instance()`. Thread-safe with `threading.Lock` for initial creation.
- **Per-key async locking**: `Dict[CacheKey, asyncio.Lock]` — create lock on first access, acquire before model creation.
- **LRU via OrderedDict**: `move_to_end(key)` on access; `popitem(last=False)` for eviction.
- **Async-first**: `get_or_create()` is the primary API. `get_or_create_sync()` wraps it for `@property` contexts using `threading.Lock`.
- **Logging**: Use `logging.getLogger("parrot.EmbeddingRegistry")`. Warning on eviction, info on load, debug on cache hit.
- **GPU tracking**: `torch.cuda.memory_allocated()` when `torch.cuda.is_available()`, else `None`.

### Known Risks / Gotchas

- **LRU eviction of active model**: If a bot holds a reference to an evicted model, the model object survives (Python refcount). The registry just loses its reference. Next registry access re-creates it. This is acceptable — the model isn't destroyed, just no longer deduplicated.
- **Sync/async bridge**: `get_or_create_sync()` must NOT call `asyncio.run()` if an event loop is already running. Use `threading.Lock` + direct model creation for the sync path.
- **Test isolation**: `autouse` fixture must call `registry.clear()` to prevent cross-test contamination.
- **Import order**: `EmbeddingRegistry` must be importable without side effects (no model loading at import time).

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `torch` | existing | GPU memory tracking, `cuda.empty_cache()` on eviction |
| `sentence-transformers` | existing | HuggingFace embedding models |
| `asyncio` | stdlib | Per-key async locks |
| `collections.OrderedDict` | stdlib | LRU tracking |

---

## 7. Open Questions

- [x] What should `max_models` default to? **Resolved: 10**
- [x] Should eviction log a warning? **Resolved: Yes, log warning with model name and cache size**
- [x] Should registry track GPU memory? **Resolved: Yes, via `torch.cuda.memory_allocated()`**

---

## Worktree Strategy

- **Isolation unit**: `per-spec` (sequential tasks in one worktree)
- **Rationale**: The registry (Module 1) is a foundation — all consumer modules (4-7) depend on it. Sequential execution in one worktree avoids merge conflicts on shared files (`abstract.py`, `__init__.py`).
- **Cross-feature dependencies**: None. Changes are additive to existing components.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-03-20 | Claude | Initial draft from brainstorm |
