---
type: Wiki Overview
title: 'Brainstorm: Multimodal Embedding Provider (UForm-first)'
id: doc:sdd-proposals-multimodal-embedding-provider-brainstorm-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: AI-Parrot's embedding layer is currently **text-only** (HuggingFace Transformers).
relates_to:
- concept: mod:parrot
  rel: mentions
- concept: mod:parrot.clients
  rel: mentions
- concept: mod:parrot.embeddings
  rel: mentions
- concept: mod:parrot.models
  rel: mentions
- concept: mod:parrot.stores.pgvector
  rel: mentions
---

---
title: Multimodal Embedding Provider (UForm-first)
type: brainstorm
status: draft
base_branch: dev
feature_slug: multimodal-embedding-provider
target_package: packages/ai-parrot
related:
  - InfographicToolkit (visual document use cases)
  - Epson planogram agents (image retrieval)
  - PgVector conversational RAG
author: jesuslarag
---

# Brainstorm: Multimodal Embedding Provider (UForm-first)

## 1. Problem Statement

AI-Parrot's embedding layer is currently **text-only** (HuggingFace Transformers).
Several active domains require retrieving over content where the *visual* signal is
primary or co-equal with text:

- Epson planogram agents (image of shelf layout ↔ textual product/spec query).
- `InfographicToolkit` outputs and source figures.
- Document loaders that today drop or OCR-flatten embedded images, losing layout/visual semantics.

We need a **multimodal embedding provider** that maps text and images into a *shared*
vector space so PgVector can serve cross-modal retrieval (text→image, image→text,
image→image) under the existing conversational RAG flow — without coupling embedding
logic into loaders and without adding a heavy serving footprint to Knative.

UForm (`unum-cloud/uform`, Apache-2.0, v3.1.4 / Oct-2025) is the candidate first
implementation: tiny CLIP-style encoders (64–768 dims, Matryoshka), quantization-aware,
native ONNX, multilingual base (21 langs incl. Spanish). This brainstorm scopes the
provider abstraction, the UForm implementation, and a quick benchmark to decide whether
the multilingual text quality justifies adoption over our current text embedder.

### Non-goals

- **NOT** a local reasoning LLM. UForm's generative models (1.2B, qwen1.5-0.5B base) are
  captioning/VQA-grade only and are out of scope here. Local reasoning stays on the
  Ollama/vLLM track and is a separate FEAT.
- **NOT** replacing the text-only embedder for pure-text RAG by default. The benchmark
  decides whether UForm's multilingual text encoder is competitive; until then both
  coexist.
- **NOT** a new vector store. We extend PgVector usage; ArangoDB graph RAG is untouched.

---

## 2. Constraints

- **Asyncio-first.** Encoding is CPU/GPU-bound (sync). Provider must never block the loop:
  wrap in `run_in_executor` or offload to `qworker` / `ToolWorkerService`.
- **Pydantic v2** at all I/O boundaries (config + result models).
- **Stateless provider.** No per-request global mutable state; model handles loaded once at
  `configure()`, inference is pure. Mirrors stateless-toolkit principle.
- **Separation of concerns.** Loaders keep producing `List[Document]` with image references;
  embedding happens at the vectorization layer, never inside loaders. No LLM/decision logic
  in the provider.
- **Deployment footprint.** Must support an ONNX runtime path (~100–460 MB) for Knative
  scale-to-zero; PyTorch path acceptable for dev/GPU.
- **PgVector compatibility.** Output must serialize to `vector` / `halfvec` / `bit`
  (pgvector ≥ 0.7) to support quantized + Matryoshka storage.
- **Shared embedding space.** Text and image embeddings MUST be L2-comparable in the same
  space and dimension for a given configured model; mixing modalities in one collection is
  a goal, not an accident.
- **Language:** code/artifacts in English.

---

## 3. Codebase Contract  ⚠️ VERIFY ALL ANCHORS BEFORE /sdd-spec

> I could not read the repo from here. Run each `grep` and replace the placeholder path
> with the real one (use the matched **anchor string**, not a line number, in the spec).
> If an anchor returns nothing, that item is a *new* artifact (mark accordingly).

### Existing (must confirm)

| Concept | Grep anchor command | Placeholder path |
|---|---|---|
| Embedding base/abstract class | `grep -rn "class .*Embedding" packages/ai-parrot/**/embeddings* ` | `parrot.embeddings.AbstractEmbedding` ⚠️ |
| Embedding/client registry | `grep -rn "SUPPORTED_CLIENTS\|EMBEDDING_PROVIDERS\|register_embedding" packages/ai-parrot` | `parrot.clients.SUPPORTED_CLIENTS` ⚠️ |
| PgVector store | `grep -rn "class .*PgVector\|pgvector\|halfvec" packages/ai-parrot` | `parrot.stores.pgvector.PgVectorStore` ⚠️ |
| Document model | `grep -rn "class Document" packages/ai-parrot packages/ai-parrot-loaders` | `parrot.models.Document` ⚠️ |
| Image carrier on Document | `grep -rn "image\|bytes\|media\|attachment" .../models/document.py` | (confirm how loaders attach image refs) ⚠️ |
| Async offload mechanism | `grep -rn "run_in_executor\|ToolWorkerService\|QWorker" packages/ai-parrot` | `parrot.qworker.ToolWorkerService` ⚠️ |
| Config loader | `grep -rn "navconfig\|from navconfig" packages/ai-parrot` | `navconfig.config` ✔ (known) |
| Existing HF text embedder (benchmark baseline) | `grep -rn "SentenceTransformer\|AutoModel.*embed\|HuggingFace.*Embedding" packages/ai-parrot` | `parrot.embeddings.HFEmbedding` ⚠️ |

