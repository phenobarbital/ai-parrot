# TASK-1340: Matryoshka + contextual augmentation cross-distribution regression suite

**Feature**: FEAT-201 — ai-parrot-embeddings
**Spec**: `sdd/specs/ai-parrot-embeddings.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1334, TASK-1335
**Assigned-to**: unassigned

---

## Context

Implements **Module 8** of the spec — proves that the two highest-risk
cross-boundary wirings still work after the split:

- **Matryoshka kwarg-forwarding (FEAT-150)**: `AbstractStore.create_embedding`
  (in core) forwards a `matryoshka={...}` kwarg through to
  `SentenceTransformerModel.encode()` (now in the satellite). The
  3-tuple cache-key change in `EmbeddingRegistry` must keep working.
- **Contextual augmentation (FEAT-127/128)**: `AbstractStore._apply_contextual_augmentation`
  hook (in core's `AbstractStore`) is invoked by the moved concrete
  stores (`PgVectorStore.add_documents`, `MilvusStore`, etc.).

Without this regression suite, a subtle break in the cross-distribution
import or attribute lookup could ship silently.

Reference: spec §3 Module 8, §7 Known Risks, F013.

---

## Scope

Create
`packages/ai-parrot-embeddings/tests/test_cross_dist_matryoshka.py`
with two test classes:

1. **`TestMatryoshkaForwarding`** — exercises the kwarg-forwarding
   chain end-to-end with the satellite installed:
   - Build an `EmbeddingRegistry` instance.
   - `get_or_create_sync("all-MiniLM-L6-v2", "huggingface",
     matryoshka={"enabled": True, "dimension": 256})`.
   - Assert the 3-tuple cache key includes `256`.
   - Encode a sample text; assert the embedding dimension is 256.
   - Verify the model resolves through the satellite (`__module__ ==
     'parrot.embeddings.huggingface'`).

2. **`TestContextualAugmentationForwarding`** — exercises the
   contextual augmentation hook from a satellite-supplied store:
   - Instantiate `PgVectorStore` (or `FAISSStore`, easier — no DB
     fixture needed) with a contextual-augmentation config.
   - Call `add_documents` with a small fixture set.
   - Assert the contextual-augmentation hook ran (mock the hook
     callable and assert call count).
   - Verify the store resolves through the satellite.

**NOT in scope**:
- Adding new test fixtures for live Milvus / Postgres / Arango DBs —
  use FAISS (in-memory) or mock the I/O layer.
- Refactoring the existing matryoshka tests at
  `packages/ai-parrot/tests/` — they stay; this task ADDS a
  cross-distribution smoke test alongside.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-embeddings/tests/test_cross_dist_matryoshka.py` | CREATE | Matryoshka + contextual augmentation cross-boundary smoke tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Cross-Boundary Wiring

```python
# packages/ai-parrot/src/parrot/embeddings/registry.py:218-281 (STAYS in core)
async def get_or_create(self, model_name, model_type="huggingface", **kwargs) -> Any:
    matryoshka_dim = self._extract_matryoshka_dim(kwargs)
    key: CacheKey = (model_name, model_type, matryoshka_dim)   # ← FEAT-150 3-tuple
    ...

# packages/ai-parrot/src/parrot/embeddings/registry.py:119-147
@staticmethod
def _extract_matryoshka_dim(kwargs: dict) -> Optional[int]:
    cfg = kwargs.get("matryoshka")
    if not isinstance(cfg, dict):
        return None
    if not cfg.get("enabled"):
        return None
    dim = cfg.get("dimension")
    return int(dim) if isinstance(dim, int) and dim > 0 else None

# packages/ai-parrot/src/parrot/stores/abstract.py:297 (STAYS in core)
def create_embedding(self, ..., matryoshka=None) -> EmbeddingModel:
    # FEAT-150: forwards matryoshka kwarg through to the underlying EmbeddingModel
    ...
```

### Verified Matryoshka Pydantic Model

```python
# packages/ai-parrot/src/parrot/embeddings/matryoshka.py (STAYS in core)
class MatryoshkaConfig(BaseModel):
    enabled: bool
    dimension: Optional[int]
    # see file for exact fields
```

### Verified FAISS Path (lightest test fixture)

```python
# Moved to packages/ai-parrot-embeddings/src/parrot/stores/faiss_store.py:32
class FAISSStore(AbstractStore):
    # In-memory store — no external DB needed. Use this for the
    # contextual-augmentation smoke test.
```

### Does NOT Exist (Anti-Hallucination)

- ~~`MatryoshkaConfig(dimension=128)` as the registry's API surface~~
  — the Registry accepts a plain `matryoshka={...}` dict via `**kwargs`,
  not a `MatryoshkaConfig` instance. The Pydantic model is used inside
  `SentenceTransformerModel.__init__` (via `validate_against_catalog`),
  not by the Registry directly.
- ~~`EmbeddingRegistry.matryoshka_cache` attribute~~ — does not exist;
  the cache is a single `OrderedDict` keyed by the 3-tuple.
