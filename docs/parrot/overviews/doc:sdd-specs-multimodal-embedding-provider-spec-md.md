---
type: Wiki Overview
title: 'Feature Specification: Multimodal Embedding Provider'
id: doc:sdd-specs-multimodal-embedding-provider-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: AI-Parrot's embedding layer is currently **text-only** (HuggingFace Transformers).
relates_to:
- concept: mod:parrot
  rel: mentions
- concept: mod:parrot.conf
  rel: mentions
- concept: mod:parrot.embeddings
  rel: mentions
- concept: mod:parrot.embeddings.base
  rel: mentions
- concept: mod:parrot.embeddings.catalog
  rel: mentions
- concept: mod:parrot.embeddings.matryoshka
  rel: mentions
- concept: mod:parrot.embeddings.multimodal
  rel: mentions
- concept: mod:parrot.embeddings.registry
  rel: mentions
- concept: mod:parrot.stores
  rel: mentions
- concept: mod:parrot.stores.abstract
  rel: mentions
- concept: mod:parrot.stores.models
  rel: mentions
- concept: mod:parrot.stores.pgvector
  rel: mentions
---

---
type: feature
base_branch: dev
---

# Feature Specification: Multimodal Embedding Provider

**Feature ID**: FEAT-229
**Date**: 2026-06-08
**Author**: jesuslarag
**Status**: approved
**Target version**: 1.x (next minor)

---

## 1. Motivation & Business Requirements

### Problem Statement

AI-Parrot's embedding layer is currently **text-only** (HuggingFace Transformers).
Several active domains require retrieving over content where the visual signal is
primary or co-equal with text:

- Epson planogram agents (image of shelf layout <-> textual product/spec query).
- `InfographicToolkit` outputs and source figures.
- Document loaders that today drop or OCR-flatten embedded images, losing
  layout/visual semantics.

A **multimodal embedding provider** is needed that maps text and images into a
shared vector space so PgVector can serve cross-modal retrieval (text->image,
image->text, image->image) under the existing conversational RAG flow — without
coupling embedding logic into loaders and without adding a heavy serving footprint
to Knative.

UForm (`unum-cloud/uform`, Apache-2.0, v3.1.4 / Oct-2025) is the candidate first
implementation: tiny CLIP-style encoders (64-768 dims, Matryoshka),
quantization-aware, native ONNX, multilingual base (21 langs incl. Spanish).

### Goals

- Provide a modality-aware embedding abstraction (`MultimodalEmbedding`) that
  future CLIP-family providers can plug into with zero churn.
- Ship UForm as the first concrete provider with torch + ONNX backend toggle for
  dev/GPU vs Knative serving footprints.
- Extend PgVector with a parallel multimodal collection supporting cross-modal
  retrieval (text<->image) via shared embedding space.
- Centralize Matryoshka slicing and quantization (f32/f16/i8/b1) as reusable
  post-processing in the base class, model-agnostic.
- Deliver a benchmark harness to decide whether UForm's multilingual text quality
  justifies adoption over the current text embedder.

### Non-Goals (explicitly out of scope)

- **NOT** a local reasoning LLM. UForm's generative models (captioning/VQA-grade)
  are out of scope. Local reasoning stays on the Ollama/vLLM track (separate FEAT).
- **NOT** replacing the text-only embedder for pure-text RAG by default. The
  benchmark decides; until then both coexist in parallel collections.
- **NOT** a new vector store. We extend PgVector; ArangoDB graph RAG is untouched.
- **NOT** a qworker/ToolWorkerService offload path. v1 uses `ThreadPoolExecutor`
  + `run_in_executor`. qworker integration is a follow-up FEAT.
- Runtime fallback-on-failure was rejected in brainstorm (Option A) — see
  `sdd/proposals/multimodal-embedding-provider-brainstorm.md`.

---

## 2. Architectural Design

### Overview

**Option C from brainstorm (recommended and approved):** Define a modality-aware
abstract interface (`MultimodalEmbedding`); `UFormEmbedding` is the first concrete
provider shipping with a torch/ONNX backend toggle. Quantization + Matryoshka
slicing live in the base as model-agnostic post-processing.