### New (to be created)

- `MultimodalEmbedding` protocol/abstract (modality-aware interface). NEW
- `UFormEmbedding` concrete provider (torch + onnx backends). NEW
- `EmbeddingBackend` enum / strategy (`torch` | `onnx`). NEW
- `QuantizationMode` enum (`f32` | `f16` | `i8` | `b1`). NEW
- PgVector multimodal collection schema (modality column + shared-dim vector). NEW or MIGRATION

### External deps (confirm against `uv` workspace)

- `uform>=3.1` (torch extra: `uform[torch]`, onnx extra: `uform[onnx]`).
- `onnxruntime` (CPU) / `onnxruntime-gpu` as optional extra.
- `pillow` (image decode) — likely already present via loaders. ⚠️ confirm.
- Optional: `usearch`, `simsimd` (only if in-process rerank/index is later desired — NOT
  required for PgVector path).

---

## 4. Architecture Options

### Option A — Thin UForm wrapper (torch only)
Single `UFormEmbedding` calling `uform.get_model(...)` with the torch backend.

- **Pros:** Smallest diff; fastest to ship; matches README API 1:1.
- **Cons:** ~5.2 GB torch footprint hurts Knative cold start; no abstraction, so a second
  multimodal model (Jina-CLIP, OpenCLIP) later means a rewrite; quantization/Matryoshka
  bolted on ad hoc.

### Option B — UForm with backend toggle (torch + onnx)
Same provider, `EmbeddingBackend` strategy chooses torch (dev/GPU) or ONNX runtime
(serving). One class, two loaders.

- **Pros:** Solves the deployment footprint cleanly (~460 MB ONNX → ~100 MB tuned) for
  Knative; keeps a single provider surface.
- **Cons:** Still UForm-specific; abstraction debt remains for future models; ONNX export of
  UForm encoders must be validated (they ship ONNX, but confirm both TEXT and IMAGE
  encoders are exported).

### Option C — Generic `MultimodalEmbedding` abstraction, UForm as first impl (RECOMMENDED)
Define a modality-aware interface; `UFormEmbedding` is the first concrete provider and ships
with the backend toggle from Option B. Quantization + Matryoshka slicing live in the base as
post-processing, model-agnostic.

```
MultimodalEmbedding (ABC, Pydantic-configured)
  ├─ async embed_text(texts: list[str]) -> EmbeddingResult
  ├─ async embed_images(images: list[ImageInput]) -> EmbeddingResult
  ├─ async embed_documents(docs: list[Document]) -> EmbeddingResult   # routes by modality
  ├─ dim: int            # post-Matryoshka
  ├─ quantization: QuantizationMode
  └─ _postprocess(features) -> np.ndarray   # slice + downcast (shared logic)

UFormEmbedding(MultimodalEmbedding)
  ├─ backend: EmbeddingBackend  # torch | onnx
  └─ uses uform.get_model(...) / onnxruntime session
```

- **Pros:** Clean separation; future CLIP-family providers plug in with zero churn;
  quantization/Matryoshka centralized and reused; aligns with your abstraction-first style
  (`AbstractClient`/`AbstractToolkit` symmetry). Stateless, async, testable.
- **Cons:** Slightly more upfront design; must define a stable cross-provider result contract
  (dim alignment, normalization convention) now rather than later.

**Recommendation: Option C.** The marginal design cost buys us provider-independence and a
single place for the PgVector-facing quantization logic, which is the part most likely to be
reused. UForm ships behind it with the torch/onnx toggle.

---

## 5. Module Layout (proposed — adjust to verified base path)

```
packages/ai-parrot/parrot/embeddings/
  multimodal/
    __init__.py
    base.py            # MultimodalEmbedding ABC, EmbeddingResult, enums
    quantization.py    # f32/f16/i8/b1 + Matryoshka slice helpers
    uform.py           # UFormEmbedding (torch + onnx backends)
  registry.py          # register_embedding("uform-multimodal", UFormEmbedding)  ⚠️ confirm registry
packages/ai-parrot/parrot/stores/pgvector/
  multimodal_schema.py # collection w/ modality column + shared-dim vector/halfvec/bit
```

### Key interface decisions to lock in spec

- **Normalization:** L2-normalize all outputs at the base layer so cosine == dot. UForm
  encoders return features + pooled embedding; we consume the pooled embedding and normalize.
