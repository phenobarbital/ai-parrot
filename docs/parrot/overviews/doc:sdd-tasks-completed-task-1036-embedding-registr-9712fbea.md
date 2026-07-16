---
type: Wiki Overview
title: 'TASK-1036: EmbeddingRegistry Matryoshka cache key'
id: doc:sdd-tasks-completed-task-1036-embedding-registry-matryoshka-cache-key-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: bots that use the same model with DIFFERENT `matryoshka.dimension`
relates_to:
- concept: mod:parrot.embeddings.registry
  rel: mentions
---

# TASK-1036: EmbeddingRegistry Matryoshka cache key

**Feature**: FEAT-150 — Matryoshka Embedding Truncation
**Spec**: `sdd/specs/matryoshka-embedding-truncation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1035
**Assigned-to**: unassigned

---

## Context

`EmbeddingRegistry` caches model instances keyed by
`(model_name, model_type)` (`registry.py:202`). Without this task, two
bots that use the same model with DIFFERENT `matryoshka.dimension`
would silently share one instance — whichever loaded first wins, and
the second bot's truncation config would be silently ignored. This is
the highest-risk failure mode flagged in spec §7 Known Risks.

Implements spec §3 Module 3.

---

## Scope

- Extend the registry's cache key to include the Matryoshka dimension:
  `(model_name, model_type, matryoshka_dim or None)`.
- Update `get_or_create`, `get_or_create_sync`, the per-key async lock
  registry, the `unload` method, and the LRU eviction path so they all
  use the new 3-tuple key.
- Update the `CacheKey` type alias accordingly (if it is currently a
  named tuple or `Tuple[str, str]`, broaden it to 3-tuple).
- The matryoshka_dim is read from `kwargs.get("matryoshka")` in the
  registry — extract it into a small private helper
  `_extract_matryoshka_dim(kwargs) -> Optional[int]` that handles
  `None`, missing, `{"enabled": False, ...}`, and
  `{"enabled": True, "dimension": N}`.
- Add a unit test that creates two bots with the same model + different
  matryoshka dims and asserts they are different cached objects.

**NOT in scope**: changes to the embedding model classes (done in
TASK-1035), to the store-layer forwarding (TASK-1037), or to provisioning
(TASK-1038).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/embeddings/registry.py` | MODIFY | Cache key extension and helper |
| `packages/ai-parrot/tests/embeddings/test_matryoshka_registry.py` | CREATE | Cache-key separation test |
| `packages/ai-parrot/tests/embeddings/test_registry.py` | MODIFY | Adjust any test that compared cache keys as 2-tuples (only if needed) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from typing import Any, Optional, Tuple
import asyncio
from collections import OrderedDict
```

### Existing Signatures to Use

```python
# parrot/embeddings/registry.py
class EmbeddingRegistry:
    _supported_embeddings: dict
    _cache: OrderedDict
    _async_locks: dict
    _max_models: int
    _stats: dict

    def _build_model(self, model_name: str, model_type: str, **kwargs) -> Any:  # line 115
        ...
        return klass(model_name=model_name, **kwargs)  # line 140

    async def get_or_create(
        self, model_name: str, model_type: str = "huggingface", **kwargs,
    ) -> Any:                                          # line 182
        key: CacheKey = (model_name, model_type)       # line 202  ← change here

    def get_or_create_sync(
        self, model_name: str, model_type: str = "huggingface", **kwargs,
    ) -> Any:                                          # line 294

    async def unload(self, model_name: str, model_type: str = "huggingface") -> bool:  # line 260

    def _evict_if_needed(self) -> None:                # line 146

    def _get_or_create_lock(self, key) -> asyncio.Lock:  # line 172
```

### Does NOT Exist

- ~~`EmbeddingRegistry.invalidate_dim`~~ — not a real method.
- ~~A separate `MatryoshkaCache`~~ — there is one cache; do not create
  a parallel structure.

---

## Implementation Notes

### Pattern to Follow

The cache key currently is a 2-tuple: `(model_name, model_type)`.
Broaden it to a 3-tuple: `(model_name, model_type, matryoshka_dim)`,
where the third element is `Optional[int]` and is `None` when the
caller didn't pass a `matryoshka` kwarg or set `enabled=False`.

A null third element preserves backward compatibility — existing
callers that don't pass `matryoshka` always land in the
`(name, type, None)` slot.

### Helper to extract dim

```python
def _extract_matryoshka_dim(kwargs: dict) -> Optional[int]:
    cfg = kwargs.get("matryoshka")
    if not isinstance(cfg, dict):
        return None
    if not cfg.get("enabled"):
        return None
    dim = cfg.get("dimension")
    return int(dim) if isinstance(dim, int) and dim > 0 else None