```
MultimodalEmbedding (ABC, extends EmbeddingModel)
  ├─ async embed_text(texts: list[str]) -> EmbeddingResult
  ├─ async embed_images(images: list[ImageInput]) -> EmbeddingResult
  ├─ async embed_documents(docs: list[Document]) -> EmbeddingResult  # routes by modality
  ├─ dim: int               # post-Matryoshka output dimension
  ├─ quantization: QuantizationMode
  └─ _postprocess(features) -> np.ndarray  # slice + downcast (shared logic)

UFormEmbedding(MultimodalEmbedding)
  ├─ backend: EmbeddingBackend  # torch | onnx
  └─ uses uform.get_model(...) / onnxruntime session
```

All outputs are L2-normalized at the base layer so `cosine == dot`. Text and
image embeddings share the same dimension and space for a given configured model,
enabling mixed-modality retrieval in PgVector.

**Registry integration:** registered as `'multimodal': 'UFormEmbedding'` in
`supported_embeddings`. The `EmbeddingRegistry` resolves `model_type='multimodal'`
to `parrot.embeddings.multimodal.UFormEmbedding`. Future multimodal providers
(Jina-CLIP, OpenCLIP) would either get their own keys or use a factory within
the `multimodal` package.

### Component Diagram

```
                    ┌──────────────────────────┐
                    │    EmbeddingRegistry      │
                    │ (singleton, LRU cache)    │
                    └──────────┬───────────────┘
                               │ get_or_create(name, "multimodal")
                               ▼
┌──────────────────────────────────────────────────┐
│          MultimodalEmbedding (ABC)                │
│  embed_text() / embed_images() / embed_documents()│
│  _postprocess(): Matryoshka slice + quantize      │
└────────────────────┬─────────────────────────────┘
                     │ extends
                     ▼
┌──────────────────────────────────────────────────┐
│            UFormEmbedding                         │
│  backend: EmbeddingBackend (torch | onnx)         │
│  _create_embedding(): loads uform model           │
│  encode(): dispatches to executor                 │
└────────────────────┬─────────────────────────────┘
                     │ stores embeddings
                     ▼
┌──────────────────────────────────────────────────┐
│         PgVectorStore (existing)                  │
│  + multimodal_collection: parallel table          │
│    embedding vector(N) / halfvec(N) / bit(N*8)    │
│    modality: text | image                         │
│    HNSW index: vector_cosine_ops                  │
└──────────────────────────────────────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `EmbeddingModel` (ABC) | extends | `MultimodalEmbedding` inherits base lifecycle (executor, model lock, initialize_model, free) |
| `EmbeddingRegistry` | uses | Registered via `supported_embeddings['multimodal']`; cache key is `(model_name, 'multimodal', matryoshka_dim)` |
| `supported_embeddings` dict | extends | New entry: `'multimodal': 'UFormEmbedding'` |
| `EMBEDDING_MODELS` catalog | extends | New entries for UForm multilingual-base and english-large; requires extending `Provider` Literal to include `'multimodal'` |
| `MatryoshkaConfig` | reuses | UForm supports Matryoshka natively; existing validate + truncation logic applies |
| `PgVectorStore` | extends | New parallel multimodal collection (separate table, same store class) |
| `Document` model | uses | Routes `embed_documents()` by modality; images via `metadata` references, text via `page_content` |
| `AbstractStore` | unchanged | Embedding model config passes through `embedding_model` dict with `model_type: 'multimodal'` |

### Data Models

```python
from enum import Enum
from typing import Union, Optional
from dataclasses import dataclass
import numpy as np
from PIL import Image
from pydantic import BaseModel, Field


class EmbeddingBackend(str, Enum):
    """Runtime backend for multimodal inference."""
    TORCH = "torch"
    ONNX = "onnx"


class QuantizationMode(str, Enum):
    """Post-processing quantization for storage."""
    F32 = "f32"
    F16 = "f16"
    I8 = "i8"
    B1 = "b1"


ImageInput = Union[Image.Image, bytes, str]
# str = file path or URL; resolved once in a resolver, never in encode hot path


@dataclass
class EmbeddingResult:
    """Return type for all embed_* methods."""
    embeddings: np.ndarray      # shape: (N, dim)
    dimension: int              # post-Matryoshka dim
    quantization: QuantizationMode
    modality: str               # "text" | "image" | "mixed"
