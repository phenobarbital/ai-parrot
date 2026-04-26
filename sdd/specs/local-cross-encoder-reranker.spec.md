# Feature Specification: Local Cross-Encoder Reranker for RAG Retrieval

**Feature ID**: FEAT-126
**Date**: 2026-04-27
**Author**: Jesus Lara
**Status**: draft
**Target version**: ai-parrot next minor

---

## 1. Motivation & Business Requirements

### Problem Statement

The current RAG retrieval pipeline in `BaseBot.ask()` and `BaseBot.conversation()` relies on
pure dense vector similarity (`search_type='similarity'` is the hardcoded default), with a
fixed `context_search_limit=10` and `context_score_threshold=0.7` over chunks of approx.
512 tokens. This pipeline has a known structural weakness: when a user query and the
authoritative document use different surface vocabulary — e.g. *"what applications I need
to download?"* against a document titled *"web applications to use"* — the cosine distance
penalises the lexical mismatch even though the document is the correct answer. The result
is degraded answer quality on questions that an employee would consider trivially
answerable from the corpus.

The framework already exposes a `search_type='ensemble'` mode that fuses similarity + MMR
via `weighted_score | rrf | interleave` (see `parrot/interfaces/vector.py:155`), but this is
**fusion of two dense retrievals**, not true relevance-based reranking — both branches share
the same embedding space and the same lexical-mismatch blind spot. There is no
cross-encoder reranker anywhere in the codebase that scores `(query, passage)` pairs jointly.

Field deployment will serve thousands of employees querying daily. To deliver acceptable
answer quality at that scale, we need a reranking stage that operates over a wider
candidate pool than what fits in the LLM context, so we can recover semantically and
lexically diverse hits up front and trust a precise scorer to keep only the top-N for
prompt assembly.

### Goals

1. Introduce an `AbstractReranker` abstraction in `parrot/rerankers/` that exposes a single
   async method `rerank(query, documents, top_n) -> list[RerankedDocument]`, mirroring the
   pattern of `AbstractClient`, `AbstractStore`, and `AbstractToolkit`.
2. Provide a production-grade implementation `LocalCrossEncoderReranker` that runs
   cross-encoder models in-process (no external service), supporting at least three models
   selected via `model_name`:
   - `BAAI/bge-reranker-v2-m3` — production default (568M, multilingual, English-strong).
   - `jinaai/jina-reranker-v2-base-multilingual` — comparison alternative (278M).
   - `cross-encoder/ms-marco-MiniLM-L-12-v2` — dev/CI fast path (33M, English-only).
3. Auto-detect device and precision per environment:
   - GPU available → FP16.
   - CPU only → PyTorch dynamic INT8 quantization (no extra dependencies).
4. Wire the reranker into `BaseBot._build_vector_context()` so that, when configured,
   retrieval over-fetches by a multiplier (default `4×limit`) and the reranker keeps the
   top `limit`. When no reranker is configured, the existing path is preserved
   byte-for-byte (backward compatible).
5. Ship a reproducible benchmark harness that produces nDCG@5, MRR, and P50/P95 latency
   for each supported model on both CPU and GPU, against a small labelled query set.
6. Document the threshold semantics shift: `context_score_threshold` (today calibrated for
   cosine distance) is **not** comparable to cross-encoder logits and must be re-calibrated
   or bypassed when reranking is active.

### Non-Goals (explicitly out of scope)

- **Hybrid lexical+dense retrieval at the bot layer** (exposing `search_type='hybrid'` to
  call `store.hybrid_search()` for ColBERT/BM25). The infrastructure exists in
  `parrot/stores/postgres.py:1653` and `parrot/stores/arango.py:775` but is unrelated to
  reranking and warrants its own spec.
- **Parent-child / small-to-big retrieval** at the loader/store layer. Discussed but
  deferred — solves a different failure mode (answer split across chunks).
- **Cloud reranker APIs** (Cohere Rerank, Jina cloud, Voyage). Rejected by stakeholder
  decision: the field deployment target explicitly avoids adding another cloud dependency.
