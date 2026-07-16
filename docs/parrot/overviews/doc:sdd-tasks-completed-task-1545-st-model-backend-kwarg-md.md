---
type: Wiki Overview
title: 'TASK-1545: Add backend/file_name kwargs to SentenceTransformerModel'
id: doc:sdd-tasks-completed-task-1545-st-model-backend-kwarg-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Module 2 of FEAT-237. The `SentenceTransformerModel` wrapper in `huggingface.py`
  does not forward `backend` or `file_name` kwargs to the `SentenceTransformer()`
  constructor, despite `sentence-transformers>=5.0.0` supporting ONNX/OpenVINO backends
  natively. This task closes that g
relates_to:
- concept: mod:parrot.embeddings.base
  rel: mentions
- concept: mod:parrot.embeddings.catalog
  rel: mentions
- concept: mod:parrot.embeddings.huggingface
  rel: mentions
---

# TASK-1545: Add backend/file_name kwargs to SentenceTransformerModel

**Feature**: FEAT-237 — PageIndex Embedding Router
**Spec**: `sdd/specs/pageindex-embedding-router.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1544
**Assigned-to**: unassigned

---

## Context

Module 2 of FEAT-237. The `SentenceTransformerModel` wrapper in `huggingface.py` does not forward `backend` or `file_name` kwargs to the `SentenceTransformer()` constructor, despite `sentence-transformers>=5.0.0` supporting ONNX/OpenVINO backends natively. This task closes that gap so ONNX-quantized models can be loaded for the CPU benchmark.

Spec reference: §3 Module 2, §6 Codebase Contract.

---

## Scope

- Accept `backend` (Optional[str]) and `file_name` (Optional[str]) in `SentenceTransformerModel.__init__`.
- Forward both to `SentenceTransformer()` constructor in `_create_embedding()`.
- Pull `backend` from the catalog entry (`EmbeddingModelEntry.backend`) when not explicitly provided.
- Write unit tests verifying kwarg forwarding.

**NOT in scope**: Adding new catalog entries (TASK-1544), NodeEmbeddingStore (TASK-1546), model download or benchmark execution.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-embeddings/src/parrot/embeddings/huggingface.py` | MODIFY | Accept `backend` and `file_name` in `__init__`, forward in `_create_embedding()` |
| `tests/embeddings/test_st_backend_kwarg.py` | CREATE | Unit tests for backend kwarg forwarding |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.

### Verified Imports

```python
from parrot.embeddings.huggingface import SentenceTransformerModel  # verified: huggingface.py:111
from parrot.embeddings.base import EmbeddingModel  # verified: base.py
from parrot.embeddings.catalog import EMBEDDING_MODELS, EmbeddingModelEntry  # verified: catalog.py
```

### Existing Signatures to Use

```python
# packages/ai-parrot-embeddings/src/parrot/embeddings/huggingface.py
class SentenceTransformerModel(EmbeddingModel):
    def __init__(self, model_name, matryoshka=None, **kwargs)  # line 131
    async def encode(self, texts: List[str], **kwargs) -> np.ndarray  # line 383
    def _create_embedding(self, model_name=None, **kwargs) -> Any  # line 322
    # _create_embedding builds SentenceTransformer(model_name, **st_kwargs)
    # st_kwargs currently includes: device, cache_folder, [trust_remote_code]
    # Does NOT pass backend or file_name — THIS IS THE GAP

# packages/ai-parrot/src/parrot/embeddings/catalog.py (after TASK-1544)
class EmbeddingModelEntry(BaseModel):
    model: str
    provider: Provider
    name: str
    dimension: int
    matryoshka_dimensions: Optional[list[int]] = None
    backend: Optional[Literal["torch", "onnx", "openvino"]] = None  # added by TASK-1544
```

### Does NOT Exist

- ~~`SentenceTransformerModel.__init__(backend=...)`~~ — parameter does not exist yet; this task adds it
- ~~`SentenceTransformerModel.__init__(file_name=...)`~~ — parameter does not exist yet; this task adds it
- ~~`SentenceTransformerModel._backend`~~ — attribute does not exist yet

---

## Implementation Notes

### Pattern to Follow

