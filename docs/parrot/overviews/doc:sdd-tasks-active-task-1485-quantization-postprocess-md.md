---
type: Wiki Overview
title: 'TASK-1485: Quantization & Matryoshka Post-processing'
id: doc:sdd-tasks-active-task-1485-quantization-postprocess-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'This task implements the shared post-processing pipeline for multimodal
  embeddings:'
relates_to:
- concept: mod:parrot.embeddings
  rel: mentions
- concept: mod:parrot.embeddings.base
  rel: mentions
- concept: mod:parrot.embeddings.matryoshka
  rel: mentions
- concept: mod:parrot.embeddings.multimodal
  rel: mentions
- concept: mod:parrot.embeddings.multimodal.base
  rel: mentions
- concept: mod:parrot.embeddings.multimodal.quantization
  rel: mentions
---

# TASK-1485: Quantization & Matryoshka Post-processing

**Feature**: FEAT-229 — Multimodal Embedding Provider
**Spec**: `sdd/specs/multimodal-embedding-provider.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1484
**Assigned-to**: unassigned

---

## Context

This task implements the shared post-processing pipeline for multimodal embeddings:
Matryoshka dimension slicing, L2 renormalization, and quantization (f32/f16/i8/b1).
This logic lives in the base class and is model-agnostic — any `MultimodalEmbedding`
subclass reuses it.

Implements spec §3 (Module 2) and draws on the existing `_apply_matryoshka()` pattern
from `SentenceTransformerModel`.

---

## Scope

- Create `packages/ai-parrot/src/parrot/embeddings/multimodal/quantization.py` with:
  - `matryoshka_slice(embeddings: np.ndarray, dim: int) -> np.ndarray` — slice leading N dims
  - `l2_normalize(embeddings: np.ndarray) -> np.ndarray` — L2 renormalization
  - `quantize(embeddings: np.ndarray, mode: QuantizationMode) -> np.ndarray` — quantize:
    - `F32`: passthrough
    - `F16`: `embeddings.astype(np.float16)`
    - `I8`: `(embeddings * 127).astype(np.int8)`
    - `B1`: `np.packbits(embeddings > 0)`
  - `PGVECTOR_TYPE_MAP: dict[QuantizationMode, str]` — maps mode to pgvector column type:
    - `F32 -> "vector"`, `F16 -> "halfvec"`, `I8 -> "halfvec"`, `B1 -> "bit"`
- Wire `_postprocess()` in `MultimodalEmbedding` (update `base.py`) to call:
  `matryoshka_slice` -> `l2_normalize` -> `quantize` in sequence.
- Write unit tests for each step and the full chain.

**NOT in scope**: UForm-specific code (TASK-1486), PgVector schema (TASK-1488).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/embeddings/multimodal/quantization.py` | CREATE | Slice, normalize, quantize utilities + pgvector type map |
| `packages/ai-parrot/src/parrot/embeddings/multimodal/base.py` | MODIFY | Wire `_postprocess()` to call quantization pipeline |
| `packages/ai-parrot/src/parrot/embeddings/multimodal/__init__.py` | MODIFY | Export new symbols |
| `tests/embeddings/test_quantization.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.embeddings.multimodal.base import MultimodalEmbedding, QuantizationMode  # created in TASK-1484
from parrot.embeddings.matryoshka import MatryoshkaConfig, validate_against_catalog  # verified: packages/ai-parrot/src/parrot/embeddings/matryoshka.py:36,74
```

### Existing Signatures to Use
```python
# packages/ai-parrot-embeddings/src/parrot/embeddings/huggingface.py — PATTERN REFERENCE ONLY
# (Do NOT import from here; extract the logic pattern into quantization.py)
class SentenceTransformerModel(EmbeddingModel):
    def _apply_matryoshka(self, vectors) -> np.ndarray | list:  # line 225
        # Pattern: slice leading dims, L2 renormalize
        # arr[..., :dim] -> norms -> normalized = sliced / norms
        ...

# packages/ai-parrot/src/parrot/embeddings/matryoshka.py
class MatryoshkaConfig(BaseModel):                    # line 36
    enabled: bool = False                             # line 54
    dimension: Optional[int] = Field(default=None, gt=0)  # line 55
```

### Does NOT Exist
- ~~`parrot.embeddings.quantization`~~ — does not exist; the new module is `parrot.embeddings.multimodal.quantization`
- ~~`parrot.embeddings.base.EmbeddingModel._postprocess()`~~ — not on the base class; added by `MultimodalEmbedding` (TASK-1484)
- ~~`pgvector.sqlalchemy.HalfVector`~~ — verify availability before using; current code only uses `Vector`
- ~~`pgvector.sqlalchemy.Bit`~~ — verify availability before using

