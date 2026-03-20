# TASK-374: Implement EmbeddingRegistry Singleton Core

**Feature**: first-time-caching-embedding-model
**Feature ID**: FEAT-054
**Spec**: `sdd/specs/first-time-caching-embedding-model.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-373
**Assigned-to**: unassigned

---

## Context

> This is the foundation task for FEAT-054. The `EmbeddingRegistry` is a process-wide
> singleton that caches embedding model instances by `(model_name, model_type)` key,
> provides async-safe concurrent access with per-key locks, LRU eviction, GPU memory
> tracking, and explicit preload/unload APIs.
> Implements Spec Module 1.

---

## Scope

- Create `parrot/embeddings/registry.py` with the `EmbeddingRegistry` class
- Implement singleton pattern with `@classmethod instance()`
- Implement `OrderedDict`-based LRU cache keyed by `(model_name, model_type)`
- Implement `get_or_create()` (async) with per-key `asyncio.Lock`
- Implement `get_or_create_sync()` with `threading.Lock` for non-async contexts
- Implement `preload()` — async bulk loading
- Implement `unload()` — remove from cache, call `model.free()`
- Implement `loaded_models()` — list of cached keys
- Implement `stats()` — hit/miss/eviction counts, GPU memory
- Implement `clear()` — reset cache for test isolation
- LRU eviction at `max_models` threshold, calls `model.free()`, logs warning
- GPU memory tracking via `torch.cuda.memory_allocated()` when CUDA available
- Write comprehensive unit tests

**NOT in scope**: Consumer integration (TASK-376–379), exports (TASK-375).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/embeddings/registry.py` | CREATE | EmbeddingRegistry singleton |
| `tests/embeddings/test_registry.py` | CREATE | Unit tests for registry |
| `tests/embeddings/__init__.py` | CREATE | Test package init (if missing) |

---

## Implementation Notes

### Pattern to Follow

```python
import asyncio
import threading
import importlib
from collections import OrderedDict
from typing import Tuple, Optional, Any, Dict, List
from navconfig.logging import logging
from ..conf import EMBEDDING_REGISTRY_MAX_MODELS
from . import supported_embeddings

CacheKey = Tuple[str, str]  # (model_name, model_type)

class EmbeddingRegistry:
    """Process-wide singleton for embedding model caching with LRU eviction."""

    _instance: Optional["EmbeddingRegistry"] = None
    _instance_lock = threading.Lock()

    def __init__(self, max_models: int = None):
        # Only called internally by instance()
        self._max_models = max_models or EMBEDDING_REGISTRY_MAX_MODELS
        self._cache: OrderedDict[CacheKey, Any] = OrderedDict()
        self._locks: Dict[CacheKey, asyncio.Lock] = {}
        self._sync_lock = threading.Lock()
        self._global_lock = asyncio.Lock()
        self._stats = {"hits": 0, "misses": 0, "evictions": 0}
        self.logger = logging.getLogger("parrot.EmbeddingRegistry")

    @classmethod
    def instance(cls, max_models: int = None) -> "EmbeddingRegistry":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls(max_models=max_models)
            return cls._instance
```

### Key Constraints
- `get_or_create()` must use per-key `asyncio.Lock` — multiple coroutines requesting
  different models should NOT block each other
- `get_or_create_sync()` must NOT call `asyncio.run()` — use `threading.Lock` + direct creation
- Model creation: use `supported_embeddings` dict to resolve class, then `importlib.import_module()`
  (same pattern as `AbstractStore.create_embedding()`)
- On eviction: call `model.free()`, log warning: `"Evicting embedding model '%s' (cache full: %d/%d)"`
- GPU memory: `torch.cuda.memory_allocated() / 1024 / 1024` when `torch.cuda.is_available()`
- `clear()` must call `free()` on every model before clearing the OrderedDict

### References in Codebase
- `parrot/embeddings/base.py` — `EmbeddingModel` base class with `free()` method
- `parrot/embeddings/__init__.py` — `supported_embeddings` dict for class resolution
- `parrot/stores/abstract.py:create_embedding()` — existing model creation pattern to mirror

---

## Acceptance Criteria

