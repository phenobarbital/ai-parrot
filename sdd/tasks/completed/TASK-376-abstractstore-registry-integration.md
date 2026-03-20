# TASK-376: Integrate AbstractStore with EmbeddingRegistry

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

> `AbstractStore.create_embedding()` currently instantiates a new `EmbeddingModel` on
> every call via `importlib.import_module()`. This task refactors it to use
> `EmbeddingRegistry.instance().get_or_create_sync()` for deduplication.
> Similarly, `get_default_embedding()` and `generate_embedding()` benefit from caching.
> Implements Spec Module 4.

---

## Scope

- Refactor `AbstractStore.create_embedding()` to delegate to `EmbeddingRegistry.instance().get_or_create_sync()`
- Refactor `AbstractStore.get_default_embedding()` to use registry
- Ensure `generate_embedding()` still works (it calls `get_default_embedding()` as fallback)
- Write tests verifying registry is used
- Maintain backwards compatibility — method signatures unchanged

**NOT in scope**: KBStore refactoring (TASK-377), bot integration (TASK-378).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/stores/abstract.py` | MODIFY | Refactor `create_embedding()` and `get_default_embedding()` |
| `tests/stores/test_abstract_store_registry.py` | CREATE | Tests for registry integration |

---

## Implementation Notes

### Pattern to Follow

Current code in `AbstractStore.create_embedding()`:
```python
def create_embedding(self, embedding_model: dict, **kwargs):
    model_type = embedding_model.get('model_type', 'huggingface')
    model_name = embedding_model.get('model_name', EMBEDDING_DEFAULT_MODEL)
    embed_cls = supported_embeddings[model_type]
    cls_path = f"..embeddings.{model_type}"
    embed_module = importlib.import_module(cls_path, package=__package__)
    embed_obj = getattr(embed_module, embed_cls)
    return embed_obj(model_name=model_name, **kwargs)
```

Refactored to:
```python
def create_embedding(self, embedding_model: dict, **kwargs):
    from parrot.embeddings import EmbeddingRegistry
    model_type = embedding_model.get('model_type', 'huggingface')
    model_name = embedding_model.get('model_name', EMBEDDING_DEFAULT_MODEL)
    registry = EmbeddingRegistry.instance()
    return registry.get_or_create_sync(model_name, model_type, **kwargs)
```

### Key Constraints
- Use `get_or_create_sync()` since `create_embedding()` is a sync method
- Method signature unchanged — callers see no difference
- Import `EmbeddingRegistry` inside the method to avoid circular imports
- Remove the `importlib.import_module` logic (now handled by registry)

### References in Codebase
- `parrot/stores/abstract.py:223-277` — current `create_embedding()`, `get_default_embedding()`, `generate_embedding()`
- `parrot/embeddings/registry.py` — the registry (TASK-374)

---

## Acceptance Criteria

- [ ] `AbstractStore.create_embedding()` calls `EmbeddingRegistry.get_or_create_sync()`
- [ ] Same embedding config returns same cached instance (verified by identity check)
- [ ] `generate_embedding()` still works as before
- [ ] Method signatures unchanged — no breaking changes
- [ ] Tests pass: `pytest tests/stores/test_abstract_store_registry.py -v`

---

## Test Specification

```python
# tests/stores/test_abstract_store_registry.py
import pytest
from unittest.mock import patch, MagicMock


class TestAbstractStoreRegistryIntegration:
    def test_create_embedding_uses_registry(self):
        """create_embedding() delegates to EmbeddingRegistry."""
        ...

    def test_same_config_returns_same_instance(self):
        """Two calls with same config return identical instance."""
        ...

    def test_generate_embedding_works(self):
        """generate_embedding() still produces embeddings."""
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
6. **Move this file** to `tasks/completed/TASK-376-abstractstore-registry-integration.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker
**Date**: 2026-03-20
**Notes**: Refactored `create_embedding()` to use `EmbeddingRegistry.instance().get_or_create_sync()` and updated `get_default_embedding()` to call the refactored `create_embedding()`. Removed `importlib` logic from method (now handled by registry). Method signatures unchanged. Created `tests/stores/test_abstract_store_registry.py` and `tests/stores/__init__.py`.

**Deviations from spec**: none