---

## Implementation Notes

### Pattern to Follow
```python
# Extract the Matryoshka pattern from huggingface.py:225-263:
def matryoshka_slice(embeddings: np.ndarray, dim: int) -> np.ndarray:
    return embeddings[..., :dim]

def l2_normalize(embeddings: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(embeddings, axis=-1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    return embeddings / norms

def quantize(embeddings: np.ndarray, mode: QuantizationMode) -> np.ndarray:
    if mode == QuantizationMode.F32:
        return embeddings.astype(np.float32)
    elif mode == QuantizationMode.F16:
        return embeddings.astype(np.float16)
    elif mode == QuantizationMode.I8:
        return (embeddings * 127).astype(np.int8)
    elif mode == QuantizationMode.B1:
        return np.packbits(embeddings > 0, axis=-1)
```

### Key Constraints
- Matryoshka slicing happens BEFORE normalization (slice -> renormalize)
- L2 normalization must handle zero vectors (replace norm 0 with 1.0)
- B1 quantization changes the shape (packbits reduces last dim by 8x) — document this
- `_postprocess()` in `MultimodalEmbedding` should: skip slice if `output_dim is None`, always normalize, then quantize
- All functions are pure (no side effects, no state)

### References in Codebase
- `packages/ai-parrot-embeddings/src/parrot/embeddings/huggingface.py:225-263` — `_apply_matryoshka()` pattern
- `packages/ai-parrot/src/parrot/embeddings/matryoshka.py` — config + validation

---

## Acceptance Criteria

- [ ] `matryoshka_slice()` correctly truncates to leading N dims
- [ ] `l2_normalize()` produces unit vectors (norm == 1.0 within tolerance)
- [ ] `l2_normalize()` handles zero vectors without NaN
- [ ] `quantize()` F32 passthrough, F16 dtype check, I8 range [-127, 127], B1 packbits correct length
- [ ] `PGVECTOR_TYPE_MAP` maps all 4 modes to correct pgvector column types
- [ ] `_postprocess()` in `MultimodalEmbedding` chains slice -> normalize -> quantize correctly
- [ ] All tests pass: `pytest tests/embeddings/test_quantization.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/embeddings/multimodal/`

---

## Test Specification

```python
# tests/embeddings/test_quantization.py
import pytest
import numpy as np
from parrot.embeddings.multimodal.quantization import (
    matryoshka_slice, l2_normalize, quantize, PGVECTOR_TYPE_MAP,
)
from parrot.embeddings.multimodal import QuantizationMode


class TestMatryoshkaSlice:
    def test_truncates_dims(self):
        emb = np.random.randn(5, 768).astype(np.float32)
        sliced = matryoshka_slice(emb, 256)
        assert sliced.shape == (5, 256)

    def test_preserves_leading_values(self):
        emb = np.arange(768, dtype=np.float32).reshape(1, 768)
        sliced = matryoshka_slice(emb, 64)
        np.testing.assert_array_equal(sliced[0], np.arange(64, dtype=np.float32))


class TestL2Normalize:
    def test_unit_vectors(self):
        emb = np.random.randn(5, 256).astype(np.float32)
        normed = l2_normalize(emb)
        norms = np.linalg.norm(normed, axis=-1)
        np.testing.assert_allclose(norms, 1.0, atol=1e-6)

    def test_zero_vector(self):
        emb = np.zeros((1, 256), dtype=np.float32)
        normed = l2_normalize(emb)
        assert not np.any(np.isnan(normed))


class TestQuantize:
    def test_f32_passthrough(self):
        emb = np.random.randn(3, 256).astype(np.float32)
        result = quantize(emb, QuantizationMode.F32)
        assert result.dtype == np.float32

    def test_f16_downcast(self):
        emb = np.random.randn(3, 256).astype(np.float32)
        result = quantize(emb, QuantizationMode.F16)
        assert result.dtype == np.float16

    def test_i8_range(self):
        emb = l2_normalize(np.random.randn(3, 256).astype(np.float32))
        result = quantize(emb, QuantizationMode.I8)
        assert result.dtype == np.int8
        assert result.min() >= -127
        assert result.max() <= 127

    def test_b1_packbits(self):
        emb = np.random.randn(3, 256).astype(np.float32)
        result = quantize(emb, QuantizationMode.B1)
        assert result.shape == (3, 32)  # 256 / 8


class TestPgvectorTypeMap:
    def test_all_modes_mapped(self):
        for mode in QuantizationMode:
            assert mode in PGVECTOR_TYPE_MAP
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-1484 is in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/multimodal-embedding-provider.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1485-quantization-postprocess.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