- **ONNX Runtime / Optimum** as the default CPU acceleration path. Documented as an
  optional escalation if PyTorch dynamic quantization proves insufficient under load, but
  not a default and not implemented in this feature.
- **Re-engineering the existing `'ensemble'` fusion logic** in `parrot/interfaces/vector.py`.
  It coexists with the new reranker; users who prefer the old behaviour keep it.
- **Changing the default `context_score_threshold`**. Calibration guidance is documented;
  any default change is a follow-up after harness data is collected.

---

## 2. Architectural Design

### Overview

A new module `parrot/rerankers/` introduces:

1. `AbstractReranker` — async-first abstract base class with one public method
   `rerank()` and lifecycle hooks `load()` / `cleanup()`.
2. `LocalCrossEncoderReranker` — concrete implementation that loads an HF cross-encoder
   model once at construction (eager + warmup), runs `(query, passage)` scoring in a
   single batched forward pass, and returns documents reordered by relevance score with
   the original index preserved for traceability.
3. `LLMReranker` — debug/fallback implementation that uses the bot's existing LLM via
   `AbstractClient.completion()`. Not for production hot path; exists so engineers can
   sanity-check the local reranker against a strong reference without external services.

`AbstractBot` gains an optional `self.reranker: Optional[AbstractReranker]` attribute
configured via constructor kwargs. When non-null, `_build_vector_context()`:

1. Multiplies the candidate pool: requests `limit * rerank_oversample_factor` results
   from the underlying `similarity_search` / `mmr_search` / `_ensemble_search` (default
   factor `4`, configurable per call and per bot).
2. Awaits `self.reranker.rerank(question, candidates, top_n=limit)`.
3. On reranker failure (timeout, exception, empty result) logs at WARNING level and
   falls back to the original retrieval order truncated to `limit`. Never raises to
   the caller.

The score-threshold filter remains applied *before* reranking, against the retrieval
score (cosine), not against the reranker score. This is intentional: the threshold
filters the candidate pool; the reranker reorders what survives.

### Component Diagram

```
                       ┌──────────────────────────────────────┐
                       │  BaseBot.ask() / .conversation()     │
                       └──────────────────┬───────────────────┘
                                          │
                                          ▼
                       ┌──────────────────────────────────────┐
                       │  AbstractBot._build_vector_context() │
                       │  (parrot/bots/abstract.py:2239)      │
                       └──────────────────┬───────────────────┘
                                          │
                          ┌───────────────┴───────────────┐
                          │                               │
                          ▼                               ▼
              ┌───────────────────────┐     ┌─────────────────────────────┐
              │ store.similarity_search│     │ self.reranker (optional)    │
              │ store.mmr_search       │ ──► │ AbstractReranker.rerank()   │
              │ _ensemble_search       │     │                             │
              └───────────────────────┘     └──────────────┬──────────────┘
                  (over-fetch limit*N)                     │
                                                           ▼
                                            ┌──────────────────────────────┐
                                            │ LocalCrossEncoderReranker    │
                                            │  - HF model singleton (eager)│
                                            │  - batched forward pass      │
                                            │  - asyncio.to_thread wrapper │
                                            └──────────────────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractBot` (`parrot/bots/abstract.py:144`) | extends | New `self.reranker` attribute, init kwarg `reranker`, init kwarg `rerank_oversample_factor=4`. |
| `AbstractBot._build_vector_context()` (`abstract.py:2239`) | modifies | Inserts post-retrieval rerank step when `self.reranker` is set; preserves legacy path otherwise. |
| `AbstractBot.get_vector_context()` (`abstract.py:1587`) | modifies | Same hook applied to the legacy path called from the StoreRouter fallback. |
| `BaseBot.ask()` (`base.py:562`) and `BaseBot.conversation()` (`base.py:46`) | passive | No signature change; benefit transparently when bot is configured with a reranker. |
| `parrot/stores/models.py:SearchResult` (line 7) | reuses | Reranker accepts `list[SearchResult]` and returns `list[RerankedDocument]` carrying the original `SearchResult` plus reranker metadata. |
| `parrot/interfaces/vector.py:_combine_search_results` (line 155) | coexists | Pre-rerank fusion (`weighted_score | rrf | interleave`) is unchanged. The reranker, when active, runs *after* fusion. |

