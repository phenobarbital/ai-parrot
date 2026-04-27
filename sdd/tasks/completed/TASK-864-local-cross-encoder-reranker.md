# TASK-864: LocalCrossEncoderReranker Implementation

**Feature**: FEAT-126 — Local Cross-Encoder Reranker for RAG Retrieval
**Spec**: `sdd/specs/local-cross-encoder-reranker.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-863
**Assigned-to**: unassigned

---

## Context

This is the core implementation task. It creates `LocalCrossEncoderReranker`, which
loads a HuggingFace cross-encoder model in-process and scores `(query, passage)` pairs
via batched forward passes. This is the production reranker — it must handle device
autodetection, precision selection (FP16 on GPU, INT8 on CPU), eager warmup, graceful
error handling, and process-wide model caching.

Implements spec Module 4.

---

## Scope

- Implement `parrot/rerankers/local.py` with `LocalCrossEncoderReranker` class.
- Device autodetect: CUDA if available, else CPU.
- Precision autodetect: FP16 on CUDA, INT8 (`torch.quantize_dynamic` on `nn.Linear`) on CPU.
- Tokenisation of all `(query, passage)` pairs in configurable `batch_size` mini-batches.
- Forward pass under `torch.inference_mode()` with `model.eval()`.
- Async wrapping via `ThreadPoolExecutor(max_workers=1)` per device as a class attribute.
- Process-wide singleton cache keyed by `(model_name, device, precision)`.
- Eager warmup at `__init__` with a dummy pair.
- Error path: catch `Exception`, log at WARNING, return original-order `RerankedDocument`
  list with `rerank_score=float('nan')`.
- Clear `ImportError` if `transformers` or `torch` are not installed.
- Update `parrot/rerankers/__init__.py` to export `LocalCrossEncoderReranker`.

**NOT in scope**:
- `LLMReranker` (TASK-865)
- Bot integration (TASK-866)
- Benchmark harness (TASK-868)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/rerankers/local.py` | CREATE | LocalCrossEncoderReranker implementation |
| `packages/ai-parrot/src/parrot/rerankers/__init__.py` | MODIFY | Add LocalCrossEncoderReranker to exports |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.rerankers.abstract import AbstractReranker  # created by TASK-863
from parrot.rerankers.models import RerankedDocument, RerankerConfig  # created by TASK-863
from parrot.stores.models import SearchResult            # verified: parrot/stores/models.py:7
```

```python
# External dependencies (all already pinned in pyproject.toml)
import torch                          # available via sentence-transformers dep
from transformers import AutoTokenizer, AutoModelForSequenceClassification  # >=4.48.0
import logging
import asyncio
from concurrent.futures import ThreadPoolExecutor
```

### Existing Signatures to Use

```python
# Created by TASK-863 — parrot/rerankers/abstract.py
class AbstractReranker(ABC):
    @abstractmethod
    async def rerank(
        self,
        query: str,
        documents: list[SearchResult],
        top_n: Optional[int] = None,
    ) -> list[RerankedDocument]: ...

    async def load(self) -> None: ...
    async def cleanup(self) -> None: ...

# Created by TASK-863 — parrot/rerankers/models.py
class RerankerConfig(BaseModel):
    model_name: str = "BAAI/bge-reranker-v2-m3"
    device: str = "auto"
    precision: str = "auto"
    max_length: int = 512
    batch_size: int = 32
    trust_remote_code: bool = False
    warmup: bool = True

class RerankedDocument(BaseModel):
    document: SearchResult
    rerank_score: float = Field(...)
    rerank_rank: int = Field(..., ge=0)
    original_rank: int = Field(..., ge=0)
    rerank_model: str = Field(...)
    rerank_latency_ms: Optional[float] = None
```

```python
# packages/ai-parrot/src/parrot/stores/models.py:7
class SearchResult(BaseModel):
    id: str
    content: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    score: float
    ensemble_score: float = None
    search_source: str = None
    similarity_rank: Optional[int] = None
    mmr_rank: Optional[int] = None
