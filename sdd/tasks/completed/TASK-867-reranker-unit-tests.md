# TASK-867: Comprehensive Unit Tests for Reranker Subsystem

**Feature**: FEAT-126 — Local Cross-Encoder Reranker for RAG Retrieval
**Spec**: `sdd/specs/local-cross-encoder-reranker.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-863, TASK-864, TASK-865, TASK-866
**Assigned-to**: unassigned

---

## Context

This task consolidates and expands the unit test suite for the entire reranker
subsystem. While individual tasks (TASK-863 through TASK-866) include basic test
scaffolds, this task ensures comprehensive coverage including edge cases, the full
test matrix from spec §4, and proper test fixtures shared across the suite.

Implements spec Module 8 (unit test portion).

---

## Scope

- Create shared test fixtures in `tests/unit/rerankers/conftest.py`.
- Ensure all unit tests from spec §4 are implemented and passing.
- Add edge case tests: single document, duplicate scores, very long passages,
  concurrent rerank calls.
- Verify `conftest.py` provides `minilm_reranker` (session-scoped) and
  `fake_search_results` fixtures.

**NOT in scope**:
- Integration tests (TASK-868)
- Benchmark harness (TASK-868)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/unit/rerankers/__init__.py` | CREATE | Test package init |
| `packages/ai-parrot/tests/unit/rerankers/conftest.py` | CREATE | Shared fixtures |
| `packages/ai-parrot/tests/unit/rerankers/test_models_and_abstract.py` | CREATE or VERIFY | Models + ABC tests |
| `packages/ai-parrot/tests/unit/rerankers/test_local_reranker.py` | CREATE or VERIFY | LocalCrossEncoderReranker tests |
| `packages/ai-parrot/tests/unit/rerankers/test_llm_reranker.py` | CREATE or VERIFY | LLMReranker tests |
| `packages/ai-parrot/tests/unit/rerankers/test_bot_integration.py` | CREATE or VERIFY | Bot integration tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# All created by prior tasks (TASK-863 through TASK-866)
from parrot.rerankers import (
    AbstractReranker,
    LocalCrossEncoderReranker,
    LLMReranker,
    RerankedDocument,
    RerankerConfig,
)
from parrot.stores.models import SearchResult  # verified: parrot/stores/models.py:7
from parrot.bots.abstract import AbstractBot   # verified: parrot/bots/abstract.py:144
```

### Does NOT Exist

- ~~`parrot.rerankers.test_utils`~~ — no test utilities module; create fixtures in conftest.py
- ~~`SearchResult.rerank_score`~~ — reranker data lives on `RerankedDocument`
- ~~`AbstractBot.rerank()`~~ — no such method; reranking happens inside `_build_vector_context()`

---

## Implementation Notes

### Required Test Matrix (from spec §4)

| Test ID | Description | Module |
|---|---|---|
| `test_abstract_reranker_is_abc` | Cannot instantiate directly | Abstract |
| `test_local_reranker_init_minilm_cpu` | Loads MiniLM on CPU, warmup runs | Local |
| `test_local_reranker_rerank_orders_descending` | Most relevant doc is rank 0 | Local |
| `test_local_reranker_top_n_truncation` | `top_n=3` returns exactly 3 | Local |
| `test_local_reranker_preserves_original_rank` | Correct `original_rank` on each doc | Local |
| `test_local_reranker_handles_empty_input` | Empty docs returns `[]` | Local |
| `test_local_reranker_failure_returns_original_order` | Mock model raise → NaN + original order | Local |
| `test_local_reranker_truncates_to_max_length` | Long passages tokenized with truncation | Local |
| `test_int8_quantization_applied_on_cpu` | Quantized linear layers present | Local |
| `test_fp16_applied_on_cuda` | FP16 dtype on CUDA (skip if no CUDA) | Local |
| `test_jina_requires_trust_remote_code` | Error without trust_remote_code for Jina | Local |
| `test_llm_reranker_basic` | Fake client → ordering matches scores | LLM |
| `test_abstractbot_no_reranker_path_unchanged` | No reranker → same output as before | Bot |
| `test_abstractbot_with_reranker_oversamples` | Reranker → search called with limit*factor | Bot |
| `test_abstractbot_reranker_failure_falls_back` | Reranker NaN → original order fallback | Bot |

### Shared Fixtures (conftest.py)

```python
import pytest
from parrot.stores.models import SearchResult


@pytest.fixture(scope="session")
def minilm_reranker():
    from parrot.rerankers import LocalCrossEncoderReranker, RerankerConfig
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
    texts = [
        "Python is a programming language used for AI",
        "The weather today is sunny and warm",
        "Machine learning uses neural networks for prediction",
        "Cooking recipes for Italian pasta dishes",
        "Deep learning frameworks like PyTorch and TensorFlow",
    ]
    return [
        SearchResult(id=str(i), content=text, metadata={}, score=0.9 - i * 0.1)
        for i, text in enumerate(texts)
    ]
```

### Key Constraints

- CI must use **MiniLM-L-12-v2** for any test that loads a real model (small, fast)
- BGE v2-m3 and Jina v2 are too large for CI — only in benchmark harness
- Mark CUDA-only tests with `@pytest.mark.skipif(not torch.cuda.is_available(), ...)`
- Mark Jina tests that require model download with appropriate skip markers
- Use `pytest-asyncio` for all async tests

---

## Acceptance Criteria

- [ ] All 15 tests from spec §4 unit test table implemented and passing
- [ ] Shared fixtures in `conftest.py` work across all test files
- [ ] All tests pass: `pytest packages/ai-parrot/tests/unit/rerankers/ -v`
- [ ] No test requires GPU (CUDA tests are skipped when unavailable)
- [ ] No test downloads BGE or Jina models (use MiniLM only)
- [ ] Test run completes in under 60 seconds on CPU

---

## Test Specification

See the test matrix above. Each test must be implemented following the scaffolds
provided in TASK-863, TASK-864, TASK-865, and TASK-866. This task's added value is:

1. Consolidating all tests into a coherent suite with shared fixtures
2. Adding edge case tests not covered by individual task scaffolds:
   - Single document input
   - All documents with identical content
   - Very long passage (> 2x max_length)
   - `top_n` greater than number of documents
   - Concurrent `rerank()` calls (asyncio.gather)
3. Ensuring the test directory structure is correct and discoverable by pytest

---

## Agent Instructions

When you pick up this task:

1. **Check dependencies** — verify TASK-863, 864, 865, 866 are in `tasks/completed/`
2. **Verify** that test files from prior tasks exist; if they do, extend them rather
   than rewriting
3. **Create** `conftest.py` with shared fixtures
4. **Fill gaps** in the test matrix — add any missing tests from the spec §4 table
5. **Add edge case tests** listed above
6. **Run full suite**: `pytest packages/ai-parrot/tests/unit/rerankers/ -v`
7. **Move this file** to `tasks/completed/`
8. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
