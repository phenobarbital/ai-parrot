---
type: Wiki Overview
title: 'TASK-1490: Multimodal Embedding Integration Tests'
id: doc:sdd-tasks-active-task-1490-integration-tests-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This task writes the integration test suite that validates the full multimodal
relates_to:
- concept: mod:parrot.embeddings.multimodal
  rel: mentions
- concept: mod:parrot.embeddings.multimodal.quantization
  rel: mentions
- concept: mod:parrot.embeddings.registry
  rel: mentions
- concept: mod:parrot.stores.models
  rel: mentions
- concept: mod:parrot.stores.multimodal_schema
  rel: mentions
---

# TASK-1490: Multimodal Embedding Integration Tests

**Feature**: FEAT-229 — Multimodal Embedding Provider
**Spec**: `sdd/specs/multimodal-embedding-provider.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1487, TASK-1488
**Assigned-to**: unassigned

---

## Context

This task writes the integration test suite that validates the full multimodal
embedding pipeline end-to-end: cross-modal sanity (text<->image pair similarity),
ONNX/torch agreement, async non-blocking verification, PgVector quantized
round-trip, and the embed_documents routing. These tests are the acceptance
criteria evidence for the feature.

Implements spec §4 (Test Specification — Integration Tests) and §5 (Acceptance Criteria).

---

## Scope

- Create `tests/embeddings/test_uform_integration.py` with:
  - **Cross-modal sanity**: known text<->image pair scores higher cosine than
    mismatched pair.
  - **Shared space dimension**: text and image embeddings have identical dimension.
  - **ONNX/torch agreement**: ONNX vs torch embeddings cosine >= 0.999 on fixed sample
    (skip if ONNX not available).
  - **Async non-blocking**: embed_* does not block the event loop (use asyncio
    debug mode or measure event loop lag).
  - **Registry integration**: `EmbeddingRegistry.get_or_create(name, 'multimodal')`
    returns `UFormEmbedding` instance (extends test from TASK-1487).
  - **Matryoshka recall curve**: Recall@10 at multiple dim levels (regression guard).
  - **embed_documents routing**: text-only docs go through embed_text, image-ref
    docs through embed_images.
- Create `tests/stores/test_multimodal_pgvector_integration.py` with:
  - **PgVector round-trip**: store multimodal embeddings, search, retrieve with
    correct modality filter.
  - **Quantized round-trip**: f16/i8/b1 embeddings round-trip through pgvector.
- Add test fixtures: `tests/fixtures/red_apple.jpg` (tiny test image).
- Ensure all tests are properly marked with `pytest.mark.asyncio` and skip
  conditions for optional deps (uform, asyncpg, pgvector).

**NOT in scope**: performance benchmarking (TASK-1489), modifying implementation code.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/embeddings/test_uform_integration.py` | CREATE | Embedding integration tests |
| `tests/stores/test_multimodal_pgvector_integration.py` | CREATE | PgVector integration tests |
| `tests/fixtures/red_apple.jpg` | CREATE | Tiny test image fixture (224x224 RGB) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.embeddings.multimodal import (  # created in TASK-1484/1486
    MultimodalEmbedding, UFormEmbedding, EmbeddingResult,
    EmbeddingBackend, QuantizationMode, ImageInput, resolve_image,
)
from parrot.embeddings.multimodal.quantization import (  # created in TASK-1485
    matryoshka_slice, l2_normalize, quantize,
)
from parrot.embeddings.registry import EmbeddingRegistry  # verified: packages/ai-parrot/src/parrot/embeddings/registry.py:51
from parrot.stores.models import Document  # verified: packages/ai-parrot/src/parrot/stores/models.py:40
from parrot.stores.multimodal_schema import define_multimodal_collection  # created in TASK-1488
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/embeddings/registry.py
class EmbeddingRegistry:                               # line 51
    async def get_or_create(self, model_name, model_type="huggingface", **kwargs) -> Any:  # line 218
    async def unload(self, model_name, model_type="huggingface") -> bool:  # line 301

# packages/ai-parrot/src/parrot/stores/models.py
class Document(BaseModel):                             # line 40
    page_content: str                                  # line 45
    metadata: Dict[str, Any]                           # line 46