```

### Does NOT Exist

- ~~`parrot.rerankers.local`~~ — does not exist; this task creates it.
- ~~`LocalCrossEncoderReranker`~~ — does not exist; this task creates it.
- ~~`sentence_transformers.CrossEncoder`~~ — exists in the library but do NOT use it as
  the primary path. Use `transformers.AutoModelForSequenceClassification` directly for
  full control over tokenization, batching, and quantization. `CrossEncoder` may be
  referenced as an alternative in comments but is not the implementation path.
- ~~`store.rerank()`~~ — no store has a public rerank method.
- ~~`parrot.rerankers.cohere`~~ — out of scope; no cloud reranker implementations.

---

## Implementation Notes

### Constructor Pattern

```python
class LocalCrossEncoderReranker(AbstractReranker):
    _model_cache: ClassVar[dict] = {}  # (model_name, device, precision) -> (model, tokenizer)
    _executors: ClassVar[dict] = {}    # device_str -> ThreadPoolExecutor(max_workers=1)

    def __init__(self, config: Optional[RerankerConfig] = None, **kwargs):
        # Accept config object OR individual kwargs
        # Resolve device: 'auto' -> 'cuda' if torch.cuda.is_available() else 'cpu'
        # Resolve precision: 'auto' -> 'fp16' on cuda, 'int8' on cpu
        # Load model (from cache or fresh)
        # Apply quantization if int8
        # Warmup with dummy pair if config.warmup
        self.logger = logging.getLogger(__name__)
```

### Key Implementation Details

1. **Model loading**: Use `AutoModelForSequenceClassification.from_pretrained()` with
   `trust_remote_code=config.trust_remote_code`. Respect `HF_HOME` / `TRANSFORMERS_CACHE`.
2. **INT8 quantization on CPU**:
   ```python
   torch.quantization.quantize_dynamic(model, {torch.nn.Linear}, dtype=torch.qint8)
   ```
3. **FP16 on CUDA**: `model.half()` after loading.
4. **Forward pass**: Tokenize with `tokenizer(pairs, padding=True, truncation=True, max_length=...)`,
   then `model(**inputs).logits.squeeze(-1)` for relevance scores.
5. **Batching**: When `len(documents) > batch_size`, chunk into mini-batches and concatenate scores.
6. **Async wrapping**: Use a class-level `ThreadPoolExecutor(max_workers=1)` per device.
   Run the synchronous `_rerank_sync()` via `loop.run_in_executor(self._executor, ...)`.
7. **Error handling**: Wrap the entire scoring path in try/except. On failure, log WARNING
   and return documents in original order with `rerank_score=float('nan')`.
8. **Warmup**: After model load, run a single forward pass with `("warmup", "warmup passage")`
   to trigger CUDA kernel JIT and weight materialization.
9. **Import guard**: At module top, wrap `import torch` and `import transformers` in
   try/except ImportError with a clear message.

### Jina v2 Compatibility

`jinaai/jina-reranker-v2-base-multilingual` requires `trust_remote_code=True` because
it uses a custom HF architecture class. If a user tries to load it with
`trust_remote_code=False`, raise a clear `ValueError` explaining the requirement.

### References in Codebase

- `parrot/stores/abstract.py:17` — AbstractStore pattern for ABC + lifecycle
- `parrot/clients/base.py:231` — AbstractClient pattern for logger + init

---

## Acceptance Criteria

- [ ] `LocalCrossEncoderReranker` loads and reranks with `cross-encoder/ms-marco-MiniLM-L-12-v2` on CPU
- [ ] Device autodetect works: CPU path when no CUDA available
- [ ] INT8 quantization applied when `device='cpu'` and `precision='auto'`
- [ ] FP16 applied when CUDA available and `precision='auto'` (skip if no CUDA)
- [ ] Process-wide model cache prevents duplicate loads for same `(model, device, precision)`
- [ ] Eager warmup runs at construction
- [ ] Error in model forward pass returns original-order results with NaN scores
- [ ] Empty input returns `[]` without forward pass
- [ ] `top_n` truncation works correctly
- [ ] `original_rank` preserved correctly on each `RerankedDocument`
- [ ] `from parrot.rerankers import LocalCrossEncoderReranker` works
- [ ] Clear `ImportError` if `transformers`/`torch` not installed

---

## Test Specification

```python
# tests/unit/rerankers/test_local_reranker.py
import pytest
from unittest.mock import patch, MagicMock
from parrot.rerankers import LocalCrossEncoderReranker, RerankerConfig
from parrot.stores.models import SearchResult


