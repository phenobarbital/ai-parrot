# TASK-865: LLMReranker Debug Implementation

**Feature**: FEAT-126 — Local Cross-Encoder Reranker for RAG Retrieval
**Spec**: `sdd/specs/local-cross-encoder-reranker.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-863
**Assigned-to**: unassigned

---

## Context

This task creates `LLMReranker`, a debug/fallback reranker that uses the bot's
existing LLM via `AbstractClient.completion()` to score `(query, document)` pairs.
It is NOT intended for production hot-path use — it exists so engineers can
sanity-check the `LocalCrossEncoderReranker` against a strong reference (e.g. GPT-4,
Claude) without external reranking services.

Implements spec Module 5.

---

## Scope

- Implement `parrot/rerankers/llm.py` with `LLMReranker` class.
- Takes an `AbstractClient` instance at construction.
- Scores each `(query, document)` pair via a structured-output prompt that returns
  a numeric relevance score (0.0–1.0).
- Sorts by score descending and returns `list[RerankedDocument]`.
- Error handling: on LLM failure, log WARNING and return original-order results
  with `rerank_score=float('nan')`.
- Update `parrot/rerankers/__init__.py` to export `LLMReranker`.

**NOT in scope**:
- Production optimization (batching, caching) — this is a debug tool
- Bot integration (TASK-866)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/rerankers/llm.py` | CREATE | LLMReranker implementation |
| `packages/ai-parrot/src/parrot/rerankers/__init__.py` | MODIFY | Add LLMReranker to exports |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.rerankers.abstract import AbstractReranker  # created by TASK-863
from parrot.rerankers.models import RerankedDocument     # created by TASK-863
from parrot.stores.models import SearchResult            # verified: parrot/stores/models.py:7
from parrot.clients.base import AbstractClient           # verified: parrot/clients/base.py:231
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/clients/base.py:231
class AbstractClient(ABC):
    client_type: str = "generic"
    client_name: str = "generic"
    use_session: bool = False

    def __init__(
        self,
        conversation_memory=None,
        preset=None,
        tools=None,
        use_tools=False,
        debug=True,
        tool_manager=None,
        **kwargs
    ): ...

    # The completion method is the key interface for LLMReranker.
    # Verify the exact signature before implementing — it varies by subclass.
    # Base pattern: async def completion(prompt, ...) -> response
```

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
```

### Does NOT Exist

- ~~`parrot.rerankers.llm`~~ — does not exist; this task creates it.
- ~~`LLMReranker`~~ — does not exist; this task creates it.
- ~~`AbstractClient.rerank()`~~ — no such method on AbstractClient.
- ~~`AbstractClient.structured_output()`~~ — verify what the actual structured output
  interface is before using it. Use `completion()` with a prompt that requests JSON.

---

## Implementation Notes

### Design Pattern

```python
class LLMReranker(AbstractReranker):
    def __init__(self, client: AbstractClient, **kwargs):
        self.client = client
        self.logger = logging.getLogger(__name__)

    async def rerank(self, query, documents, top_n=None):
        # For each document, ask the LLM to score relevance 0.0-1.0
        # Use a simple structured prompt:
        #   "Rate the relevance of this passage to the query on a scale of 0.0 to 1.0.
        #    Query: {query}
        #    Passage: {document.content}
        #    Respond with ONLY a number between 0.0 and 1.0."
        # Parse the numeric response
        # Sort by score descending
        # Return top_n RerankedDocuments
```

### Key Constraints

- Score each document independently (no batching needed — this is a debug tool)
- Use `asyncio.gather()` to score documents concurrently for reasonable throughput
- Parse the LLM response as a float; on parse failure, assign score 0.0 with a warning
- Measure and record `rerank_latency_ms` for the full batch
- The prompt must be simple and model-agnostic — work with any AbstractClient subclass

### References in Codebase

- `parrot/clients/base.py:231` — AbstractClient interface
- `parrot/rerankers/abstract.py` — AbstractReranker ABC (from TASK-863)

---

## Acceptance Criteria

- [ ] `LLMReranker` accepts an `AbstractClient` at construction
- [ ] `rerank()` scores each document via LLM completion
- [ ] Results sorted by score descending
- [ ] `top_n` truncation works
- [ ] LLM failure returns original-order results with NaN scores
- [ ] `from parrot.rerankers import LLMReranker` works
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/rerankers/llm.py`

---

## Test Specification

```python
# tests/unit/rerankers/test_llm_reranker.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot.rerankers import LLMReranker
from parrot.stores.models import SearchResult


@pytest.fixture
def fake_client():
    client = MagicMock()
    # Mock completion to return numeric scores
    scores = iter(["0.9", "0.3", "0.7"])
    client.completion = AsyncMock(side_effect=lambda *a, **kw: next(scores))
    return client


@pytest.fixture
def fake_search_results():
    return [
        SearchResult(id="1", content="relevant doc", metadata={}, score=0.8),
        SearchResult(id="2", content="irrelevant doc", metadata={}, score=0.85),
        SearchResult(id="3", content="somewhat relevant", metadata={}, score=0.75),
    ]


class TestLLMReranker:
    @pytest.mark.asyncio
    async def test_basic_ordering(self, fake_client, fake_search_results):
        reranker = LLMReranker(client=fake_client)
        results = await reranker.rerank("test query", fake_search_results)
        assert len(results) == 3
        assert results[0].rerank_score == 0.9
        assert results[1].rerank_score == 0.7
        assert results[2].rerank_score == 0.3

    @pytest.mark.asyncio
    async def test_top_n_truncation(self, fake_client, fake_search_results):
        reranker = LLMReranker(client=fake_client)
        results = await reranker.rerank("test query", fake_search_results, top_n=2)
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_failure_returns_original_order(self, fake_search_results):
        client = MagicMock()
        client.completion = AsyncMock(side_effect=RuntimeError("LLM down"))
        reranker = LLMReranker(client=client)
        results = await reranker.rerank("test", fake_search_results)
        assert len(results) == 3
        import math
        assert all(math.isnan(r.rerank_score) for r in results)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/local-cross-encoder-reranker.spec.md` §2 and Module 5
2. **Check dependencies** — verify TASK-863 is in `tasks/completed/`
3. **Verify the Codebase Contract** — confirm `AbstractClient.completion()` signature
   by reading `parrot/clients/base.py`. The exact return type matters for parsing.
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** `llm.py` and update `__init__.py`
6. **Run tests**: `pytest tests/unit/rerankers/test_llm_reranker.py -v`
7. **Move this file** to `tasks/completed/`
8. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