```

### New Public Interfaces

```python
class MultimodalEmbedding(EmbeddingModel, ABC):
    """Modality-aware embedding provider.

    Extends EmbeddingModel with image support and shared-space guarantees.
    """

    def __init__(
        self,
        model_name: str,
        output_dim: Optional[int] = None,         # Matryoshka truncation dim
        quantization: QuantizationMode = QuantizationMode.F32,
        **kwargs,
    ): ...

    @abstractmethod
    async def embed_text(self, texts: list[str]) -> EmbeddingResult: ...

    @abstractmethod
    async def embed_images(self, images: list[ImageInput]) -> EmbeddingResult: ...

    async def embed_documents(self, docs: list[Document]) -> EmbeddingResult:
        """Routes by modality: text via page_content, images via metadata refs."""
        ...

    def _postprocess(self, features: np.ndarray) -> np.ndarray:
        """Matryoshka slice -> L2 renormalize -> quantize. Shared logic."""
        ...


class UFormEmbedding(MultimodalEmbedding):
    """UForm-backed multimodal embedding provider."""

    def __init__(
        self,
        model_name: str = "unum-cloud/uform3-image-text-multilingual-base",
        backend: EmbeddingBackend = EmbeddingBackend.TORCH,
        output_dim: Optional[int] = None,
        quantization: QuantizationMode = QuantizationMode.F32,
        **kwargs,
    ): ...

    def _create_embedding(self, model_name: str, **kwargs) -> Any:
        """Loads UForm model (torch or ONNX session)."""
        ...

    async def encode(self, texts: list[str], **kwargs) -> np.ndarray:
        """Text encoding via run_in_executor."""
        ...

    async def embed_text(self, texts: list[str]) -> EmbeddingResult: ...
    async def embed_images(self, images: list[ImageInput]) -> EmbeddingResult: ...