- ~~`AbstractStore.apply_contextual_augmentation` (public)~~ — actual
  method is `_apply_contextual_augmentation` (underscore-prefixed
  hook). Check the abstract.py source for the exact name before
  patching.

---

## Implementation Notes

### Suggested test for Matryoshka kwarg forwarding

```python
# packages/ai-parrot-embeddings/tests/test_cross_dist_matryoshka.py
import pytest

from parrot.embeddings.registry import EmbeddingRegistry


@pytest.mark.requires_huggingface
class TestMatryoshkaForwarding:
    """FEAT-150 still works across the FEAT-201 boundary."""

    def test_cache_key_includes_dimension(self):
        registry = EmbeddingRegistry.instance()
        registry.clear()
        registry.get_or_create_sync(
            "all-MiniLM-L6-v2",
            "huggingface",
            matryoshka={"enabled": True, "dimension": 256},
        )
        keys = registry.loaded_models()
        assert any(k[2] == 256 for k in keys), \
            f"matryoshka dim missing from cache keys: {keys}"

    def test_model_resolves_to_satellite(self):
        registry = EmbeddingRegistry.instance()
        registry.clear()
        model = registry.get_or_create_sync(
            "all-MiniLM-L6-v2",
            "huggingface",
        )
        # Model is an EmbeddingModel wrapper — class lives in satellite
        assert model.__class__.__module__ == "parrot.embeddings.huggingface", \
            f"model resolved to {model.__class__.__module__}"
```

### Suggested test for contextual-augmentation forwarding

```python
from unittest.mock import patch

import pytest


@pytest.mark.requires_faiss
class TestContextualAugmentationForwarding:
    """FEAT-127/128 hook still fires when stores live in the satellite."""

    @pytest.mark.asyncio
    async def test_augmentation_hook_fires_on_add_documents(self):
        from parrot.stores.faiss_store import FAISSStore
        from parrot.stores.models import Document

        store = FAISSStore(...)  # minimal config; verify in implementation
        docs = [Document(id="1", content="hello world", metadata={})]

        with patch.object(
            FAISSStore.__bases__[0],   # AbstractStore (in core)
            "_apply_contextual_augmentation",
            wraps=getattr(FAISSStore.__bases__[0], "_apply_contextual_augmentation"),
        ) as spy:
            await store.add_documents(docs)
            assert spy.called, "contextual augmentation hook did not fire"

    def test_store_resolves_to_satellite(self):
        import parrot.stores.faiss_store as fs
        assert "ai-parrot-embeddings" in fs.__file__
```

### Pytest markers

Add to `packages/ai-parrot-embeddings/pyproject.toml` or
`tests/conftest.py`:

```python
# conftest.py
def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "requires_huggingface: requires the huggingface extra (sentence-transformers)",
    )
    config.addinivalue_line(
        "markers",
        "requires_faiss: requires the faiss extra (faiss-cpu)",
    )
```

CI can then skip these on cheap runners via `pytest -m "not requires_huggingface"`.

### References in Codebase

- `packages/ai-parrot/src/parrot/embeddings/registry.py:33-37,119-147` —
  3-tuple CacheKey + extract helper (STAY).
- `packages/ai-parrot/src/parrot/stores/abstract.py:297` —
  `create_embedding(matryoshka=...)` (STAYS).
- Git log entries `84ce2866`, `7f2d5b99`, `d48ec222`, `fe949c6d`,
  `b3f25477` (FEAT-150) and `f3f80ee1`, `66475ac2`, `595544e9`
  (FEAT-127/128) — context for what's being regression-tested.

---

## Acceptance Criteria

- [ ] `packages/ai-parrot-embeddings/tests/test_cross_dist_matryoshka.py`
      exists with the two test classes.
- [ ] Tests skip cleanly when their `requires_*` extra is not installed.
- [ ] `pytest -m requires_huggingface
      packages/ai-parrot-embeddings/tests/test_cross_dist_matryoshka.py`
      passes when `[huggingface]` is installed.
- [ ] `pytest -m requires_faiss
      packages/ai-parrot-embeddings/tests/test_cross_dist_matryoshka.py`
      passes when `[faiss]` is installed (faiss-cpu is in core deps so
      it's always present).
- [ ] If either wiring is broken, the corresponding test FAILS with a
      message that points the implementer at the right module (e.g.
      "cache keys missing matryoshka dim" rather than a bare
      `AssertionError`).
- [ ] The existing matryoshka test suite at
      `packages/ai-parrot/tests/` continues to pass unchanged.

---

## Test Specification

The test file IS the deliverable.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** §3 Module 8 and §7 Known Risks.
2. **Check dependencies** — TASK-1334 and TASK-1335 must be in
   `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — re-read
   `embeddings/registry.py` cache-key code and `stores/abstract.py`
   `create_embedding` signature.
4. **Update status** in
   `sdd/tasks/index/ai-parrot-embeddings.json` → `"in-progress"`.
5. **Implement** the two test classes. Discover the actual
   `_apply_contextual_augmentation` method name and FAISSStore init
   shape before assuming.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note**.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker agent)
**Date**: 2026-05-28
**Notes**: …

**Deviations from spec**: none | describe if any