```

### Does NOT Exist
- ~~`Document.image_url`~~ / ~~`Document.image_bytes`~~ — NO image fields on Document; use `metadata['image_path']`
- ~~`EmbeddingModel.embed_images()`~~ — only on `MultimodalEmbedding`, not the base class
- ~~`PgVectorStore.multimodal_search()`~~ — use the helpers from `multimodal_schema.py` (TASK-1488)

---

## Implementation Notes

### Key Constraints
- All integration tests should have skip conditions for optional dependencies:
  ```python
  uform = pytest.importorskip("uform")
  asyncpg = pytest.importorskip("asyncpg")  # for PgVector tests
  ```
- Cross-modal sanity test needs a known text-image pair where the semantic
  match is strong (e.g., "a red apple on a table" + image of a red apple).
  Use the fixture image `tests/fixtures/red_apple.jpg`.
- Generate the fixture image programmatically if a real photo is not available
  (PIL.Image with red pixels is sufficient for the encode path; the sanity
  assertion may be weak but the test validates the pipeline).
- ONNX/torch agreement test compares cosine similarity of embeddings from
  both backends on the same input. Skip if `onnxruntime` not installed.
- Async non-blocking test: use `asyncio` debug mode which warns if the event
  loop is blocked for >100ms, or measure wall-clock of concurrent coroutines.
- PgVector tests require a running PostgreSQL with pgvector extension.
  Use environment variable `TEST_PGVECTOR_DSN` for the connection string.
  Skip if not available.

### References in Codebase
- `packages/ai-parrot-embeddings/src/parrot/embeddings/huggingface.py` — existing test patterns
- Spec §4 (Test Specification) — full test matrix

---

## Acceptance Criteria

- [ ] Cross-modal sanity test: matching text-image pair cosine > mismatched pair cosine
- [ ] Shared dimension test: text_result.dimension == image_result.dimension
- [ ] ONNX/torch agreement: cosine >= 0.999 (or skipped if ONNX unavailable)
- [ ] Async non-blocking verification passes
- [ ] Registry integration: `get_or_create` returns `UFormEmbedding`
- [ ] Matryoshka dimensions produce correct output shapes
- [ ] embed_documents routes text and image docs correctly
- [ ] PgVector round-trip: store and retrieve multimodal embeddings
- [ ] Quantized round-trip: f16/i8/b1 survive store + retrieve
- [ ] All tests pass: `pytest tests/embeddings/test_uform_integration.py tests/stores/test_multimodal_pgvector_integration.py -v`
- [ ] Tests skip gracefully when optional deps are missing

---

## Test Specification

```python
# tests/embeddings/test_uform_integration.py
import pytest
import numpy as np

uform = pytest.importorskip("uform")

from parrot.embeddings.multimodal import (
    UFormEmbedding, EmbeddingBackend, QuantizationMode,
)
from parrot.stores.models import Document
from PIL import Image


@pytest.fixture
def provider():
    return UFormEmbedding(backend=EmbeddingBackend.TORCH)


class TestCrossModalSanity:
    @pytest.mark.asyncio
    async def test_matching_pair_scores_higher(self, provider):
        await provider.initialize_model()
        text_result = await provider.embed_text(["a red apple on a wooden table"])
        img = Image.open("tests/fixtures/red_apple.jpg")
        img_result = await provider.embed_images([img])
        # Mismatched text
        mismatch = await provider.embed_text(["a blue car in a parking lot"])
        match_cos = np.dot(text_result.embeddings[0], img_result.embeddings[0])
        mismatch_cos = np.dot(mismatch.embeddings[0], img_result.embeddings[0])
        assert match_cos > mismatch_cos


class TestSharedDimension:
    @pytest.mark.asyncio
    async def test_text_image_same_dim(self, provider):
        await provider.initialize_model()
        text = await provider.embed_text(["test"])
        img = await provider.embed_images([Image.new("RGB", (224, 224))])
        assert text.dimension == img.dimension


class TestOnnxTorchAgreement:
    @pytest.mark.asyncio
    async def test_cosine_agreement(self):
        onnxruntime = pytest.importorskip("onnxruntime")
        torch_prov = UFormEmbedding(backend=EmbeddingBackend.TORCH)
        onnx_prov = UFormEmbedding(backend=EmbeddingBackend.ONNX)
        await torch_prov.initialize_model()
        await onnx_prov.initialize_model()
        t1 = await torch_prov.embed_text(["hello world"])
        t2 = await onnx_prov.embed_text(["hello world"])
        cos = np.dot(t1.embeddings[0], t2.embeddings[0])
        assert cos >= 0.999


class TestAsyncNonBlocking:
    @pytest.mark.asyncio
    async def test_does_not_block_loop(self, provider):
        import asyncio
        await provider.initialize_model()
        # Run embedding and a timer concurrently — timer should not be starved
        start = asyncio.get_event_loop().time()
        timer_ran = asyncio.Event()
        async def timer():
            await asyncio.sleep(0.01)
            timer_ran.set()
        await asyncio.gather(
            provider.embed_text(["test query"]),
            timer(),
        )
        assert timer_ran.is_set()


class TestEmbedDocumentsRouting:
    @pytest.mark.asyncio
    async def test_text_only_docs(self, provider):
        await provider.initialize_model()
        docs = [Document(page_content="hello", metadata={})]
        result = await provider.embed_documents(docs)
        assert result.modality == "text"

    @pytest.mark.asyncio
    async def test_image_docs(self, provider):
        await provider.initialize_model()
        docs = [Document(page_content="", metadata={"image_path": "tests/fixtures/red_apple.jpg"})]
        result = await provider.embed_documents(docs)
        assert result.modality in ("image", "mixed")
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-1487 and TASK-1488 are in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm all imports from prior tasks are available
4. **Create test fixtures** — generate `tests/fixtures/red_apple.jpg` programmatically
   if a real image is not available
5. **Update status** in `sdd/tasks/index/multimodal-embedding-provider.json` → `"in-progress"`
6. **Implement** following the scope, codebase contract, and notes above
7. **Run all tests** and verify they pass (or skip gracefully for missing deps)
8. **Move this file** to `sdd/tasks/completed/TASK-1490-integration-tests.md`
9. **Update index** → `"done"`
10. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
