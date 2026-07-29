---
type: Wiki Overview
title: 'TASK-1544: Add backend field to EmbeddingModelEntry + new catalog entries'
id: doc:sdd-tasks-completed-task-1544-catalog-backend-field-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Module 1 of FEAT-237. The `EmbeddingModelEntry` Pydantic schema in `catalog.py`
  currently lacks a `backend` field, preventing ONNX/OpenVINO model entries from being
  expressed in the catalog. This task adds the field and registers new embedding model
  entries needed by the benchmar
relates_to:
- concept: mod:parrot.embeddings.catalog
  rel: mentions
---

# TASK-1544: Add backend field to EmbeddingModelEntry + new catalog entries

**Feature**: FEAT-237 — PageIndex Embedding Router
**Spec**: `sdd/specs/pageindex-embedding-router.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Module 1 of FEAT-237. The `EmbeddingModelEntry` Pydantic schema in `catalog.py` currently lacks a `backend` field, preventing ONNX/OpenVINO model entries from being expressed in the catalog. This task adds the field and registers new embedding model entries needed by the benchmark matrix.

Spec reference: §3 Module 1, §6 Codebase Contract.

---

## Scope

- Add an optional `backend` field (`Literal["torch", "onnx", "openvino"] | None`, default `None`) to `EmbeddingModelEntry`.
- Add catalog entries for:
  - `Qwen/Qwen3-Embedding-0.6B` (Apache 2.0)
  - `intfloat/multilingual-e5-small` (MIT)
  - `minishlab/potion-base-8M` (MIT, model2vec/static)
- Ensure existing catalog entries validate without `backend` (backward compat).
- Write unit tests.

**NOT in scope**: Modifying `SentenceTransformerModel` (that's TASK-1545), adding EmbeddingGemma-300M (deferred).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/embeddings/catalog.py` | MODIFY | Add `backend` field to `EmbeddingModelEntry`; add 3 new model entries |
| `tests/embeddings/test_catalog_backend.py` | CREATE | Unit tests for backend field + new entries |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.

### Verified Imports

```python
from parrot.embeddings.catalog import EMBEDDING_MODELS, EmbeddingModelEntry  # verified: catalog.py
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/embeddings/catalog.py
class EmbeddingModelEntry(BaseModel):
    model: str           # line 77
    provider: Provider   # line 78
    name: str            # line 79
    dimension: int       # line ~80
    matryoshka_dimensions: Optional[list[int]] = None  # line 96
    # NO backend field currently — this task adds it

EMBEDDING_MODELS: dict[str, EmbeddingModelEntry]  # line 171 — the global registry dict
```

### Does NOT Exist

- ~~`EmbeddingModelEntry.backend`~~ — does not exist yet; this task adds it
- ~~`intfloat/multilingual-e5-small` in EMBEDDING_MODELS~~ — NOT in catalog (only e5-base and e5-large exist)
- ~~`Qwen/Qwen3-Embedding-0.6B` in EMBEDDING_MODELS~~ — NOT in catalog (only Octen derivative is present)

---

## Implementation Notes

### Pattern to Follow

```python
# Existing field pattern in EmbeddingModelEntry:
class EmbeddingModelEntry(BaseModel):
    model: str
    provider: Provider
    name: str
    dimension: int
    matryoshka_dimensions: Optional[list[int]] = None
    # Add here:
    backend: Optional[Literal["torch", "onnx", "openvino"]] = None
```

### Key Constraints

- The `backend` field MUST be optional with `None` default so all existing entries validate without change.
- New entries should follow the exact pattern of existing `EMBEDDING_MODELS` dict entries.
- Use `Literal` from `typing` for the backend type constraint.
- The Octen-Embedding-0.6B entry already exists — do NOT duplicate it. Add Qwen3 as a separate entry.

### References in Codebase

- `packages/ai-parrot/src/parrot/embeddings/catalog.py` — schema + registry dict
- `packages/ai-parrot/src/parrot/embeddings/matryoshka.py` — `validate_against_catalog` uses catalog entries

---

## Acceptance Criteria

- [ ] `EmbeddingModelEntry` has an optional `backend` field with `Literal["torch", "onnx", "openvino"] | None`
- [ ] All existing catalog entries validate without modification (backward compat)
- [ ] `Qwen/Qwen3-Embedding-0.6B`, `intfloat/multilingual-e5-small`, `minishlab/potion-base-8M` added to `EMBEDDING_MODELS`
- [ ] Unit tests pass: `pytest tests/embeddings/test_catalog_backend.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/embeddings/catalog.py`

---

## Test Specification

```python
# tests/embeddings/test_catalog_backend.py
import pytest
from parrot.embeddings.catalog import EMBEDDING_MODELS, EmbeddingModelEntry


class TestCatalogBackendField:
    def test_backend_field_optional(self):
        """Existing entries validate without backend field."""
        for name, entry in EMBEDDING_MODELS.items():
            assert isinstance(entry, EmbeddingModelEntry)

    def test_backend_field_accepts_valid_values(self):
        """Backend field accepts torch/onnx/openvino."""
        entry = EmbeddingModelEntry(
            model="test/model", provider="huggingface", name="test",
            dimension=256, backend="onnx"
        )
        assert entry.backend == "onnx"

    def test_backend_field_rejects_invalid(self):
        """Backend field rejects unknown values."""
        with pytest.raises(Exception):
            EmbeddingModelEntry(
                model="test/model", provider="huggingface", name="test",
                dimension=256, backend="invalid"
            )

    def test_qwen3_entry_exists(self):
        """Qwen3-Embedding-0.6B is in the catalog."""
        assert "Qwen/Qwen3-Embedding-0.6B" in EMBEDDING_MODELS

    def test_e5_small_entry_exists(self):
        """multilingual-e5-small is in the catalog."""
        assert "intfloat/multilingual-e5-small" in EMBEDDING_MODELS

    def test_potion_entry_exists(self):
        """potion-base-8M is in the catalog."""
        assert "minishlab/potion-base-8M" in EMBEDDING_MODELS
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/pageindex-embedding-router.spec.md` for full context
2. **Check dependencies** — this task has no dependencies
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm `EmbeddingModelEntry` schema at `catalog.py`
   - Confirm `EMBEDDING_MODELS` dict structure
   - If anything has changed, update the contract FIRST
4. **Update status** in `sdd/tasks/index/pageindex-embedding-router.json` → `"in-progress"`
5. **Implement** following the scope and contract above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1544-catalog-backend-field.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: 
**Date**: 
**Notes**: 

**Deviations from spec**: none | describe if any

---
_Completion appended by sdd-worker_

**Completed by**: sdd-worker (Claude Sonnet 4.6)
**Date**: 2026-06-15
**Notes**: Added optional `backend: Optional[Literal["torch", "onnx", "openvino"]] = None` field to `EmbeddingModelEntry`. Added 3 new entries: Qwen/Qwen3-Embedding-0.6B (1024d, matryoshka), intfloat/multilingual-e5-small (384d), minishlab/potion-base-8M (256d). All 10 unit tests pass.

**Deviations from spec**: The test spec used `"model_id" in EMBEDDING_MODELS` but EMBEDDING_MODELS is a list not a dict. Tests use a helper function `_find_model(model_id)` that searches the list by the `model` field key. Functionally equivalent.
