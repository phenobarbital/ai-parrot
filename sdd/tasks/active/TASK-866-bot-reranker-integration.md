# TASK-866: Wire Reranker into AbstractBot Retrieval Pipeline

**Feature**: FEAT-126 — Local Cross-Encoder Reranker for RAG Retrieval
**Spec**: `sdd/specs/local-cross-encoder-reranker.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-863, TASK-864
**Assigned-to**: unassigned

---

## Context

This task modifies `AbstractBot` to support an optional reranker in the retrieval
pipeline. When a reranker is configured, retrieval over-fetches candidates by a
configurable multiplier and the reranker keeps the top-N. When no reranker is
configured, the existing path is preserved byte-for-byte (backward compatible).

Implements spec Module 6.

---

## Scope

- Add `self.reranker: Optional[AbstractReranker]` attribute to `AbstractBot.__init__()`.
- Add `self.rerank_oversample_factor: int` attribute (default 4).
- Modify `AbstractBot.get_vector_context()` (line 1587) to over-fetch and rerank when
  `self.reranker` is set.
- Modify `AbstractBot._build_vector_context()` (line 2239) to over-fetch and rerank
  when `self.reranker` is set.
- On reranker failure (exception, NaN scores), log at WARNING and fall back to
  original retrieval order truncated to `limit`. Never raise to the caller.
- Update docstrings on `context_score_threshold` to note it is applied pre-rerank
  (cosine space, not reranker space).

**NOT in scope**:
- Exposing reranker in `chatbot.yaml` / DB-driven bot config (follow-up task)
- Adding `rerank_score_threshold` — out of scope per spec §7
- Changing `BaseBot.ask()` or `BaseBot.conversation()` signatures

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | Add reranker attribute + modify retrieval methods |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.rerankers.abstract import AbstractReranker  # created by TASK-863
from parrot.rerankers.models import RerankedDocument     # created by TASK-863
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/bots/abstract.py:144
class AbstractBot(
    MCPEnabledMixin,
    DBInterface,
    LocalKBMixin,
    ToolInterface,
    VectorInterface,
    ABC
):
    # line 387
    self.context_search_limit: int = kwargs.get('context_search_limit', 10)
    # line 388
    self.context_score_threshold: float = kwargs.get('context_score_threshold', 0.7)

    # line 1587
    async def get_vector_context(
        self,
        question: str,
        search_type: str = 'similarity',
        search_kwargs: dict = None,
        metric_type: str = 'COSINE',
        limit: int = 10,
        score_threshold: float = None,
        ensemble_config: dict = None,
        return_sources: bool = False,
    ) -> str: ...

    # line 2239
    async def _build_vector_context(
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

### Does NOT Exist

- ~~`AbstractBot.reranker`~~ — does not exist yet; this task adds it.
- ~~`AbstractBot.rerank_oversample_factor`~~ — does not exist yet; this task adds it.
- ~~`search_type='rerank'`~~ — DO NOT add a new search_type value. Reranking is
  orthogonal to retrieval mode.
- ~~`SearchResult.rerank_score`~~ — DO NOT modify SearchResult. Reranker data lives
  on `RerankedDocument`.

---

## Implementation Notes

### Where to Add Attributes

Add after line 388 (next to `context_score_threshold`):

```python
self.reranker = kwargs.get('reranker', None)
self.rerank_oversample_factor: int = int(kwargs.get('rerank_oversample_factor', 4))
```

Use a TYPE_CHECKING import for the type annotation to avoid forcing heavy imports:

```python
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from parrot.rerankers.abstract import AbstractReranker
```

### Modification Pattern for `_build_vector_context()`

The key modification is:
1. If `self.reranker` is set, multiply `limit` by `self.rerank_oversample_factor`
   for the upstream search call.
2. After search results are obtained, call `await self.reranker.rerank(question, results, top_n=original_limit)`.
3. Extract the `SearchResult` objects from the `RerankedDocument` wrappers to continue
   with the existing context-building logic.
4. Wrap in try/except: on failure, log WARNING and truncate original results to `limit`.

```python
# Pseudocode for the modification
original_limit = limit
if self.reranker:
    limit = limit * self.rerank_oversample_factor