- [ ] `EmbeddingRegistry.instance()` returns the same object on repeated calls
- [ ] `get_or_create()` caches by `(model_name, model_type)` — identity check
- [ ] `get_or_create()` with different keys creates different instances
- [ ] LRU eviction at `max_models`, calls `model.free()`, logs warning
- [ ] Concurrent `get_or_create()` for same key loads model exactly once
- [ ] `preload()` populates cache for list of model configs
- [ ] `unload()` removes model, calls `free()`, returns True (False if not found)
- [ ] `loaded_models()` returns list of `(model_name, model_type)` tuples
- [ ] `stats()` returns correct hit/miss/eviction counts
- [ ] `clear()` empties cache, calls `free()` on all models
- [ ] `get_or_create_sync()` works in non-async contexts
- [ ] All tests pass: `pytest tests/embeddings/test_registry.py -v`
- [ ] Import works: `from parrot.embeddings.registry import EmbeddingRegistry`

---

## Test Specification

```python
# tests/embeddings/test_registry.py
import pytest
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock

@pytest.fixture(autouse=True)
def clean_registry():
    """Reset singleton between tests."""
    from parrot.embeddings.registry import EmbeddingRegistry
    EmbeddingRegistry._instance = None
    yield
    if EmbeddingRegistry._instance:
        EmbeddingRegistry._instance.clear()
        EmbeddingRegistry._instance = None


class TestEmbeddingRegistrySingleton:
    def test_instance_returns_same_object(self):
        from parrot.embeddings.registry import EmbeddingRegistry
        r1 = EmbeddingRegistry.instance()
        r2 = EmbeddingRegistry.instance()
        assert r1 is r2

    def test_instance_respects_max_models(self):
        from parrot.embeddings.registry import EmbeddingRegistry
        r = EmbeddingRegistry.instance(max_models=5)
        assert r._max_models == 5


class TestGetOrCreate:
    @pytest.mark.asyncio
    async def test_caches_by_key(self):
        """Same (model_name, model_type) returns same instance."""
        ...

    @pytest.mark.asyncio
    async def test_different_keys_different_instances(self):
        """Different model names create different instances."""
        ...

    @pytest.mark.asyncio
    async def test_concurrent_first_access(self):
        """Multiple coroutines for same key — only one model created."""
        ...


class TestLRUEviction:
    @pytest.mark.asyncio
    async def test_evicts_oldest_when_full(self):
        """After max_models+1, oldest model is evicted."""
        ...

    @pytest.mark.asyncio
    async def test_eviction_calls_free(self):
        """Evicted model's free() is called."""
        ...

    @pytest.mark.asyncio
    async def test_eviction_logs_warning(self):
        """Eviction emits a warning log."""
        ...

    @pytest.mark.asyncio
    async def test_access_refreshes_lru(self):
        """Accessing a cached model moves it to end (not evicted next)."""
        ...


class TestPreloadUnload:
    @pytest.mark.asyncio
    async def test_preload_populates_cache(self):
        ...

    @pytest.mark.asyncio
    async def test_unload_removes_and_frees(self):
        ...

    @pytest.mark.asyncio
    async def test_unload_nonexistent_returns_false(self):
        ...


class TestStats:
    @pytest.mark.asyncio
    async def test_stats_tracks_hits_misses(self):
        ...

    def test_loaded_models_returns_keys(self):
        ...


class TestClear:
    @pytest.mark.asyncio
    async def test_clear_empties_cache(self):
        ...

    @pytest.mark.asyncio
    async def test_clear_calls_free_on_all(self):
        ...


class TestSyncAccess:
    def test_get_or_create_sync(self):
        """Sync variant works in non-async context."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-373 must be completed
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-374-embedding-registry-core.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker
**Date**: 2026-03-20
**Notes**: Created `parrot/embeddings/registry.py` with full `EmbeddingRegistry` singleton implementation: `OrderedDict`-based LRU cache, per-key `asyncio.Lock`, thread-safe singleton via `threading.Lock`, async `get_or_create()` with `run_in_executor` for non-blocking model load, sync `get_or_create_sync()` using `threading.Lock`, `preload()`/`unload()`/`clear()`/`loaded_models()`/`stats()`. `RegistryStats` dataclass with GPU memory tracking. Also created `tests/embeddings/test_registry.py` and `tests/embeddings/__init__.py`.

**Deviations from spec**: none
