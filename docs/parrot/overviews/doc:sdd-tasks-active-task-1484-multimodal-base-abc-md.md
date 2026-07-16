---
type: Wiki Overview
title: 'TASK-1484: Multimodal Embedding Base ABC & Enums'
id: doc:sdd-tasks-active-task-1484-multimodal-base-abc-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This is the foundation task for the multimodal embedding feature. It creates
  the
relates_to:
- concept: mod:parrot.embeddings.base
  rel: mentions
- concept: mod:parrot.embeddings.multimodal
  rel: mentions
- concept: mod:parrot.stores.models
  rel: mentions
---

# TASK-1484: Multimodal Embedding Base ABC & Enums

**Feature**: FEAT-229 — Multimodal Embedding Provider
**Spec**: `sdd/specs/multimodal-embedding-provider.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This is the foundation task for the multimodal embedding feature. It creates the
abstract interface (`MultimodalEmbedding`) that all future multimodal embedding
providers will implement, along with supporting types (enums, result dataclass,
image input type alias, image resolver utility).

Implements spec §2 (Architectural Design — Overview) and §3 (Module 1).

---

## Scope

- Create the `parrot/embeddings/multimodal/` package with `__init__.py` and `base.py`.
- Implement `MultimodalEmbedding(EmbeddingModel, ABC)` with:
  - `embed_text(texts: list[str]) -> EmbeddingResult` (abstract)
  - `embed_images(images: list[ImageInput]) -> EmbeddingResult` (abstract)
  - `embed_documents(docs: list[Document]) -> EmbeddingResult` (concrete — routes by modality)
  - `_postprocess(features: np.ndarray) -> np.ndarray` (stub — delegates to Module 2)
  - Constructor accepting `model_name`, `output_dim`, `quantization`, `**kwargs`.
- Implement supporting types:
  - `EmbeddingBackend(str, Enum)`: `TORCH = "torch"`, `ONNX = "onnx"`
  - `QuantizationMode(str, Enum)`: `F32`, `F16`, `I8`, `B1`
  - `ImageInput = Union[PIL.Image.Image, bytes, str]`
  - `EmbeddingResult` dataclass: `embeddings: np.ndarray`, `dimension: int`,
    `quantization: QuantizationMode`, `modality: str`
- Implement `resolve_image(input: ImageInput) -> PIL.Image.Image` utility:
  - `PIL.Image.Image` → passthrough
  - `bytes` → `Image.open(BytesIO(input))`
  - `str` → file path load via `Image.open(path)` (URL support deferred)
- Write unit tests for the ABC contract and image resolver.

**NOT in scope**: quantization logic (TASK-1485), UForm-specific code (TASK-1486),
registry integration (TASK-1487), PgVector schema (TASK-1488).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/embeddings/multimodal/__init__.py` | CREATE | Package init; export `MultimodalEmbedding`, `EmbeddingResult`, enums, `ImageInput`, `resolve_image` |
| `packages/ai-parrot/src/parrot/embeddings/multimodal/base.py` | CREATE | ABC + enums + dataclass + image resolver |
| `tests/embeddings/test_multimodal_base.py` | CREATE | Unit tests for ABC contract, enums, image resolver |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.embeddings.base import EmbeddingModel  # verified: packages/ai-parrot/src/parrot/embeddings/base.py:15
from parrot.stores.models import Document  # verified: packages/ai-parrot/src/parrot/stores/models.py:40
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/embeddings/base.py
class EmbeddingModel(ABC):                           # line 15
    def __init__(self, model_name: str, **kwargs):   # line 20
        self.model_name: str                         # line 21
        self.logger: Logger                          # line 22
        self.executor: ThreadPoolExecutor            # line 23 — max_workers=4
        self._model_lock: asyncio.Lock               # line 24
        self._dimension: Optional[int]               # line 25
        self._model: Any                             # line 27
        self._device: Any                            # line 28

    def get_embedding_dimension(self) -> int:         # line 133
    async def initialize_model(self) -> None:         # line 136
    @abstractmethod
    def _create_embedding(self, model_name: str, **kwargs) -> Any:  # line 162
    async def embed_documents(self, texts: List[str], batch_size: Optional[int] = None) -> List[List[float]]:  # line 169
    async def embed_query(self, text: str, as_nparray: bool = False) -> Union[List[float], List[np.ndarray]]:  # line 188
    def free(self) -> None:                           # line 216
    @abstractmethod
    async def encode(self, texts: List[str], **kwargs) -> np.ndarray:  # line 225

# packages/ai-parrot/src/parrot/stores/models.py
class Document(BaseModel):                            # line 40
    page_content: str                                 # line 45
    metadata: Dict[str, Any]                          # line 46