- **Matryoshka:** `output_dim` config slices the leading N dims *before* normalization
  (slice → renormalize). Validate recall per dim in benchmark.
- **Quantization:** `i8` via linear scale (`* 127`), `b1` via `np.packbits(emb > 0)`; map to
  pgvector `halfvec`/`bit`. f32 default.
- **Image input contract:** accept `PIL.Image | bytes | path | url`; resolve once in a
  resolver, never inside the encode hot path.
- **Async:** `embed_*` are `async` and dispatch the sync encode via `run_in_executor`;
  expose an optional `qworker` offload path behind a flag for serving.

---

## 6. PgVector Integration

- Single multimodal collection: `embedding vector(N)` (or `halfvec(N)` / `bit(N*?)`),
  `modality text` (`text`|`image`), `source_id`, `doc_id`, payload `jsonb`.
- Index: HNSW with `vector_cosine_ops` (or `bit_hamming_ops` for b1). Confirm pgvector
  version supports the chosen op class.
- Matryoshka strategy: store full dim; optionally maintain a second truncated column for a
  coarse-search-then-rerank pattern (decide in spec — adds write cost).
- **Open question:** do we keep multimodal vectors in the *same* collection as current
  text-only RAG (requires same model/dim) or a parallel collection joined at query time?
  Lean: parallel collection while UForm coexists with the current text embedder; merge only
  if benchmark says UForm replaces the text embedder.

---

## 7. Benchmark Plan (decision gate)

Goal: decide if UForm's **multilingual text** quality is competitive, and quantify its
multimodal + cost advantages. Ship as `benchmarks/multimodal_embedding_benchmark.py`
(provided alongside this doc).

### Models under test
- `unum-cloud/uform3-image-text-multilingual-base` (206M, 21 langs) — primary candidate.
- `unum-cloud/uform3-image-text-english-large` (365M) — English ceiling reference.
- Current AI-Parrot text embedder — **baseline** ⚠️ plug in real model id.
- `intfloat/multilingual-e5-large` — strong multilingual text baseline.
- `BAAI/bge-m3` — strong multilingual text baseline.
- (Optional multimodal baseline) `jinaai/jina-clip-v2` or `sentence-transformers/clip-ViT-B-32-multilingual-v1`.

### Metrics
- **Text retrieval (Spanish, your domain):** Recall@{1,5,10}, MRR, nDCG@10.
- **Matryoshka recall curve:** same metrics at dims {768, 512, 256, 128, 64}.
- **Quantization recall delta:** f32 vs i8 vs b1.
- **Throughput:** embeddings/sec, latency p50/p95 (CPU and, if available, GPU).
- **Footprint:** on-disk model size, embedding dim, estimated PgVector index size for N rows.
- **Cross-modal (if image set available):** image→text and text→image Recall@k.

### Data
- Bring your own Spanish domain set (query, relevant_doc_id) — TODO marker in script.
- Tiny synthetic fallback included so the harness runs end-to-end out of the box.

### Decision rule (proposed)
- If UForm multilingual text nDCG@10 is within ~3% of the best text baseline → adopt UForm as
  the *unified* provider and consider replacing the text-only embedder.
- If it lags >3% on text but cross-modal works → adopt as multimodal-only provider, keep the
  text embedder for pure-text RAG (parallel collections).
- If both lag → keep text embedder; revisit a different multimodal model behind the same
  Option-C abstraction.

---

## 8. Acceptance Criteria

1. `MultimodalEmbedding` ABC + `UFormEmbedding` implemented; registered in the embedding
   registry under a stable name.
2. `embed_text`, `embed_images`, `embed_documents` are async and non-blocking (executor or
   qworker); verified with an event-loop-block test.
3. Text and image embeddings share dim and space; a known text↔image pair scores higher than
   a mismatched pair (sanity assertion).
4. Matryoshka `output_dim` slicing + L2 renormalization produce correct dims; recall curve
   recorded.
5. Quantization modes (f32/f16/i8/b1) serialize to the matching pgvector type; round-trip
   store+search test passes.
6. ONNX backend loads and matches torch backend embeddings within tolerance (cosine ≥ 0.999
   on a fixed sample).
7. Benchmark harness runs end-to-end on the synthetic fallback and emits a markdown + CSV
   report; documented how to plug real Spanish domain data and the current baseline.
8. No embedding logic leaks into loaders; provider is stateless across requests.
9. PgVector multimodal collection schema + HNSW index created via migration; documented.

---

## 9. Open Questions for /sdd-spec

- Same-collection vs parallel-collection for multimodal vs current text RAG?
- Do we expose the `qworker` offload now or as a follow-up FEAT?
- ONNX: are both TEXT and IMAGE encoders exported for the multilingual model? (verify on HF)
- Coarse-rerank (truncated second column) in v1 or deferred?
- Provider naming in registry: `uform` vs `uform-multimodal` vs `multimodal`?

---

## Revision History

| Date | Author | Change |
|---|---|---|
| 2026-06-05 | jesuslarag | Initial brainstorm draft |