```

This helper is intentionally permissive — full validation belongs to
TASK-1034's `validate_against_catalog`, which is invoked inside
`SentenceTransformerModel.__init__` (TASK-1035). The registry only
needs a stable cache discriminator.

### `unload` semantics

The `unload(model_name, model_type)` signature today does not include
matryoshka_dim. Two reasonable options:

- **Option A**: keep the signature, sweep all keys whose first two
  elements match (i.e. unload all matryoshka variants of a model).
- **Option B**: add an optional `matryoshka_dim` parameter that
  defaults to `None` and behaves like Option A when omitted.

Pick Option A — fewer API changes, matches the operator intent
("forget this model"). Document the choice in the code comment.

### References in Codebase

- `parrot/embeddings/registry.py:115-329` — full module to modify.
- `parrot/embeddings/__init__.py:1-31` — `EmbeddingRegistry` is
  exported; signature changes must be backward-compatible for
  existing callers that pass only `(model_name, model_type)`.

---

## Acceptance Criteria

- [ ] Cache key is a 3-tuple `(model_name, model_type, matryoshka_dim)`.
- [ ] All registry methods (`get_or_create`, `get_or_create_sync`,
      `unload`, `_evict_if_needed`, `_get_or_create_lock`) use the new key.
- [ ] `EmbeddingRegistry.instance().get_or_create_sync("nomic-ai/nomic-embed-text-v1.5", "huggingface")` returns one object;
      a subsequent call with `matryoshka={"enabled": True, "dimension": 512}` returns a DIFFERENT object.
- [ ] Two `get_or_create_sync` calls with the same dim return the SAME object (cache hit).
- [ ] `unload("model", "huggingface")` removes all variants of that model regardless of matryoshka_dim.
- [ ] No regression in existing registry tests: `pytest packages/ai-parrot/tests/embeddings/test_registry.py -v`
- [ ] New cache-key test passes: `pytest packages/ai-parrot/tests/embeddings/test_matryoshka_registry.py -v`
- [ ] No lint errors: `ruff check packages/ai-parrot/src/parrot/embeddings/registry.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/embeddings/test_matryoshka_registry.py
import pytest
from unittest.mock import MagicMock, patch

from parrot.embeddings.registry import EmbeddingRegistry


@pytest.fixture(autouse=True)
def fresh_registry(monkeypatch):
    """Ensure each test starts with a clean singleton."""
    EmbeddingRegistry._instance = None
    yield
    EmbeddingRegistry._instance = None


class TestMatryoshkaCacheKey:
    def test_different_dims_separate_instances(self, monkeypatch):
        # Replace _build_model so we don't actually load weights
        counter = {"n": 0}
        def stub_build(self, model_name, model_type, **kwargs):
            counter["n"] += 1
            return MagicMock(name=f"model_{counter['n']}")
        monkeypatch.setattr(EmbeddingRegistry, "_build_model", stub_build)

        reg = EmbeddingRegistry.instance()
        a = reg.get_or_create_sync("nomic-ai/nomic-embed-text-v1.5", "huggingface")
        b = reg.get_or_create_sync(
            "nomic-ai/nomic-embed-text-v1.5",
            "huggingface",
            matryoshka={"enabled": True, "dimension": 512},
        )
        assert a is not b
        assert counter["n"] == 2

    def test_same_dim_returns_cached(self, monkeypatch):
        counter = {"n": 0}
        def stub_build(self, model_name, model_type, **kwargs):
            counter["n"] += 1
            return MagicMock(name=f"model_{counter['n']}")
        monkeypatch.setattr(EmbeddingRegistry, "_build_model", stub_build)

        reg = EmbeddingRegistry.instance()
        a = reg.get_or_create_sync(
            "nomic-ai/nomic-embed-text-v1.5", "huggingface",
            matryoshka={"enabled": True, "dimension": 512},
        )
        b = reg.get_or_create_sync(
            "nomic-ai/nomic-embed-text-v1.5", "huggingface",
            matryoshka={"enabled": True, "dimension": 512},
        )
        assert a is b
        assert counter["n"] == 1

    def test_disabled_matryoshka_keys_to_none(self, monkeypatch):
        counter = {"n": 0}
        def stub_build(self, model_name, model_type, **kwargs):
            counter["n"] += 1
            return MagicMock()
        monkeypatch.setattr(EmbeddingRegistry, "_build_model", stub_build)

        reg = EmbeddingRegistry.instance()
        a = reg.get_or_create_sync("nomic-ai/nomic-embed-text-v1.5", "huggingface")
        b = reg.get_or_create_sync(
            "nomic-ai/nomic-embed-text-v1.5", "huggingface",
            matryoshka={"enabled": False, "dimension": 512},
        )
        # enabled=False ⇒ same key slot ⇒ shared instance
        assert a is b
```

---

## Agent Instructions

1. Verify TASK-1034 and TASK-1035 are completed.
2. Re-read spec §3 Module 3 and §7 Known Risks ("registry cache key pollution").
3. Implement the cache-key extension and helper.
4. Run the full embeddings test suite to catch any regression.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-05-06
**Notes**: Extended CacheKey to 3-tuple, added _extract_matryoshka_dim helper, updated get_or_create/get_or_create_sync/unload/_evict_if_needed. Also fixed pre-existing unused imports (field, TYPE_CHECKING). Updated 2 assertions in test_registry.py to use 3-tuple keys. All 243 tests pass.
**Deviations from spec**: None (unused import cleanup was a pre-existing issue that ruff caught).
