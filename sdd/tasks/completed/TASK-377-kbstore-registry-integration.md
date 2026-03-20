# TASK-377: Integrate KnowledgeBaseStore with EmbeddingRegistry

**Feature**: first-time-caching-embedding-model
**Feature ID**: FEAT-054
**Spec**: `sdd/specs/first-time-caching-embedding-model.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-374, TASK-375
**Assigned-to**: unassigned

---

## Context

> `KnowledgeBaseStore.__init__` currently calls `SentenceTransformer(embedding_model)`
> directly, eagerly loading the model on construction. This task refactors it to use
> the `EmbeddingRegistry` for deduplication and makes loading lazy (deferred to first
> `add_facts()` or `search_facts()` call).
> Implements Spec Module 5.

---

## Scope

- Refactor `KnowledgeBaseStore.__init__` to store model config but NOT load the model
- Add a lazy `_get_embeddings()` method that retrieves the model from the registry on first use
- Update `add_facts()` and `search_facts()` to use `_get_embeddings()` instead of `self.embeddings`
- Maintain the `self.embeddings` property for backwards compatibility
- Write tests verifying lazy loading behavior

**NOT in scope**: AbstractStore refactoring (TASK-376), bot integration (TASK-378).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/stores/kb/store.py` | MODIFY | Lazy loading via registry |
| `tests/stores/kb/test_kbstore_registry.py` | CREATE | Tests for lazy loading |

---

## Implementation Notes

### Pattern to Follow

Current eager loading:
```python
class KnowledgeBaseStore:
    def __init__(self, embedding_model: str = "all-MiniLM-L6-v2", ...):
        from sentence_transformers import SentenceTransformer
        self.embeddings = SentenceTransformer(embedding_model)
```

Refactored to lazy:
```python
class KnowledgeBaseStore:
    def __init__(self, embedding_model: str = "all-MiniLM-L6-v2", ...):
        self._embedding_model_name = embedding_model
        self._embeddings = None  # Lazy
        # ... rest of init without loading model

    @property
    def embeddings(self):
        """Lazy-load embedding model via registry on first access."""
        if self._embeddings is None:
            from parrot.embeddings import EmbeddingRegistry
            registry = EmbeddingRegistry.instance()
            self._embeddings = registry.get_or_create_sync(
                self._embedding_model_name, "huggingface"
            )
        return self._embeddings
```

### Key Constraints
- `self.embeddings` must remain a valid attribute (property now, was direct assignment)
- `self.embeddings.encode(...)` calls in `add_facts()` and `search_facts()` should work unchanged
- The FAISS index initialization can stay eager (it's lightweight)
- Import `EmbeddingRegistry` inside the property to avoid circular imports at module level
- The `sentence_transformers` import can be deferred too (registry handles it)

### References in Codebase
- `parrot/stores/kb/store.py` — current `KnowledgeBaseStore` implementation
- `parrot/bots/abstract.py:1007-1011` — `warmup_embeddings()` calls `self.kb_store.embeddings.encode()`

---

## Acceptance Criteria

- [ ] `KnowledgeBaseStore.__init__` does NOT load any model (no SentenceTransformer call)
- [ ] `self.embeddings` property loads model lazily on first access via registry
- [ ] `add_facts()` works correctly (embeddings loaded on first call)
- [ ] `search_facts()` works correctly (embeddings loaded on first call)
- [ ] `warmup_embeddings()` in AbstractBot still works (accesses `self.kb_store.embeddings`)
- [ ] Two KBStores with same model name share one instance
- [ ] Tests pass: `pytest tests/stores/kb/test_kbstore_registry.py -v`

---

## Test Specification

```python
# tests/stores/kb/test_kbstore_registry.py
import pytest
from unittest.mock import patch, MagicMock


class TestKBStoreRegistryIntegration:
    def test_init_does_not_load_model(self):
        """KnowledgeBaseStore.__init__ does not trigger model loading."""
        ...

    def test_embeddings_loads_on_first_access(self):
        """Accessing .embeddings triggers registry lookup."""
        ...

    def test_two_kbstores_share_model(self):
        """Two KBStores with same model name get same instance."""
        ...

    @pytest.mark.asyncio
    async def test_add_facts_triggers_lazy_load(self):
        """add_facts() causes embedding model to load."""
        ...

    @pytest.mark.asyncio
    async def test_search_facts_triggers_lazy_load(self):
        """search_facts() causes embedding model to load."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-374, TASK-375 must be completed
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-377-kbstore-registry-integration.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker
**Date**: 2026-03-20
**Notes**: Replaced eager `SentenceTransformer(embedding_model)` in `__init__` with `self._embedding_model_name = embedding_model; self._embeddings = None`. Added lazy `embeddings` property that calls `EmbeddingRegistry.instance().get_or_create_sync(...)` on first access. Added `embeddings.setter` for backwards compatibility. `add_facts()` and `search_facts()` continue to use `self.embeddings.encode(...)` unchanged.

**Deviations from spec**: none