```python
# In __init__, accept the new params:
def __init__(self, model_name, matryoshka=None, backend=None, file_name=None, **kwargs):
    self._backend = backend
    self._file_name = file_name
    ...

# In _create_embedding(), forward to SentenceTransformer constructor:
def _create_embedding(self, model_name=None, **kwargs):
    ...
    st_kwargs = {
        "device": self.device,
        "cache_folder": ...,
    }
    if self._backend:
        st_kwargs["backend"] = self._backend
    if self._file_name:
        st_kwargs["model_kwargs"] = {"file_name": self._file_name}
    model = SentenceTransformer(model_name, **st_kwargs)
```

### Key Constraints

- `backend` param is optional — `None` means default torch behavior (backward compatible).
- `file_name` is for specifying quantized model files (e.g., `model_quantized.onnx`).
- The `sentence-transformers` library passes `backend` directly to its constructor; `file_name` goes via `model_kwargs`.
- MUST NOT break any existing embedding usage — all current code passes neither param.

### References in Codebase

- `packages/ai-parrot-embeddings/src/parrot/embeddings/huggingface.py` — main edit target
- `packages/ai-parrot/src/parrot/embeddings/registry.py` — `get_or_create()` passes **kwargs through to model constructor

---

## Acceptance Criteria

- [ ] `SentenceTransformerModel.__init__` accepts `backend` and `file_name` kwargs
- [ ] `_create_embedding()` forwards `backend` to `SentenceTransformer()` constructor
- [ ] `_create_embedding()` forwards `file_name` via `model_kwargs`
- [ ] Default behavior (no backend/file_name) is unchanged
- [ ] Unit tests pass: `pytest tests/embeddings/test_st_backend_kwarg.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-embeddings/src/parrot/embeddings/huggingface.py`

---

## Test Specification

```python
# tests/embeddings/test_st_backend_kwarg.py
import pytest
from unittest.mock import patch, MagicMock


class TestSentenceTransformerBackend:
    @patch("parrot.embeddings.huggingface.SentenceTransformer")
    def test_backend_kwarg_forwarded(self, mock_st_class):
        """_create_embedding passes backend to SentenceTransformer."""
        from parrot.embeddings.huggingface import SentenceTransformerModel
        model = SentenceTransformerModel("test/model", backend="onnx")
        model._create_embedding("test/model")
        call_kwargs = mock_st_class.call_args
        assert call_kwargs.kwargs.get("backend") == "onnx" or \
               (len(call_kwargs.args) > 1 and "onnx" in str(call_kwargs))

    @patch("parrot.embeddings.huggingface.SentenceTransformer")
    def test_file_name_kwarg_forwarded(self, mock_st_class):
        """_create_embedding passes file_name via model_kwargs."""
        from parrot.embeddings.huggingface import SentenceTransformerModel
        model = SentenceTransformerModel("test/model", file_name="model_quantized.onnx")
        model._create_embedding("test/model")
        call_kwargs = mock_st_class.call_args
        # file_name should appear in model_kwargs
        assert "model_quantized.onnx" in str(call_kwargs)

    @patch("parrot.embeddings.huggingface.SentenceTransformer")
    def test_no_backend_default_unchanged(self, mock_st_class):
        """Without backend, SentenceTransformer called without backend kwarg."""
        from parrot.embeddings.huggingface import SentenceTransformerModel
        model = SentenceTransformerModel("test/model")
        model._create_embedding("test/model")
        call_kwargs = mock_st_class.call_args
        assert "backend" not in (call_kwargs.kwargs or {})
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/pageindex-embedding-router.spec.md` for full context
2. **Check dependencies** — verify TASK-1544 is in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — read `huggingface.py` to confirm `_create_embedding` signature
4. **Update status** in `sdd/tasks/index/pageindex-embedding-router.json` → `"in-progress"`
5. **Implement** following the scope and contract above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1545-st-model-backend-kwarg.md`
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
**Notes**: Added `backend: Optional[str] = None` and `file_name: Optional[str] = None` to `SentenceTransformerModel.__init__`. Both are stored as `self._backend` and `self._file_name` before super().__init__(). In `_create_embedding()`, `backend` is forwarded directly to `SentenceTransformer()` via `st_kwargs`, and `file_name` is forwarded via `st_kwargs["model_kwargs"] = {"file_name": ...}`. All 7 unit tests pass.

**Deviations from spec**: Tests patch `sentence_transformers.SentenceTransformer` directly (not `parrot.embeddings.huggingface.SentenceTransformer`) because `SentenceTransformer` is loaded via `lazy_import()` at call time, not as a module-level attribute. This is functionally equivalent and correctly tests the forwarding behavior.
