---
type: Wiki Overview
title: 'TASK-1486: UForm Embedding Provider'
id: doc:sdd-tasks-active-task-1486-uform-provider-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This task implements `UFormEmbedding`, the first concrete multimodal embedding
relates_to:
- concept: mod:parrot.embeddings.base
  rel: mentions
- concept: mod:parrot.embeddings.multimodal
  rel: mentions
- concept: mod:parrot.embeddings.multimodal.base
  rel: mentions
- concept: mod:parrot.embeddings.multimodal.quantization
  rel: mentions
- concept: mod:parrot.embeddings.multimodal.uform
  rel: mentions
---

# TASK-1486: UForm Embedding Provider

**Feature**: FEAT-229 — Multimodal Embedding Provider
**Spec**: `sdd/specs/multimodal-embedding-provider.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1484, TASK-1485
**Assigned-to**: unassigned

---

## Context

This task implements `UFormEmbedding`, the first concrete multimodal embedding
provider. It wraps UForm's CLIP-style encoders with dual backend support (torch
for dev/GPU, ONNX for Knative serving). This is the core deliverable of the
feature — the abstraction (TASK-1484) and post-processing (TASK-1485) exist to
support this provider and future ones.

Implements spec §3 (Module 3).

---

## Scope

- Create `packages/ai-parrot/src/parrot/embeddings/multimodal/uform.py` with:
  - `UFormEmbedding(MultimodalEmbedding)` class
  - Constructor: `model_name` (default: `"unum-cloud/uform3-image-text-multilingual-base"`),
    `backend: EmbeddingBackend` (default: `TORCH`), `output_dim`, `quantization`, `**kwargs`
  - `_create_embedding(model_name, **kwargs)` — loads model:
    - Torch: `uform.get_model(model_name)` → returns `(model, processor)`
    - ONNX: `uform.get_model_onnx(model_name)` or equivalent ONNX session loading
  - `encode(texts, **kwargs)` — text encoding via `run_in_executor`
  - `embed_text(texts)` — encode text batch, run `_postprocess`, return `EmbeddingResult`
  - `embed_images(images)` — resolve images, encode batch, run `_postprocess`, return `EmbeddingResult`
- Ensure all sync inference calls use `self.executor` + `run_in_executor` (inherited from `EmbeddingModel`)
- Add basic integration test (requires `uform` installed)
- Update `multimodal/__init__.py` to export `UFormEmbedding`

**NOT in scope**: registry/catalog integration (TASK-1487), PgVector schema (TASK-1488),
benchmark (TASK-1489).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/embeddings/multimodal/uform.py` | CREATE | UFormEmbedding class |
| `packages/ai-parrot/src/parrot/embeddings/multimodal/__init__.py` | MODIFY | Export `UFormEmbedding` |
| `tests/embeddings/test_uform_embedding.py` | CREATE | Unit + integration tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.embeddings.base import EmbeddingModel  # verified: packages/ai-parrot/src/parrot/embeddings/base.py:15
from parrot.embeddings.multimodal.base import (  # created in TASK-1484
    MultimodalEmbedding, EmbeddingResult, EmbeddingBackend,
    QuantizationMode, ImageInput, resolve_image,
)
from parrot.embeddings.multimodal.quantization import (  # created in TASK-1485
    matryoshka_slice, l2_normalize, quantize,
)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/embeddings/base.py
class EmbeddingModel(ABC):                           # line 15
    def __init__(self, model_name: str, **kwargs):   # line 20
        self.executor: ThreadPoolExecutor            # line 23 — max_workers=4
        self._model_lock: asyncio.Lock               # line 24
        self._dimension: Optional[int]               # line 25

    async def initialize_model(self) -> None:         # line 136
    @abstractmethod
    def _create_embedding(self, model_name: str, **kwargs) -> Any:  # line 162
    @abstractmethod
    async def encode(self, texts: List[str], **kwargs) -> np.ndarray:  # line 225
    def free(self) -> None:                           # line 216

# packages/ai-parrot-embeddings/src/parrot/embeddings/huggingface.py — PATTERN REFERENCE
class SentenceTransformerModel(EmbeddingModel):       # line 111
    async def encode(self, texts: List[str], **kwargs) -> np.ndarray:  # line 383
        raw_model = self.model
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self.executor,
            lambda: raw_model.encode(texts, **kwargs)
        )