### Data Models

```python
# parrot/rerankers/models.py
from typing import Optional
from pydantic import BaseModel, Field
from parrot.stores.models import SearchResult


class RerankedDocument(BaseModel):
    """A SearchResult enriched with reranker scoring."""

    document: SearchResult                              # original retrieval hit
    rerank_score: float = Field(...)                    # raw reranker logit / score
    rerank_rank: int = Field(..., ge=0)                 # 0-based rank after rerank
    original_rank: int = Field(..., ge=0)               # 0-based rank pre-rerank
    rerank_model: str = Field(...)                      # HF model id used
    rerank_latency_ms: Optional[float] = None           # populated by reranker for telemetry


class RerankerConfig(BaseModel):
    """Construction config for LocalCrossEncoderReranker."""

    model_name: str = "BAAI/bge-reranker-v2-m3"
    device: str = "auto"                                # 'auto' | 'cuda' | 'cpu' | 'cuda:0' ...
    precision: str = "auto"                             # 'auto' | 'fp32' | 'fp16' | 'int8'
    max_length: int = 512
    batch_size: int = 32
    trust_remote_code: bool = False                     # Jina v2 requires True
    warmup: bool = True                                 # do a forward pass at __init__
```

### New Public Interfaces

```python
# parrot/rerankers/abstract.py
from abc import ABC, abstractmethod
from typing import Optional
from parrot.stores.models import SearchResult
from .models import RerankedDocument


class AbstractReranker(ABC):
    """Abstract base for relevance rerankers."""

    @abstractmethod
    async def rerank(
        self,
        query: str,
        documents: list[SearchResult],
        top_n: Optional[int] = None,
    ) -> list[RerankedDocument]:
        """Score (query, document) pairs and return them sorted by relevance.

        Args:
            query: User query text.
            documents: Candidate documents from upstream retrieval.
            top_n: If set, return only the top N. If None, return all reranked.

        Returns:
            Reranked documents in descending score order. Length is min(top_n, len(documents)).
            On internal failure the implementation MUST NOT raise; it MUST return the
            input documents wrapped as RerankedDocument with rerank_score=NaN and the
            original ordering preserved.
        """

    async def load(self) -> None:
        """Eager model load. Default: no-op (subclasses override)."""

    async def cleanup(self) -> None:
        """Release resources (GPU memory, etc.). Default: no-op."""
```

`AbstractBot.__init__` gains:

```python
self.reranker: Optional[AbstractReranker] = kwargs.get("reranker", None)
self.rerank_oversample_factor: int = int(kwargs.get("rerank_oversample_factor", 4))
```

---

## 3. Module Breakdown

### Module 1: `parrot/rerankers/__init__.py`
- **Path**: `packages/ai-parrot/src/parrot/rerankers/__init__.py`
- **Responsibility**: Export `AbstractReranker`, `LocalCrossEncoderReranker`,
  `LLMReranker`, `RerankedDocument`, `RerankerConfig`. Lazy-import heavy submodules
  to keep `import parrot` cheap.
- **Depends on**: stdlib only at the package root.

### Module 2: `parrot/rerankers/models.py`
- **Path**: `packages/ai-parrot/src/parrot/rerankers/models.py`
- **Responsibility**: Pydantic models `RerankedDocument` and `RerankerConfig`.
- **Depends on**: `parrot.stores.models.SearchResult`, `pydantic`.

### Module 3: `parrot/rerankers/abstract.py`
- **Path**: `packages/ai-parrot/src/parrot/rerankers/abstract.py`
- **Responsibility**: `AbstractReranker` ABC. No implementation, no model deps.
- **Depends on**: Module 2.

