# TASK-515: EpisodicMemoryStore Integration

**Feature**: refactor-episodic-agentcorememory
**Spec**: `sdd/specs/refactor-episodic-agentcorememory.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-510, TASK-511, TASK-512
**Assigned-to**: unassigned

---

## Context

Module 6 from the spec. Wires the new `ImportanceScorer`, `RecallStrategy`, and `RedisVectorBackend` into `EpisodicMemoryStore`. This is the central integration task — it connects the modular utilities (TASK-510, TASK-511, TASK-512) into the existing store without breaking the default behavior.

---

## Scope

- Add `importance_scorer: ImportanceScorer | None` parameter to `EpisodicMemoryStore.__init__()`
- If scorer is provided, use it in `record_episode()` to compute importance (instead of inline logic)
- If scorer is None, preserve current behavior (inline heuristic)
- Add `recall_strategy: RecallStrategy | None` parameter to `__init__()`
- If strategy is provided, use it in `recall_similar()` instead of direct `backend.search_similar()`
- If strategy is None, preserve current behavior (direct backend call)
- Add `create_redis_vector()` factory method mirroring `create_pgvector()` and `create_faiss()`
- Update `__init__.py` exports
- Write integration tests verifying scorer/strategy injection

**NOT in scope**: Modifying the EpisodicMemory model. Changing the ReflectionEngine. Changing mixin behavior.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/memory/episodic/store.py` | MODIFY | Add scorer/strategy injection, create_redis_vector factory |
| `tests/unit/memory/episodic/test_store_integration.py` | CREATE | Tests for injection points |
| `parrot/memory/episodic/__init__.py` | MODIFY | Export create_redis_vector if needed |

---

## Implementation Notes

### Injection Pattern
```python
class EpisodicMemoryStore:
    def __init__(
        self,
        backend: AbstractEpisodeBackend,
        embedding_provider: EpisodeEmbeddingProvider,
        ...,
        importance_scorer: ImportanceScorer | None = None,
        recall_strategy: RecallStrategy | None = None,
    ):
        self._importance_scorer = importance_scorer
        self._recall_strategy = recall_strategy

    async def record_episode(self, ...):
        if self._importance_scorer:
            importance = self._importance_scorer.score(episode)
            episode.importance = int(importance * 10)  # normalize to 1-10
        else:
            # existing inline logic unchanged
            ...

    async def recall_similar(self, query, ...):
        if self._recall_strategy:
            embedding = await self._embedding_provider.embed(query)
            return await self._recall_strategy.search(
                query, embedding, self._backend, namespace_filter, top_k
            )
        else:
            # existing direct backend call unchanged
            ...
```

### Factory Method
```python
@classmethod
def create_redis_vector(
    cls,
    redis_url: str,
    index_name: str = "episodes",
    embedding_dim: int = 384,
    namespace: MemoryNamespace | None = None,
    recall_strategy: RecallStrategy | None = None,
    importance_scorer: ImportanceScorer | None = None,
    **kwargs,
) -> "EpisodicMemoryStore":
    from parrot.memory.episodic.backends.redis_vector import RedisVectorBackend
    backend = RedisVectorBackend(redis_url=redis_url, index_name=index_name, embedding_dim=embedding_dim)
    return cls(backend=backend, importance_scorer=importance_scorer, recall_strategy=recall_strategy, **kwargs)
```

### Key Constraints
- Default behavior (no scorer/strategy) MUST be identical to pre-change behavior
- Factory methods lazy-import backend classes
- No changes to method signatures beyond adding optional parameters

### References in Codebase
- `parrot/memory/episodic/store.py` — current implementation to modify
- `parrot/memory/episodic/scoring.py` — ImportanceScorer (TASK-510)
- `parrot/memory/episodic/recall.py` — RecallStrategy (TASK-511)
- `parrot/memory/episodic/backends/redis_vector.py` — RedisVectorBackend (TASK-512)

---

## Acceptance Criteria

- [ ] `EpisodicMemoryStore` accepts optional `importance_scorer` and `recall_strategy`
- [ ] When scorer is injected, `record_episode()` uses it for importance
- [ ] When strategy is injected, `recall_similar()` delegates to it
- [ ] Default behavior (None for both) is unchanged
- [ ] `create_redis_vector()` factory method works
- [ ] All existing tests still pass (no regressions)
- [ ] All tests pass: `pytest tests/unit/memory/episodic/test_store_integration.py -v`

---

## Test Specification

```python
# tests/unit/memory/episodic/test_store_integration.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot.memory.episodic.store import EpisodicMemoryStore
from parrot.memory.episodic.scoring import HeuristicScorer, ValueScorer
from parrot.memory.episodic.recall import SemanticOnlyStrategy


@pytest.fixture
def mock_backend():
    backend = AsyncMock()
    backend.store = AsyncMock(return_value="ep-123")
    backend.search_similar = AsyncMock(return_value=[])
    return backend


@pytest.fixture
def mock_embedding():
    provider = AsyncMock()
    provider.embed = AsyncMock(return_value=[0.1] * 384)
    provider.get_searchable_text = MagicMock(return_value="test text")
    return provider


class TestScorerIntegration:
    async def test_custom_scorer_used(self, mock_backend, mock_embedding):
        scorer = MagicMock()
        scorer.score = MagicMock(return_value=0.8)
        store = EpisodicMemoryStore(
            backend=mock_backend,
            embedding_provider=mock_embedding,
            importance_scorer=scorer,
        )
        # record_episode should call scorer
        # (specific test depends on store's record_episode signature)

    async def test_default_scorer_unchanged(self, mock_backend, mock_embedding):
        store = EpisodicMemoryStore(
            backend=mock_backend,
            embedding_provider=mock_embedding,
        )
        # Should work without scorer (existing behavior)


class TestStrategyIntegration:
    async def test_custom_strategy_used(self, mock_backend, mock_embedding):
        strategy = AsyncMock()
        strategy.search = AsyncMock(return_value=[])
        store = EpisodicMemoryStore(
            backend=mock_backend,
            embedding_provider=mock_embedding,
            recall_strategy=strategy,
        )
        await store.recall_similar("test query", agent_id="test")
        strategy.search.assert_called_once()

    async def test_default_uses_backend_directly(self, mock_backend, mock_embedding):
        store = EpisodicMemoryStore(
            backend=mock_backend,
            embedding_provider=mock_embedding,
        )
        await store.recall_similar("test query", agent_id="test")
        mock_backend.search_similar.assert_called_once()
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-515-store-integration.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker
**Date**: 2026-04-02
**Notes**: All 13 tests pass. importance_scorer and recall_strategy injected into __init__. Default behavior unchanged. create_redis_vector() factory added. create_pgvector() updated.

**Deviations from spec**: none