@pytest.fixture(scope="session")
def minilm_reranker():
    return LocalCrossEncoderReranker(
        config=RerankerConfig(
            model_name="cross-encoder/ms-marco-MiniLM-L-12-v2",
            device="cpu",
            precision="fp32",
            warmup=True,
        )
    )


@pytest.fixture
def fake_search_results():
    return [
        SearchResult(id=str(i), content=text, metadata={}, score=0.9 - i * 0.1)
        for i, text in enumerate([
            "Python is a programming language",
            "The weather today is sunny",
            "Machine learning uses neural networks",
            "Cooking recipes for pasta",
            "Deep learning frameworks comparison",
        ])
    ]


class TestLocalCrossEncoderReranker:
    @pytest.mark.asyncio
    async def test_rerank_orders_descending(self, minilm_reranker, fake_search_results):
        results = await minilm_reranker.rerank(
            "What is deep learning?", fake_search_results
        )
        assert len(results) == 5
        assert all(results[i].rerank_score >= results[i + 1].rerank_score
                    for i in range(len(results) - 1))

    @pytest.mark.asyncio
    async def test_top_n_truncation(self, minilm_reranker, fake_search_results):
        results = await minilm_reranker.rerank(
            "test query", fake_search_results, top_n=3
        )
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_preserves_original_rank(self, minilm_reranker, fake_search_results):
        results = await minilm_reranker.rerank(
            "test query", fake_search_results
        )
        original_ranks = {r.original_rank for r in results}
        assert original_ranks == {0, 1, 2, 3, 4}

    @pytest.mark.asyncio
    async def test_handles_empty_input(self, minilm_reranker):
        results = await minilm_reranker.rerank("test query", [])
        assert results == []

    @pytest.mark.asyncio
    async def test_failure_returns_original_order(self, fake_search_results):
        reranker = LocalCrossEncoderReranker(
            config=RerankerConfig(
                model_name="cross-encoder/ms-marco-MiniLM-L-12-v2",
                device="cpu", precision="fp32", warmup=False,
            )
        )
        with patch.object(reranker, '_rerank_sync', side_effect=RuntimeError("boom")):
            results = await reranker.rerank("test", fake_search_results)
        assert len(results) == 5
        import math
        assert all(math.isnan(r.rerank_score) for r in results)
        assert [r.original_rank for r in results] == [0, 1, 2, 3, 4]

    def test_int8_quantization_applied_on_cpu(self):
        reranker = LocalCrossEncoderReranker(
            config=RerankerConfig(
                model_name="cross-encoder/ms-marco-MiniLM-L-12-v2",
                device="cpu", precision="int8", warmup=False,
            )
        )
        # At least one Linear layer should be quantized
        import torch
        has_quantized = any(
            isinstance(m, torch.nn.quantized.dynamic.Linear)
            for m in reranker._model.modules()
        )
        assert has_quantized
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/local-cross-encoder-reranker.spec.md` §2 and §7
2. **Check dependencies** — verify TASK-863 is in `tasks/completed/`
3. **Verify the Codebase Contract** — confirm `AbstractReranker` and models exist from TASK-863
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** `local.py` and update `__init__.py`
6. **Run tests**: `pytest tests/unit/rerankers/test_local_reranker.py -v`
7. **Move this file** to `tasks/completed/`
8. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