```

---

## 3. Module Breakdown

### Module 1: Multimodal Base & Enums
- **Path**: `packages/ai-parrot/src/parrot/embeddings/multimodal/__init__.py` +
  `packages/ai-parrot/src/parrot/embeddings/multimodal/base.py`
- **Responsibility**: `MultimodalEmbedding` ABC, `EmbeddingResult` dataclass,
  `EmbeddingBackend` enum, `QuantizationMode` enum, `ImageInput` type alias,
  image resolver utility (PIL.Image / bytes / path / URL -> PIL.Image).
- **Depends on**: `EmbeddingModel` (existing base)

### Module 2: Quantization & Post-processing
- **Path**: `packages/ai-parrot/src/parrot/embeddings/multimodal/quantization.py`
- **Responsibility**: `_postprocess()` implementation — Matryoshka slice (leading N
  dims), L2 renormalization, quantization (f32 passthrough, f16 via `np.float16`,
  i8 via `(emb * 127).astype(int8)`, b1 via `np.packbits(emb > 0)`). Mapping to
  pgvector column types: f32->vector, f16->halfvec, i8->halfvec, b1->bit.
- **Depends on**: Module 1

### Module 3: UForm Provider
- **Path**: `packages/ai-parrot/src/parrot/embeddings/multimodal/uform.py`
- **Responsibility**: `UFormEmbedding` concrete class. Torch backend via
  `uform.get_model(...)`, ONNX backend via `onnxruntime.InferenceSession`.
  `_create_embedding()` loads model; `encode()` / `embed_text()` / `embed_images()`
  dispatch sync inference via `run_in_executor`.
- **Depends on**: Module 1, Module 2

### Module 4: Registry & Catalog Integration
- **Path**: `packages/ai-parrot/src/parrot/embeddings/__init__.py` (modify) +
  `packages/ai-parrot/src/parrot/embeddings/catalog.py` (modify)
- **Responsibility**: Add `'multimodal': 'UFormEmbedding'` to `supported_embeddings`.
  Extend `Provider` Literal to include `'multimodal'`. Add UForm model entries to
  `EMBEDDING_MODELS` catalog (multilingual-base 206M, english-large 365M).
- **Depends on**: Module 3

### Module 5: PgVector Multimodal Collection
- **Path**: `packages/ai-parrot-embeddings/src/parrot/stores/multimodal_schema.py`
  (new) + migration script
- **Responsibility**: Parallel multimodal collection table definition with:
  `embedding vector(N)` (or `halfvec(N)` / `bit(N*8)` depending on quantization),
  `modality text` (text|image), `source_id`, `doc_id`, `payload jsonb`.
  HNSW index with `vector_cosine_ops` (or `bit_hamming_ops` for b1).
  Helper to create/access multimodal collections via `PgVectorStore`.
- **Depends on**: Module 2 (quantization mode determines column type), existing
  `PgVectorStore`

### Module 6: Benchmark Harness
- **Path**: `benchmarks/multimodal_embedding_benchmark.py`
- **Responsibility**: End-to-end benchmark comparing UForm multilingual-base,
  UForm english-large, current HF text embedder baseline, and multilingual-e5-large.
  Metrics: Recall@{1,5,10}, MRR, nDCG@10 for text retrieval (Spanish domain);
  Matryoshka recall curve at dims {768,512,256,128,64}; quantization recall delta
  (f32 vs i8 vs b1); throughput (emb/sec, p50/p95); cross-modal Recall@k.
  Tiny synthetic fallback data included; pluggable Spanish domain data.
- **Depends on**: Module 3, Module 5

### Module 7: Tests
- **Path**: `tests/embeddings/test_multimodal.py` (unit) +
  `tests/embeddings/test_uform_integration.py` (integration)
- **Responsibility**: Unit tests for ABC contract, quantization, image resolver,
  Matryoshka slicing. Integration tests for UForm encode correctness, cross-modal
  sanity (known text<->image pair scores higher than mismatch), ONNX<->torch
  agreement (cosine >= 0.999), async non-blocking verification, PgVector
  round-trip store+search.
- **Depends on**: All modules

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_multimodal_abc_contract` | Module 1 | Cannot instantiate `MultimodalEmbedding` directly; subclass must implement abstract methods |
| `test_embedding_result_shape` | Module 1 | `EmbeddingResult` holds correct shape, dim, quantization, modality |
| `test_image_resolver_pil` | Module 1 | PIL.Image passthrough |
| `test_image_resolver_bytes` | Module 1 | bytes -> PIL.Image decode |
| `test_image_resolver_path` | Module 1 | file path -> PIL.Image load |
| `test_quantization_f16` | Module 2 | f32 -> f16 downcast preserves direction |
| `test_quantization_i8` | Module 2 | i8 = `(emb * 127).astype(int8)`, round-trip within tolerance |
| `test_quantization_b1` | Module 2 | b1 = `packbits(emb > 0)`, correct bit length |
| `test_matryoshka_slice_renorm` | Module 2 | Leading N dims sliced, L2 norm == 1.0 |
| `test_postprocess_chain` | Module 2 | slice -> renormalize -> quantize in correct order |
| `test_embed_documents_routing` | Module 1 | Text-only docs -> embed_text; image-ref docs -> embed_images |

### Integration Tests

| Test | Description |
|---|---|
| `test_uform_embed_text` | UForm produces correct-dim embeddings for text batch |
| `test_uform_embed_images` | UForm produces correct-dim embeddings for image batch |
| `test_crossmodal_sanity` | Known text<->image pair cosine > mismatched pair cosine |
| `test_shared_space_dimension` | Text and image embeddings have identical dimension |
| `test_onnx_torch_agreement` | ONNX vs torch embeddings cosine >= 0.999 on fixed sample |
| `test_async_nonblocking` | embed_* does not block the event loop (asyncio debug mode) |
| `test_registry_integration` | `EmbeddingRegistry.get_or_create(name, 'multimodal')` returns `UFormEmbedding` |
| `test_pgvector_roundtrip` | Store multimodal embeddings -> search -> retrieve with correct modality |
| `test_pgvector_quantized_roundtrip` | f16/i8/b1 embeddings round-trip through pgvector column types |
| `test_matryoshka_recall_curve` | Recall@10 at multiple dim levels (regression guard) |

### Test Data / Fixtures