### Module 4: `parrot/rerankers/local.py`
- **Path**: `packages/ai-parrot/src/parrot/rerankers/local.py`
- **Responsibility**: `LocalCrossEncoderReranker` — HF cross-encoder loaded as a
  process-local singleton per `(model_name, device, precision)` triple. Implements:
  - Device autodetect (CUDA if available, else CPU).
  - Precision autodetect: FP16 on CUDA, INT8 (PyTorch `quantize_dynamic` over `nn.Linear`)
    on CPU, FP32 only if user forces it.
  - Tokenisation of all `(query, passage)` pairs in a single batch (or chunked into
    `batch_size` mini-batches when `len(documents) > batch_size`).
  - Forward pass under `torch.inference_mode()` with `model.eval()`.
  - Async wrapping via `asyncio.to_thread()` (or a dedicated `ThreadPoolExecutor` with
    `max_workers=1` per device when concurrency demands serialised GPU access).
  - Eager warmup at `__init__` with a dummy `("warmup", "warmup passage")` pair so the
    first real request does not pay CUDA kernel JIT or weight-load latency.
  - Error path: catch `Exception`, log at WARNING, return original-order
    `RerankedDocument` list with `rerank_score=float('nan')`.
- **Depends on**: Module 3, `transformers` (already a dep), `torch` (already a dep),
  optionally `sentence_transformers.CrossEncoder` (already a dep) if it simplifies the
  batching code path.

### Module 5: `parrot/rerankers/llm.py`
- **Path**: `packages/ai-parrot/src/parrot/rerankers/llm.py`
- **Responsibility**: `LLMReranker` — uses an `AbstractClient` to score (query, document)
  pairs via a structured-output prompt that returns a numeric relevance score per
  document. Debug-only; not optimised for throughput.
- **Depends on**: Module 3, `parrot.clients.AbstractClient`.

### Module 6: `parrot/bots/abstract.py` modifications
- **Path**: `packages/ai-parrot/src/parrot/bots/abstract.py`
- **Responsibility**:
  - Add `self.reranker` and `self.rerank_oversample_factor` in `__init__` (around
    `abstract.py:387` next to `context_search_limit`).
  - Modify `get_vector_context()` (line 1587) and `_build_vector_context()` (line 2239) to
    over-fetch by `rerank_oversample_factor` and call `self.reranker.rerank()` when set.
  - Update docstrings to note the new behaviour and the threshold-semantics caveat.
- **Depends on**: Modules 3 and 4 (as type annotations only — no hard runtime import to
  keep AbstractBot importable without HF model deps loaded).

### Module 7: Benchmark harness
- **Path**: `packages/ai-parrot/scripts/benchmark_reranker.py` and
  `packages/ai-parrot/tests/data/reranker_eval/`.
- **Responsibility**: Reproducible script that:
  1. Loads a small labelled dataset of `(query, [doc_ids], relevance_judgments)` —
     50–100 queries minimum, English-primary.
  2. For each model in `[bge-reranker-v2-m3, jina-reranker-v2-base-multilingual,
     ms-marco-MiniLM-L-12-v2]`, on each of `[cpu, cuda]` (skipped if unavailable),
     runs reranking and computes nDCG@5, MRR, P50/P95 latency.
  3. Outputs a markdown table to stdout and a JSON to `artifacts/benchmarks/reranker-<date>.json`.
- **Depends on**: Modules 3, 4. Not part of runtime package; lives under `scripts/`.

### Module 8: Integration tests
- **Path**: `packages/ai-parrot/tests/unit/rerankers/` and
  `packages/ai-parrot/tests/integration/rerankers/`.
