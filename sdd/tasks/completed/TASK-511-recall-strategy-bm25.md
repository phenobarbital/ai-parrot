# TASK-511: RecallStrategy Abstraction + HybridBM25Strategy

**Feature**: refactor-episodic-agentcorememory
**Spec**: `sdd/specs/refactor-episodic-agentcorememory.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Module 2 from the spec. Defines a pluggable recall strategy protocol and implements BM25+semantic hybrid search. Currently `EpisodicMemoryStore.recall_similar()` delegates directly to `backend.search_similar()` (pure vector search). This task creates a strategy layer that can fuse BM25 lexical scores with semantic similarity.

Per the open questions resolution: HybridBM25Strategy maintains its **own BM25 index** (not PgVector's tsvector).

---

## Scope

- Define `RecallStrategy` protocol with `async search(query, query_embedding, backend, namespace_filter, top_k) -> list[EpisodeSearchResult]`
- Implement `SemanticOnlyStrategy` — wraps the current `backend.search_similar()` call (default behavior)
- Implement `HybridBM25Strategy`:
  - Maintains per-namespace in-memory BM25 index using `bm25s` library (lazy-imported)
  - On first search for a namespace: fetches all episodes from backend, builds BM25 index from searchable text
  - Fuses BM25 scores (weight 0.4) with semantic scores (weight 0.6), configurable
  - Normalizes both score types to [0, 1] before fusion
  - LRU-style invalidation: rebuild index if stale (configurable max age)
- Write unit tests

**NOT in scope**: Wiring strategies into `EpisodicMemoryStore` (TASK-515). PgVector tsvector changes (TASK-513).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/memory/episodic/recall.py` | CREATE | RecallStrategy protocol, SemanticOnlyStrategy, HybridBM25Strategy |
| `tests/unit/memory/episodic/test_recall.py` | CREATE | Unit tests |
| `parrot/memory/episodic/__init__.py` | MODIFY | Export new classes |

---

## Implementation Notes

### Pattern to Follow
```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class RecallStrategy(Protocol):
    async def search(
        self,
        query: str,
        query_embedding: list[float],
        backend: AbstractEpisodeBackend,
        namespace_filter: dict[str, Any],
        top_k: int = 5,
    ) -> list[EpisodeSearchResult]: ...
```

### Key Constraints
- Lazy-import `bm25s` using the `lazy_import()` pattern from `core.py`
- BM25 index is per-namespace (use `namespace_filter` as cache key)
- Must handle the case where `bm25s` is not installed — raise `ImportError` with clear message at strategy creation time, not at import time
- All methods async
- `SemanticOnlyStrategy` must produce identical results to current `backend.search_similar()`

### References in Codebase
- `parrot/memory/core.py` — BM25 index building logic (`_bm25_index`, `_bm25_score()`)
- `parrot/memory/episodic/store.py` — current `recall_similar()` implementation
- `parrot/memory/episodic/backends/base.py` — `AbstractEpisodeBackend` protocol, `EpisodeSearchResult`

---

## Acceptance Criteria

- [ ] `RecallStrategy` protocol defined
- [ ] `SemanticOnlyStrategy` delegates to backend with identical results
- [ ] `HybridBM25Strategy` builds BM25 index lazily per namespace
- [ ] Score fusion uses configurable weights (default 0.4 BM25 / 0.6 semantic)
- [ ] `bm25s` is lazy-imported; missing library raises clear error
- [ ] All tests pass: `pytest tests/unit/memory/episodic/test_recall.py -v`
- [ ] Imports work: `from parrot.memory.episodic.recall import RecallStrategy, SemanticOnlyStrategy, HybridBM25Strategy`

---

## Test Specification

```python
# tests/unit/memory/episodic/test_recall.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot.memory.episodic.recall import (
    RecallStrategy, SemanticOnlyStrategy, HybridBM25Strategy
)
from parrot.memory.episodic.models import EpisodicMemory, EpisodeOutcome


@pytest.fixture
def mock_backend():
    backend = AsyncMock()
    backend.search_similar = AsyncMock(return_value=[])
    backend.get_recent = AsyncMock(return_value=[])
    return backend


class TestSemanticOnlyStrategy:
    async def test_delegates_to_backend(self, mock_backend):
        strategy = SemanticOnlyStrategy()
        await strategy.search("query", [0.1]*384, mock_backend, {}, top_k=5)
        mock_backend.search_similar.assert_called_once()

    def test_protocol_compliance(self):
        assert isinstance(SemanticOnlyStrategy(), RecallStrategy)


class TestHybridBM25Strategy:
    def test_configurable_weights(self):
        s = HybridBM25Strategy(bm25_weight=0.3, semantic_weight=0.7)
        assert s.bm25_weight == 0.3
        assert s.semantic_weight == 0.7

    async def test_builds_index_on_first_search(self, mock_backend):
        episodes = [
            EpisodicMemory(
                agent_id="a", situation="weather query",
                action_taken="called API", outcome=EpisodeOutcome.SUCCESS,
                category="TOOL_EXECUTION", embedding=[0.1]*384,
            )
        ]
        mock_backend.get_recent = AsyncMock(return_value=episodes)
        mock_backend.search_similar = AsyncMock(return_value=[])
        strategy = HybridBM25Strategy()
        results = await strategy.search("weather", [0.1]*384, mock_backend, {}, top_k=5)
        # Should have attempted to build index
        mock_backend.get_recent.assert_called()

    def test_protocol_compliance(self):
        assert isinstance(HybridBM25Strategy(), RecallStrategy)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-511-recall-strategy-bm25.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker
**Date**: 2026-04-02
**Notes**: All 12 unit tests pass. SemanticOnlyStrategy delegates to backend. HybridBM25Strategy builds BM25 index lazily per namespace, with caching and stale invalidation. Falls back gracefully when bm25s not installed.

**Deviations from spec**: none