```python
import pytest
import numpy as np
from PIL import Image

@pytest.fixture
def sample_image():
    """Tiny RGB image for embedding tests."""
    return Image.fromarray(np.random.randint(0, 255, (224, 224, 3), dtype=np.uint8))

@pytest.fixture
def sample_texts():
    return ["a photo of a cat", "a photo of a dog", "quarterly financial report"]

@pytest.fixture
def crossmodal_pair():
    """Known matching text-image pair for sanity check."""
    return {
        "text": "a red apple on a wooden table",
        "image_path": "tests/fixtures/red_apple.jpg",  # must be added
    }
```

---

## 5. Acceptance Criteria

- [ ] `MultimodalEmbedding` ABC + `UFormEmbedding` implemented; registered in
  `supported_embeddings` under key `'multimodal'` and discoverable via
  `EmbeddingRegistry.get_or_create(name, 'multimodal')`.
- [ ] `embed_text`, `embed_images`, `embed_documents` are async and non-blocking
  (`run_in_executor` with `ThreadPoolExecutor`); verified with an event-loop-block
  test.
- [ ] Text and image embeddings share dim and space; a known text<->image pair
  scores higher cosine than a mismatched pair (sanity assertion).
- [ ] Matryoshka `output_dim` slicing + L2 renormalization produce correct dims;
  recall curve recorded at dims {768, 512, 256, 128, 64}.
- [ ] Quantization modes (f32/f16/i8/b1) serialize to the matching pgvector type
  (vector/halfvec/bit); round-trip store+search test passes.
- [ ] ONNX backend loads and matches torch backend embeddings within tolerance
  (cosine >= 0.999 on a fixed sample).
- [ ] Benchmark harness runs end-to-end on synthetic fallback data and emits a
  markdown + CSV report; documented how to plug real Spanish domain data and the
  current baseline model.
- [ ] No embedding logic leaks into loaders; provider is stateless across requests.
- [ ] PgVector multimodal collection schema (parallel table) + HNSW index created;
  includes `modality` column, `source_id`, `doc_id`, `payload` jsonb.
- [ ] `Provider` Literal in catalog extended; UForm model entries added to
  `EMBEDDING_MODELS`.
- [ ] All unit tests pass (`pytest tests/embeddings/test_multimodal.py -v`).
- [ ] All integration tests pass (`pytest tests/embeddings/test_uform_integration.py -v`).

---

## 6. Codebase Contract

### Verified Imports

```python
# Embedding base class
from parrot.embeddings.base import EmbeddingModel  # verified: packages/ai-parrot/src/parrot/embeddings/base.py:15

# Registry
from parrot.embeddings.registry import EmbeddingRegistry  # verified: packages/ai-parrot/src/parrot/embeddings/registry.py:51
from parrot.embeddings import supported_embeddings  # verified: packages/ai-parrot/src/parrot/embeddings/__init__.py:17

# Matryoshka
from parrot.embeddings.matryoshka import MatryoshkaConfig, validate_against_catalog  # verified: packages/ai-parrot/src/parrot/embeddings/matryoshka.py:36,74

# Catalog
from parrot.embeddings.catalog import EMBEDDING_MODELS  # verified: packages/ai-parrot/src/parrot/embeddings/catalog.py:171

# Stores
from parrot.stores.models import Document, DistanceStrategy  # verified: packages/ai-parrot/src/parrot/stores/models.py:40,49
from parrot.stores.abstract import AbstractStore  # verified: packages/ai-parrot/src/parrot/stores/abstract.py:60
from parrot.stores import supported_stores  # verified: packages/ai-parrot/src/parrot/stores/__init__.py:6

# PgVector
from parrot.stores.pgvector import PgVectorStore  # verified: packages/ai-parrot-embeddings/src/parrot/stores/pgvector.py:1-3 (alias for postgres.PgVectorStore)

# Config
from parrot.conf import EMBEDDING_DEVICE, CUDA_DEFAULT_DEVICE  # verified: packages/ai-parrot/src/parrot/embeddings/base.py:9-12
```

### Existing Class Signatures

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

    def get_embedding_dimension(self) -> int          # line 133
    async def initialize_model(self) -> None          # line 136
    @abstractmethod
    def _create_embedding(self, model_name: str, **kwargs) -> Any  # line 162
    async def embed_documents(self, texts: List[str], batch_size: Optional[int] = None) -> List[List[float]]  # line 169
    async def embed_query(self, text: str, as_nparray: bool = False) -> Union[List[float], List[np.ndarray]]  # line 188
    def free(self) -> None                            # line 216
    @abstractmethod
    async def encode(self, texts: List[str], **kwargs) -> np.ndarray  # line 225