```

### Does NOT Exist
- ~~`uform.get_model_onnx()`~~ — verify UForm's actual ONNX API; may be `uform.get_model(..., backend="onnx")` or `onnxruntime.InferenceSession` directly
- ~~`EmbeddingModel._postprocess()`~~ — not on the base class; inherited from `MultimodalEmbedding` (TASK-1484)
- ~~`UFormEmbedding` anywhere in codebase~~ — does not exist yet; this task creates it
- ~~`parrot.embeddings.multimodal.uform`~~ — does not exist yet

---

## Implementation Notes

### Pattern to Follow
```python
# Follow SentenceTransformerModel.encode() pattern (huggingface.py:383-392):
class UFormEmbedding(MultimodalEmbedding):
    def __init__(self, model_name="unum-cloud/uform3-image-text-multilingual-base",
                 backend=EmbeddingBackend.TORCH, output_dim=None,
                 quantization=QuantizationMode.F32, **kwargs):
        super().__init__(model_name, output_dim=output_dim,
                        quantization=quantization, **kwargs)
        self._backend = backend

    def _create_embedding(self, model_name, **kwargs):
        # Torch path:
        import uform
        model, processor = uform.get_model(model_name)
        self._processor = processor
        self._dimension = model.config.embedding_dim  # verify actual attribute
        return model

    async def encode(self, texts, **kwargs):
        model = self.model  # triggers lazy init via registry
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self.executor,
            lambda: self._encode_text_sync(model, texts)
        )

    def _encode_text_sync(self, model, texts):
        # Use UForm's processor + model to encode text
        inputs = self._processor(text=texts, ...)
        features = model.encode_text(inputs)  # verify actual API
        return features.detach().cpu().numpy()

    async def embed_text(self, texts):
        raw = await self.encode(texts)
        processed = self._postprocess(raw)
        return EmbeddingResult(embeddings=processed, dimension=processed.shape[-1],
                              quantization=self._quantization, modality="text")
```

### Key Constraints
- **CRITICAL**: Verify UForm's actual Python API before implementing. The UForm README
  and HuggingFace page are the authoritative references. Key things to check:
  - `uform.get_model()` return type and signature
  - How to encode text vs images (separate methods? single method with modality flag?)
  - How to get embedding dimension from the model config
  - ONNX backend loading mechanism
- All sync inference must go through `run_in_executor` — never block the event loop
- UForm returns features that need L2 normalization — apply via `_postprocess()`
- The `_create_embedding()` method is sync (called by `initialize_model()` in a thread pool)
- Store `_processor` as instance attribute for tokenization/image preprocessing
- Support both multilingual-base (206M) and english-large (365M) model variants

### References in Codebase
- `packages/ai-parrot-embeddings/src/parrot/embeddings/huggingface.py:111-392` — `SentenceTransformerModel` pattern
- `packages/ai-parrot/src/parrot/embeddings/base.py:136-159` — `initialize_model()` lifecycle

---

## Acceptance Criteria

- [ ] `UFormEmbedding` instantiates with default model name and backend
- [ ] `_create_embedding()` loads UForm model (torch backend)
- [ ] `embed_text()` returns `EmbeddingResult` with correct shape and modality="text"
- [ ] `embed_images()` returns `EmbeddingResult` with correct shape and modality="image"
- [ ] Text and image embeddings share the same dimension
- [ ] Async non-blocking: encode uses `run_in_executor`
- [ ] `_postprocess()` is applied (Matryoshka slice + normalize + quantize)
- [ ] ONNX backend loads if `onnxruntime` is available
- [ ] `free()` releases model resources
- [ ] All tests pass: `pytest tests/embeddings/test_uform_embedding.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/embeddings/multimodal/`

---

## Test Specification

```python
# tests/embeddings/test_uform_embedding.py
import pytest
import numpy as np

uform = pytest.importorskip("uform")

from parrot.embeddings.multimodal import (
    UFormEmbedding, EmbeddingBackend, QuantizationMode,
)


@pytest.fixture
def uform_provider():
    return UFormEmbedding(
        model_name="unum-cloud/uform3-image-text-multilingual-base",
        backend=EmbeddingBackend.TORCH,
    )


class TestUFormText:
    @pytest.mark.asyncio
    async def test_embed_text_shape(self, uform_provider):
        await uform_provider.initialize_model()
        result = await uform_provider.embed_text(["hello world", "test query"])
        assert result.embeddings.shape[0] == 2
        assert result.modality == "text"
        assert result.dimension == result.embeddings.shape[1]

    @pytest.mark.asyncio
    async def test_embed_text_normalized(self, uform_provider):
        await uform_provider.initialize_model()
        result = await uform_provider.embed_text(["test"])
        norms = np.linalg.norm(result.embeddings, axis=-1)
        np.testing.assert_allclose(norms, 1.0, atol=1e-5)


class TestUFormImages:
    @pytest.mark.asyncio
    async def test_embed_images_shape(self, uform_provider):
        from PIL import Image
        await uform_provider.initialize_model()
        img = Image.new("RGB", (224, 224))
        result = await uform_provider.embed_images([img])
        assert result.embeddings.shape[0] == 1
        assert result.modality == "image"

    @pytest.mark.asyncio
    async def test_crossmodal_shared_dim(self, uform_provider):
        from PIL import Image
        await uform_provider.initialize_model()
        text_result = await uform_provider.embed_text(["a cat"])
        img = Image.new("RGB", (224, 224))
        img_result = await uform_provider.embed_images([img])
        assert text_result.dimension == img_result.dimension


class TestUFormMatryoshka:
    @pytest.mark.asyncio
    async def test_output_dim_truncation(self):
        provider = UFormEmbedding(output_dim=256)
        await provider.initialize_model()
        result = await provider.embed_text(["test"])
        assert result.dimension == 256
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-1484 and TASK-1485 are in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - **CRITICAL**: Read UForm's actual API before implementing. Run:
     `pip show uform` and read its README/source to verify `get_model()`, encode methods, etc.
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/multimodal-embedding-provider.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1486-uform-provider.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