```

### Does NOT Exist
- ~~`parrot.embeddings.multimodal`~~ — does not exist yet; this task creates it
- ~~`Document.image_url`~~ / ~~`Document.image_bytes`~~ / ~~`Document.media`~~ — Document has NO image fields; images are referenced via `metadata` dict keys (e.g. `metadata['image_path']`)
- ~~`EmbeddingModel.embed_images()`~~ — not a method on the base class; new in this task
- ~~`parrot.embeddings.base.MultimodalEmbedding`~~ — does not exist; create in `multimodal/base.py`

---

## Implementation Notes

### Pattern to Follow
```python
# Follow the EmbeddingModel ABC pattern from base.py:15
# MultimodalEmbedding extends it, adding modality-aware methods:
class MultimodalEmbedding(EmbeddingModel, ABC):
    def __init__(self, model_name: str, output_dim: Optional[int] = None,
                 quantization: QuantizationMode = QuantizationMode.F32, **kwargs):
        super().__init__(model_name, **kwargs)
        self._output_dim = output_dim
        self._quantization = quantization

    async def embed_documents(self, docs: list[Document]) -> EmbeddingResult:
        # Route: docs with image refs -> embed_images; text-only -> embed_text
        ...
```

### Key Constraints
- `MultimodalEmbedding` must call `super().__init__()` to get executor, model_lock, logger
- `embed_documents()` checks `metadata.get('image_path')` or `metadata.get('image_url')` to detect image docs
- `_postprocess()` is a stub in this task — returns features unchanged. TASK-1485 implements the real logic.
- Image resolver must NOT be called in the encode hot path — resolve all images upfront in `embed_images()`
- All `embed_*` methods are `async`

### References in Codebase
- `packages/ai-parrot/src/parrot/embeddings/base.py` — base class to extend
- `packages/ai-parrot/src/parrot/stores/models.py:40` — Document model

---

## Acceptance Criteria

- [ ] `MultimodalEmbedding` cannot be instantiated directly (ABC)
- [ ] Subclass must implement `embed_text`, `embed_images`, `_create_embedding`, `encode`
- [ ] `EmbeddingResult` holds `embeddings`, `dimension`, `quantization`, `modality`
- [ ] `EmbeddingBackend` and `QuantizationMode` enums have correct values
- [ ] `resolve_image()` handles PIL.Image, bytes, and file path inputs
- [ ] `embed_documents()` routes text-only docs to `embed_text` and image docs to `embed_images`
- [ ] All tests pass: `pytest tests/embeddings/test_multimodal_base.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/embeddings/multimodal/`
- [ ] Imports work: `from parrot.embeddings.multimodal import MultimodalEmbedding, EmbeddingResult, EmbeddingBackend, QuantizationMode, ImageInput, resolve_image`

---

## Test Specification

```python
# tests/embeddings/test_multimodal_base.py
import pytest
import numpy as np
from PIL import Image
from io import BytesIO
from parrot.embeddings.multimodal import (
    MultimodalEmbedding, EmbeddingResult, EmbeddingBackend,
    QuantizationMode, ImageInput, resolve_image,
)
from parrot.stores.models import Document


class TestMultimodalABC:
    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            MultimodalEmbedding(model_name="test")

    def test_subclass_must_implement_abstract(self):
        class Incomplete(MultimodalEmbedding):
            pass
        with pytest.raises(TypeError):
            Incomplete(model_name="test")


class TestEnums:
    def test_embedding_backend_values(self):
        assert EmbeddingBackend.TORCH == "torch"
        assert EmbeddingBackend.ONNX == "onnx"

    def test_quantization_mode_values(self):
        assert QuantizationMode.F32 == "f32"
        assert QuantizationMode.F16 == "f16"
        assert QuantizationMode.I8 == "i8"
        assert QuantizationMode.B1 == "b1"


class TestEmbeddingResult:
    def test_creation(self):
        emb = np.random.randn(3, 768).astype(np.float32)
        result = EmbeddingResult(
            embeddings=emb, dimension=768,
            quantization=QuantizationMode.F32, modality="text"
        )
        assert result.embeddings.shape == (3, 768)
        assert result.dimension == 768


class TestImageResolver:
    def test_pil_passthrough(self):
        img = Image.new("RGB", (224, 224))
        assert resolve_image(img) is img

    def test_bytes_decode(self):
        img = Image.new("RGB", (224, 224))
        buf = BytesIO()
        img.save(buf, format="PNG")
        result = resolve_image(buf.getvalue())
        assert isinstance(result, Image.Image)

    def test_invalid_path_raises(self):
        with pytest.raises((FileNotFoundError, OSError)):
            resolve_image("/nonexistent/path.jpg")
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — this task has no dependencies
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/multimodal-embedding-provider.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1484-multimodal-base-abc.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