- **Responsibility**: See §4.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_abstract_reranker_is_abc` | Module 3 | Cannot be instantiated directly; subclasses must implement `rerank`. |
| `test_local_reranker_init_minilm_cpu` | Module 4 | Loads MiniLM-L-12-v2 on CPU successfully; warmup runs; `model_name` echoed. |
| `test_local_reranker_rerank_orders_descending` | Module 4 | Given 5 contrived passages, the most relevant is rank 0 in the output. |
| `test_local_reranker_top_n_truncation` | Module 4 | `top_n=3` returns exactly 3 items even with 10 inputs. |
| `test_local_reranker_preserves_original_rank` | Module 4 | Each `RerankedDocument` carries the correct `original_rank`. |
| `test_local_reranker_handles_empty_input` | Module 4 | Empty `documents` returns `[]` without forward pass. |
| `test_local_reranker_failure_returns_original_order` | Module 4 | Mock the model to raise; verify NaN scores and original order. |
| `test_local_reranker_truncates_to_max_length` | Module 4 | Passages longer than `max_length` are tokenised with truncation, no exception. |
| `test_int8_quantization_applied_on_cpu` | Module 4 | When `device='cpu'` and `precision='auto'`, weights are quantized (assert on a `nn.Linear` module type). |
| `test_fp16_applied_on_cuda` | Module 4 | When CUDA is available and `precision='auto'`, model dtype is FP16. Skipped if no CUDA. |
| `test_jina_requires_trust_remote_code` | Module 4 | Loading Jina v2 with `trust_remote_code=False` raises a clear error; with `True` succeeds. |
| `test_llm_reranker_basic` | Module 5 | With a fake `AbstractClient` returning fixed scores, ordering matches scores. |
| `test_abstractbot_no_reranker_path_unchanged` | Module 6 | Without `reranker`, `_build_vector_context` produces the exact same output as before. |
| `test_abstractbot_with_reranker_oversamples` | Module 6 | When `reranker` is set, the underlying `similarity_search` is called with `limit * factor`. |
| `test_abstractbot_reranker_failure_falls_back` | Module 6 | A reranker that returns NaN scores is treated as fallback; final order is original retrieval order truncated to `limit`. |

### Integration Tests

| Test | Description |
|---|---|
| `test_basebot_ask_with_local_reranker_minilm` | End-to-end `BaseBot.ask()` against an in-memory store, MiniLM reranker; assert the answer references the document the reranker promoted. |
| `test_basebot_conversation_with_reranker_preserves_history` | Reranker does not interfere with conversation memory or session_id propagation. |
| `test_reranker_oversample_respects_score_threshold` | Documents below `context_score_threshold` are filtered before reranking, not after. |
| `test_benchmark_harness_runs_minilm_cpu_e2e` | The harness script exits 0 on a 10-query mini-dataset and produces the JSON artifact. |

### Test Data / Fixtures

```python
# tests/data/reranker_eval/eval_set.json
# Schema: list of {"query": str, "passages": [{"id": str, "text": str, "relevance": int}], ...}
# At least 50 English queries with graded relevance (0/1/2) over 5–20 passages each.

@pytest.fixture(scope="session")
def minilm_reranker():
    """Cheap CPU-only reranker shared across tests in the same session."""
    from parrot.rerankers import LocalCrossEncoderReranker
    return LocalCrossEncoderReranker(
        model_name="cross-encoder/ms-marco-MiniLM-L-12-v2",
        device="cpu",
        precision="fp32",     # quant tested separately
        warmup=True,
    )

@pytest.fixture
def fake_search_results():
    """Deterministic SearchResult list for ordering tests."""
    ...
