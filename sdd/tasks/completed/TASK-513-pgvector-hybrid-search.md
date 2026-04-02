# TASK-513: PgVector Hybrid Search Enhancement

**Feature**: refactor-episodic-agentcorememory
**Spec**: `sdd/specs/refactor-episodic-agentcorememory.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-511
**Assigned-to**: unassigned

---

## Context

Module 4 from the spec. Enhances the existing PgVector backend with tsvector-based full-text search to support hybrid BM25+vector retrieval at the database level. This complements the in-memory BM25 approach from TASK-511 by enabling PostgreSQL-native hybrid search for production deployments.

---

## Scope

- Add `searchable_text` tsvector column to the episodes table schema
- Add GIN index on the tsvector column
- Implement `search_hybrid()` method that combines `ts_rank()` with cosine distance
- Add migration helper `_add_tsvector_column()` for existing tables (ALTER TABLE + backfill)
- Auto-populate tsvector on `store()` using `to_tsvector('english', situation || ' ' || action_taken || ' ' || COALESCE(lesson_learned, ''))`
- Write unit tests

**NOT in scope**: Changing the `AbstractEpisodeBackend` protocol (search_hybrid is an additional method, not a protocol requirement). Wiring into RecallStrategy (TASK-515 handles that).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/memory/episodic/backends/pgvector.py` | MODIFY | Add tsvector column, GIN index, search_hybrid(), migration helper |
| `tests/unit/memory/episodic/backends/test_pgvector_hybrid.py` | CREATE | Unit tests for hybrid search |

---

## Implementation Notes

### Hybrid Query Pattern
```sql
SELECT *, 
    (0.6 * (1 - (embedding <=> $1::vector))) + 
    (0.4 * ts_rank(searchable_text, plainto_tsquery('english', $2))) 
    AS hybrid_score
FROM episodic_memories
WHERE tenant_id = $3 AND agent_id = $4
ORDER BY hybrid_score DESC
LIMIT $5;
```

### Schema Changes
```sql
ALTER TABLE episodic_memories 
    ADD COLUMN IF NOT EXISTS searchable_text tsvector;

CREATE INDEX IF NOT EXISTS idx_episodes_searchable_text 
    ON episodic_memories USING GIN(searchable_text);

-- Backfill existing rows
UPDATE episodic_memories 
SET searchable_text = to_tsvector('english', 
    situation || ' ' || action_taken || ' ' || COALESCE(lesson_learned, ''));
```

### Key Constraints
- Migration helper must be idempotent (IF NOT EXISTS)
- `configure()` should call migration helper automatically
- tsvector populated in `store()` method — add to INSERT query
- `search_hybrid()` is a new public method, not replacing `search_similar()`
- Weight parameters (semantic_weight, text_weight) should be method arguments with defaults

### References in Codebase
- `parrot/memory/episodic/backends/pgvector.py` — existing implementation to modify
- `parrot/memory/episodic/embedding.py` — `get_searchable_text()` method for text concatenation pattern

---

## Acceptance Criteria

- [ ] tsvector column added to table schema in `configure()`
- [ ] GIN index created on tsvector column
- [ ] `store()` populates tsvector automatically
- [ ] `search_hybrid()` method combines ts_rank + cosine with configurable weights
- [ ] Migration helper works idempotently on existing tables
- [ ] All tests pass: `pytest tests/unit/memory/episodic/backends/test_pgvector_hybrid.py -v`
- [ ] Existing `search_similar()` behavior unchanged

---

## Test Specification

```python
# tests/unit/memory/episodic/backends/test_pgvector_hybrid.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot.memory.episodic.backends.pgvector import PgVectorBackend


@pytest.fixture
def mock_pool():
    pool = AsyncMock()
    pool.acquire = AsyncMock()
    return pool


@pytest.fixture
def backend(mock_pool):
    b = PgVectorBackend.__new__(PgVectorBackend)
    b._pool = mock_pool
    b._configured = True
    b.logger = MagicMock()
    return b


class TestPgVectorHybridSearch:
    async def test_search_hybrid_returns_results(self, backend, mock_pool):
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[])
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock()
        results = await backend.search_hybrid(
            embedding=[0.1] * 384,
            query_text="weather forecast",
            namespace_filter={"agent_id": "test"},
            top_k=5,
        )
        assert isinstance(results, list)

    async def test_search_hybrid_weight_params(self, backend, mock_pool):
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[])
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock()
        # Custom weights should be accepted
        await backend.search_hybrid(
            embedding=[0.1] * 384,
            query_text="test",
            namespace_filter={},
            top_k=5,
            semantic_weight=0.7,
            text_weight=0.3,
        )
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-513-pgvector-hybrid-search.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker
**Date**: 2026-04-02
**Notes**: All 8 unit tests pass. Added tsvector column + GIN index + backfill in _add_tsvector_column(). search_hybrid() with configurable weights. store() auto-populates searchable_text. Idempotent migration.

**Deviations from spec**: none