# ... existing search logic with modified limit ...

if self.reranker and search_results:
    try:
        reranked = await self.reranker.rerank(question, search_results, top_n=original_limit)
        search_results = [r.document for r in reranked]
    except Exception as e:
        self.logger.warning("Reranker failed, falling back to retrieval order: %s", e)
        search_results = search_results[:original_limit]
```

### Same Pattern for `get_vector_context()`

Apply the identical over-fetch + rerank + fallback pattern to `get_vector_context()`.
The insertion point is after results are retrieved but before they are formatted into
context string.

### Key Constraints

- The score-threshold filter is applied **before** reranking (on the retrieval score),
  NOT after. This is intentional per spec §2.
- DO NOT change any method signatures — `BaseBot.ask()` and `BaseBot.conversation()`
  benefit transparently.
- The reranker is optional — when `self.reranker is None`, the code path MUST be
  identical to before (no performance overhead, no behavior change).
- Import `AbstractReranker` only under `TYPE_CHECKING` to keep `AbstractBot` importable
  without HF model deps.

### References in Codebase

- `parrot/bots/abstract.py:387-388` — where to add new attributes
- `parrot/bots/abstract.py:1587` — `get_vector_context()` to modify
- `parrot/bots/abstract.py:2239` — `_build_vector_context()` to modify

---

## Acceptance Criteria

- [ ] `AbstractBot` accepts `reranker` and `rerank_oversample_factor` kwargs
- [ ] Without `reranker`, `_build_vector_context()` produces identical output as before
- [ ] With `reranker`, upstream search is called with `limit * factor`
- [ ] Reranker result is used to reorder and truncate to original `limit`
- [ ] Reranker failure (exception) falls back to original retrieval order with WARNING log
- [ ] Score threshold is applied pre-rerank, not post-rerank
- [ ] `get_vector_context()` has the same reranker integration
- [ ] No new hard imports of `transformers` or `torch` in `abstract.py`
- [ ] Existing tests still pass: `pytest packages/ai-parrot/tests/ -k "bot" --timeout=60`

---

## Test Specification

```python
# tests/unit/rerankers/test_bot_integration.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.stores.models import SearchResult
from parrot.rerankers.models import RerankedDocument


class TestAbstractBotRerankerIntegration:
    @pytest.mark.asyncio
    async def test_no_reranker_path_unchanged(self):
        """Without reranker, _build_vector_context produces the same output."""
        # Create a minimal bot mock with self.reranker = None
        # Verify the search is called with the original limit
        # Verify output matches pre-reranker behavior
        ...

    @pytest.mark.asyncio
    async def test_with_reranker_oversamples(self):
        """When reranker is set, search is called with limit * factor."""
        # Create a minimal bot mock with a fake reranker
        # Verify search is called with limit * rerank_oversample_factor
        ...

    @pytest.mark.asyncio
    async def test_reranker_failure_falls_back(self):
        """A failing reranker falls back to original retrieval order."""
        # Create a bot with a reranker that raises
        # Verify results are in original order, truncated to limit
        # Verify WARNING was logged
        ...

    @pytest.mark.asyncio
    async def test_score_threshold_applied_pre_rerank(self):
        """Score threshold filters candidates before reranking, not after."""
        # Verify threshold filtering happens before reranker.rerank() is called
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/local-cross-encoder-reranker.spec.md` §2 and §6
2. **Check dependencies** — verify TASK-863 and TASK-864 are in `tasks/completed/`
3. **Verify the Codebase Contract** — read `parrot/bots/abstract.py` around lines
   387, 1587, and 2239. These may have shifted — find the actual current line numbers.
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** the modifications to `abstract.py`
6. **Run tests**: Existing bot tests + new integration tests
7. **Move this file** to `tasks/completed/`
8. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