```

CI must use **MiniLM-L-12-v2** for any test that loads a real model. BGE v2-m3 and
Jina v2 are too large for fast CI; they are exercised only by the benchmark harness
which is not part of the default test suite.

---

## 5. Acceptance Criteria

This feature is complete when ALL of the following are true:

- [ ] `parrot/rerankers/` package exists with `AbstractReranker`, `LocalCrossEncoderReranker`,
      `LLMReranker`, `RerankedDocument`, and `RerankerConfig` exported from the package root.
- [ ] `LocalCrossEncoderReranker` loads and reranks successfully with all three target
      models: `BAAI/bge-reranker-v2-m3`, `jinaai/jina-reranker-v2-base-multilingual`
      (with `trust_remote_code=True`), and `cross-encoder/ms-marco-MiniLM-L-12-v2`.
- [ ] On CPU with `precision='auto'`, dynamic INT8 quantization is applied; on CUDA with
      `precision='auto'`, FP16 weights are used.
- [ ] Eager warmup runs at construction; first real `rerank()` call latency is within
      20% of steady-state latency (measured by the benchmark harness, MiniLM CPU).
- [ ] `BaseBot.ask()` and `BaseBot.conversation()` produce identical output when no
      reranker is configured (regression test passes byte-for-byte against snapshots).
- [ ] When a reranker is configured, retrieval over-fetches by `rerank_oversample_factor`
      (default 4) and the reranker keeps the top `context_search_limit`.
- [ ] Reranker failure (raised exception, NaN scores, timeout) does not propagate to
      `BaseBot.ask()`; the bot falls back to original retrieval order with a WARNING log.
- [ ] All unit tests pass (`pytest packages/ai-parrot/tests/unit/rerankers/ -v`).
- [ ] All integration tests pass (`pytest packages/ai-parrot/tests/integration/rerankers/ -v`).
- [ ] Benchmark harness runs to completion on CPU and produces the markdown table and
      JSON artifact for at least MiniLM and BGE on a 50+ query eval set.
- [ ] Documentation:
      - `docs/` page describing how to wire a reranker into a bot, including a CPU vs GPU
        configuration example and the threshold-semantics warning.
      - Docstring on `AbstractBot.context_score_threshold` updated to note that the
        threshold is applied **pre-rerank** and is in cosine space, not reranker space.
- [ ] No new direct dependencies added to `pyproject.toml`. `transformers`, `torch`, and
      `sentence_transformers` are reused from existing pins.
- [ ] Performance budget: with `BAAI/bge-reranker-v2-m3` on a single T4-class GPU at FP16,
      reranking 40 candidates of ≤512 tokens against a 32-token query completes in under
      150 ms P95 (warm). Documented in benchmark output, not enforced by CI.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Implementation agents MUST NOT reference imports, attributes, or methods not listed
> here without first verifying they exist via `grep` or `read`.

### Verified Imports

```python
from parrot.bots.abstract import AbstractBot           # verified: parrot/bots/abstract.py:144
from parrot.bots.base import BaseBot                   # verified: parrot/bots/base.py:28
from parrot.stores.models import SearchResult, Document  # verified: parrot/stores/models.py:7,21
from parrot.stores import AbstractStore                # verified: parrot/stores/__init__.py
from parrot.clients.abstract_client import AbstractClient  # verified existing pattern
```

### Existing Class Signatures (re-verified 2026-04-27)

```python
# packages/ai-parrot/src/parrot/bots/abstract.py:144
class AbstractBot(VectorInterface, ...):
    # Conversation settings (line 386–388)
    self.max_context_turns: int = kwargs.get('max_context_turns', 50)
    self.context_search_limit: int = kwargs.get('context_search_limit', 10)
    self.context_score_threshold: float = kwargs.get('context_score_threshold', 0.7)

    # tool_manager (line 275): ToolManager instance
    # _semaphore (line 404): asyncio.BoundedSemaphore (max_concurrency=20 default)

    async def get_vector_context(                       # line 1587
        self,
        question: str,
        search_type: str = 'similarity',
        search_kwargs: Optional[dict] = None,
        metric_type: str = 'COSINE',
        limit: Optional[int] = None,
        score_threshold: Optional[float] = None,
        ensemble_config: Optional[dict] = None,
        return_sources: bool = True,
    ) -> Tuple[str, Dict[str, Any]]: ...

    async def _build_vector_context(                    # line 2239
        self,
        question: str,
        use_vectors: bool = True,
        search_type: str = 'similarity',
        search_kwargs: dict = None,
        ensemble_config: dict = None,
        metric_type: str = 'COSINE',
        limit: int = 10,
        score_threshold: float = None,
        return_sources: bool = True,
    ) -> Tuple[str, Dict[str, Any]]: ...
```

```python
# packages/ai-parrot/src/parrot/bots/base.py:28
class BaseBot(AbstractBot):
    async def conversation(                             # line 46
        self, question: str, session_id: Optional[str] = None, ...
    ) -> AIMessage: ...

    async def ask(                                       # line 562
        self, question: str, ...
    ) -> AIMessage: ...

    async def ask_stream(                                # line 973
        self, question: str, ...
    ) -> AsyncIterator[AIMessage]: ...
