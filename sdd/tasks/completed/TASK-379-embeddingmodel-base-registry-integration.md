# TASK-379: Integrate EmbeddingModel Base with Registry

**Feature**: first-time-caching-embedding-model
**Feature ID**: FEAT-054
**Spec**: `sdd/specs/first-time-caching-embedding-model.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-374, TASK-375
**Assigned-to**: unassigned

---

## Context

> The `EmbeddingModel.model` property currently creates a new model instance via
> `_create_embedding()` on every first access. This task wires the property to use
> the registry when available, so even direct `EmbeddingModel` usage benefits from
> caching. Falls back to direct instantiation if registry is not initialized.
> Implements Spec Module 7.

---

## Scope

- Modify `EmbeddingModel.model` property to check registry first
- If registry is available: `registry.get_or_create_sync(model_name, model_type)`
- If registry is not initialized: fall back to current `_create_embedding()` behavior
- Determine `model_type` from class name (e.g., `SentenceTransformerModel` → `huggingface`)
- Update `initialize_model()` async method to use registry's async path
- Write tests for both paths (with and without registry)

**NOT in scope**: Consumer refactoring (TASK-376–378), registry core (TASK-374).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/embeddings/base.py` | MODIFY | Wire `model` property to registry |
| `tests/embeddings/test_base_registry.py` | CREATE | Tests for registry-aware base |

---

## Implementation Notes

### Pattern to Follow

Current property:
```python
@property
def model(self):
    if self._model is None:
        self._model = self._create_embedding(
            model_name=self.model_name,
            **self._kwargs
        )
    return self._model
```

Refactored:
```python
@property
def model(self):
    if self._model is None:
        try:
            from .registry import EmbeddingRegistry
            registry = EmbeddingRegistry.instance()
            model_type = self._get_model_type()
            self._model = registry.get_or_create_sync(
                self.model_name, model_type, **self._kwargs
            )
        except Exception:
            # Fallback: direct creation if registry not available
            self._model = self._create_embedding(
                model_name=self.model_name,
                **self._kwargs
            )
    return self._model

def _get_model_type(self) -> str:
    """Derive model_type from class name for registry lookup."""
    # Map class names to supported_embeddings keys
    class_to_type = {
        'SentenceTransformerModel': 'huggingface',
        'OpenAIEmbeddingModel': 'openai',
        'GoogleEmbeddingModel': 'google',
    }
    return class_to_type.get(self.__class__.__name__, 'huggingface')
```

### Key Constraints
- Must not break existing subclasses that override `_create_embedding()`
- The fallback path (direct creation) ensures backwards compatibility
- `_get_model_type()` must handle all known subclasses
- Import registry inside the property to avoid circular imports
- The `model.setter` (used in `initialize_model()`) must still work

### References in Codebase
- `parrot/embeddings/base.py:36-42` — current `model` property
- `parrot/embeddings/base.py:88-96` — `initialize_model()` async method
- `parrot/embeddings/huggingface.py` — `SentenceTransformerModel` subclass
- `parrot/embeddings/openai.py` — `OpenAIEmbeddingModel` subclass
- `parrot/embeddings/google.py` — `GoogleEmbeddingModel` subclass

---

## Acceptance Criteria

- [ ] `EmbeddingModel.model` property uses registry when available
- [ ] Falls back to direct `_create_embedding()` if registry not initialized
- [ ] `_get_model_type()` correctly maps all known subclasses
- [ ] `initialize_model()` async method uses registry's async path
- [ ] Existing subclasses (HuggingFace, OpenAI, Google) work unchanged
- [ ] Tests pass: `pytest tests/embeddings/test_base_registry.py -v`

---

## Test Specification

```python
# tests/embeddings/test_base_registry.py
import pytest
from unittest.mock import patch, MagicMock


class TestEmbeddingModelRegistryIntegration:
    def test_model_property_uses_registry(self):
        """model property delegates to registry when available."""
        ...

    def test_model_property_fallback(self):
        """model property falls back to _create_embedding() if no registry."""
        ...

    def test_get_model_type_huggingface(self):
        """SentenceTransformerModel maps to 'huggingface'."""
        ...

    def test_get_model_type_openai(self):
        """OpenAIEmbeddingModel maps to 'openai'."""
        ...

    def test_get_model_type_google(self):
        """GoogleEmbeddingModel maps to 'google'."""
        ...

    @pytest.mark.asyncio
    async def test_initialize_model_uses_registry(self):
        """initialize_model() uses registry's async path."""
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
6. **Move this file** to `tasks/completed/TASK-379-embeddingmodel-base-registry-integration.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker
**Date**: 2026-03-20
**Notes**: Added `_get_model_type()` method that maps concrete class names to `supported_embeddings` keys. Modified `model` property to try `EmbeddingRegistry.instance().get_or_create_sync()` first, falling back to `_create_embedding()` on exception. Updated `initialize_model()` async method to use `registry.get_or_create()` (async path) with the same fallback. Created `tests/embeddings/test_base_registry.py`.

**Deviations from spec**: none