# packages/ai-parrot/src/parrot/embeddings/registry.py
CacheKey = Tuple[str, str, Optional[int]]            # line 37 — (model_name, model_type, matryoshka_dim)

class EmbeddingRegistry:                             # line 51
    @classmethod
    def instance(cls, max_models: int = None) -> "EmbeddingRegistry"  # line 100
    async def get_or_create(self, model_name: str, model_type: str = "huggingface", **kwargs) -> Any  # line 218
    def _build_model(self, model_name: str, model_type: str, **kwargs) -> Any  # line 149
    # _build_model resolves: supported_embeddings[model_type] -> class name,
    # imports parrot.embeddings.{model_type}, instantiates class(model_name=model_name, **kwargs)


# packages/ai-parrot/src/parrot/embeddings/catalog.py
Provider = Literal["huggingface", "openai", "google"]  # line 21 — MUST EXTEND to add "multimodal"
Metric = Literal["cosine", "dot", "l2"]               # line 20
UseCaseTag = Literal[...]                             # line 22-33
class EmbeddingModelEntry(BaseModel):                 # line 36
    matryoshka_dimensions: Optional[list[int]] = None  # line 96


# packages/ai-parrot/src/parrot/embeddings/matryoshka.py
class MatryoshkaConfig(BaseModel):                    # line 36
    enabled: bool = False                             # line 54
    dimension: Optional[int] = Field(default=None, gt=0)  # line 55


# packages/ai-parrot-embeddings/src/parrot/embeddings/huggingface.py
class SentenceTransformerModel(EmbeddingModel):       # line 111
    def _apply_matryoshka(self, vectors) -> np.ndarray | list  # line 225
    # Slices leading N dims, L2-renormalizes. Pattern to reuse in base.


# packages/ai-parrot/src/parrot/stores/models.py
class Document(BaseModel):                            # line 40
    page_content: str                                 # line 45
    metadata: Dict[str, Any]                          # line 46


# packages/ai-parrot-embeddings/src/parrot/stores/postgres.py
class PgVectorStore(AbstractStore):                   # line 49
    def __init__(self, table: str = None, schema: str = 'public',
                 embedding_column: str = 'embedding',
                 distance_strategy: DistanceStrategy = DistanceStrategy.COSINE,
                 ...)                                 # line 54-89
    def _define_collection_store(self, table, schema, dimension=768, ...) -> Any  # line 135
    # Uses pgvector.sqlalchemy.Vector(dimension) for column type — line 178
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `MultimodalEmbedding` | `EmbeddingModel` | inheritance | `base.py:15` |
| `UFormEmbedding` | `EmbeddingRegistry._build_model()` | `supported_embeddings` dict lookup + dynamic import of `parrot.embeddings.multimodal` | `registry.py:149-178` |
| UForm catalog entries | `EMBEDDING_MODELS` list | append new dicts validated by `EmbeddingModelEntry` | `catalog.py:171` |
| `_postprocess()` | `SentenceTransformerModel._apply_matryoshka()` | pattern reuse (slice + renorm); extracted to shared module | `huggingface.py:225-263` |
| Multimodal collection | `PgVectorStore._define_collection_store()` | parallel table with same pattern + `modality` column | `postgres.py:135` |

### Configuration References

- `EMBEDDING_DEVICE`: device selection env var — `parrot/conf.py` (imported in `base.py:10`)
- `CUDA_DEFAULT_DEVICE`: CUDA device index — `parrot/conf.py` (imported in `base.py:11`)
- `EMBEDDING_REGISTRY_MAX_MODELS`: LRU cache size — env var read in `registry.py`
- `EMBEDDING_DEFAULT_MODEL`: default model name — `parrot/conf.py` (imported in `stores/abstract.py:8`)

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.embeddings.multimodal`~~ — **does not exist yet**; must be created as new package
- ~~`MultimodalEmbedding`~~ — does not exist; new ABC to create
- ~~`UFormEmbedding`~~ — does not exist; new class to create

…(truncated)…