```

```python
# packages/ai-parrot/src/parrot/stores/models.py:7
class SearchResult(BaseModel):
    # content, score, metadata, id, embedding (verified via class definition)

# packages/ai-parrot/src/parrot/stores/models.py:21
class Document(BaseModel): ...
```

```python
# packages/ai-parrot/src/parrot/interfaces/vector.py:110
class VectorInterface:
    async def _ensemble_search(self, store, question, config, score_threshold,
                               metric_type, search_kwargs=None) -> dict: ...
    def _combine_search_results(self, similarity_results, mmr_results, config) -> list: ...   # line 155
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `AbstractReranker` | `AbstractBot.reranker` attribute | constructor kwarg, optional | new attribute, no existing line |
| `LocalCrossEncoderReranker.rerank()` | `AbstractBot._build_vector_context()` | direct `await` after `get_vector_context` returns | `parrot/bots/abstract.py:2239` |
| `LocalCrossEncoderReranker.rerank()` | `AbstractBot.get_vector_context()` | direct `await` between retrieval and context formatting | `parrot/bots/abstract.py:1587` (around line 1696, before `if not search_results`) |
| `RerankedDocument.document` | `parrot.stores.models.SearchResult` | composition (Pydantic field) | `parrot/stores/models.py:7` |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot/rerankers/`~~ — directory does not exist; this feature creates it.
- ~~`AbstractReranker`, `LocalCrossEncoderReranker`, `LLMReranker`~~ — none exist.
- ~~`AbstractBot.reranker`~~ — attribute does not exist; this feature adds it.
- ~~`AbstractBot.rerank_oversample_factor`~~ — attribute does not exist; this feature adds it.
- ~~`SearchResult.rerank_score`, `SearchResult.rerank_rank`~~ — DO NOT add these to
  `SearchResult`. Reranker scoring lives on `RerankedDocument` via composition.
- ~~`store.rerank(...)`~~ — no store has a public `rerank` method. The `_rerank_with_chunk_context`
  in `parrot/stores/postgres.py:2749` is a private chunk-context expansion, NOT a
  cross-encoder reranker, and is unrelated to this feature.
- ~~`parrot.rerankers.cohere`, `parrot.rerankers.jina_cloud`~~ — out of scope. No cloud
  reranker implementations are part of this feature.
- ~~`search_type='rerank'`~~ — do not add a new `search_type` value. Reranking is
  orthogonal to retrieval mode and applies to whatever `search_type` the caller picked.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Follow the `AbstractClient` / `AbstractStore` async-first pattern: ABC with one
  required `async` method plus optional `load()` / `cleanup()` lifecycle.
- All structured data uses Pydantic v2 (`model_copy`, not `.copy()`).
- Use `self.logger = logging.getLogger(__name__)` per `.agent/CONTEXT.md`. No `print`.
- Do NOT add direct LangChain imports.
- HuggingFace model loads must be wrapped in `asyncio.to_thread` if invoked from async
  init paths; otherwise load synchronously at construction (preferred — eager warmup).
- `torch.inference_mode()` and `model.eval()` for every forward pass.
- Truncate tokenisation at `max_length=512` by default. BGE supports 8k but the
  latency cost is not justified at our query lengths.
- Use a process-wide singleton cache keyed by `(model_name, device, precision)` so two
  bots configured with the same reranker share one model in memory.

### Known Risks / Gotchas

1. **Threshold semantics shift.** `context_score_threshold=0.7` is calibrated for cosine
   distance returned by the vector store. Cross-encoder logits are unbounded and not
   comparable. The threshold remains applied *pre-rerank* (filters the candidate pool),
   not post-rerank. Document this clearly. A separate follow-up may introduce
   `rerank_score_threshold` as a dedicated knob, but it is out of scope here.
2. **Jina v2 `trust_remote_code=True`.** Jina's v2 reranker uses a custom HF architecture
   class loaded via `trust_remote_code`. Some hardened pipelines block this for security
   reasons. The default model (BGE v2-m3) does not require it; document the requirement
   for users selecting Jina.
3. **CPU INT8 quantization quality drift.** PyTorch dynamic quantization on `nn.Linear`
   layers typically loses 1–3 nDCG points vs FP32. The benchmark harness must report
   both; if drift is >5 points on the eval set, drop INT8 from the `'auto'` policy on
   CPU and require explicit `precision='int8'`.
4. **GPU memory under concurrency.** Multiple concurrent `rerank()` calls on the same
   GPU can OOM with large models. Serialize via `ThreadPoolExecutor(max_workers=1)`
   per device, or at minimum cap concurrent forward passes via the existing bot
   semaphore. Do NOT spawn new threads per request.
5. **Cold start cost.** Loading BGE v2-m3 weights from disk is 3–8 seconds. The eager
   warmup at `__init__` is non-negotiable for production; a lazy-load default would
   shift this cost onto the first user of the day. The `warmup=True` flag should
   default to `True`.
6. **First-class HF cache control.** Respect `HF_HOME` / `TRANSFORMERS_CACHE`. Do not
   download to a per-process temp dir.
7. **Async event loop.** `asyncio.to_thread` is sufficient for occasional offloading
   but a long-lived dedicated executor is preferable when QPS > 1. Keep the executor
   as a class attribute, not a per-call instance.
8. **Graceful degradation.** If `transformers` import fails (e.g. someone strips ML
   deps for a lightweight bot deployment), `parrot.rerankers.local` must raise a clear
   `ImportError` at module import time with installation guidance, not at first
   `rerank()` call.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `transformers` | `>=4.48.0,<5.0` (already pinned) | Cross-encoder model loading. |
| `torch` | already pinned via `torchvision>=0.23.0,<0.24` (~2.8) | Inference + INT8 quantization. |
| `sentence_transformers` | `>=5.0.0` (already pinned) | Optional convenience wrapper for `CrossEncoder` batching; if not used directly, can remain transitive. |

**No new dependencies are introduced by this feature.** Confirmed against
`packages/ai-parrot/pyproject.toml`.

---

## 8. Open Questions

- [ ] Should `reranker` be exposed in the `chatbot.yaml` / DB-driven bot config (the
      `_from_db` path in `parrot/bots/chatbot.py:387`) or is constructor-only acceptable
      for the first iteration? — *Owner: Jesus Lara*
- [ ] Default `rerank_oversample_factor`: 3 vs 4 vs 5. The benchmark harness should
      inform the final default; ship 4 and revisit. — *Owner: implementation*
- [ ] Should the benchmark harness be wired into a `make benchmark-reranker` target or
      remain a standalone script under `scripts/`? — *Owner: Jesus Lara*
- [ ] Do we want a `RerankerRegistry` (mirroring `register_agent`) so users can name
      rerankers in YAML, or is direct constructor injection enough for v1? — *Owner: implementation*
- [ ] Eval set composition: 100% synthetic vs. drawn from real production logs (with
      PII redaction). Real logs give better signal but are slower to assemble. —
      *Owner: Jesus Lara + data-protection lead*

---

## Worktree Strategy

**Default isolation unit: `per-spec` (sequential tasks).**

Tasks within this feature have a clear dependency chain:

1. Models (Module 2) → ABC (Module 3) → Local impl (Module 4) → LLM impl (Module 5)
   → Bot integration (Module 6) → Benchmark harness (Module 7) → Tests (Module 8).

There is no parallelism gain from splitting these across worktrees; the surface area
is small (~6 new files + 1 modified file in bots/abstract.py) and the integration test
suite needs the full chain to be coherent. Run all tasks sequentially in a single
worktree branched from `dev`:

```bash
git worktree add -b feat-126-local-cross-encoder-reranker \
  .claude/worktrees/feat-126-local-cross-encoder-reranker HEAD
```

**Cross-feature dependencies**: none. This spec does not depend on any other in-flight
feature and does not block any other in the `sdd/specs/` queue.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-04-27 | Jesus Lara | Initial draft from in-conversation design. |
