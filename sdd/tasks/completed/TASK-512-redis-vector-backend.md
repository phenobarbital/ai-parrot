# TASK-512: RedisVectorBackend

**Feature**: refactor-episodic-agentcorememory
**Spec**: `sdd/specs/refactor-episodic-agentcorememory.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Module 3 from the spec. Implements a new `AbstractEpisodeBackend` using Redis Stack (RediSearch + vector similarity). This provides a vector-search-capable hot storage tier alongside the existing `EpisodeRedisCache` (which remains separate per the open questions resolution — cache is for recent-episode lookups, this backend is for full vector search).

---

## Scope

- Implement `RedisVectorBackend` class implementing `AbstractEpisodeBackend` protocol:
  - `configure()`: Create RediSearch index (FT.CREATE) with HNSW vector field + tag fields for namespace filtering
  - `store(episode)`: Store as Redis HASH with embedding as BLOB, metadata as tag fields
  - `search_similar(embedding, namespace_filter, top_k, score_threshold, include_failures_only)`: FT.SEARCH with KNN vector query + tag pre-filtering
  - `get_recent(namespace_filter, limit, since)`: FT.SEARCH sorted by created_at
  - `get_failures(agent_id, tenant_id, limit)`: FT.SEARCH with is_failure=true filter
  - `delete_expired()`: Scan and delete episodes past expires_at
  - `count(namespace_filter)`: FT.SEARCH COUNT
  - `cleanup()`: Close Redis connection pool
- Graceful degradation: all methods return empty/0 on connection failure (log warning)
- Write unit tests with mocked Redis

**NOT in scope**: Unifying with `EpisodeRedisCache`. Wiring into store factory (TASK-515).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/memory/episodic/backends/redis_vector.py` | CREATE | RedisVectorBackend implementation |
| `tests/unit/memory/episodic/backends/test_redis_vector.py` | CREATE | Unit tests with mocked Redis |
| `parrot/memory/episodic/backends/__init__.py` | MODIFY | Export RedisVectorBackend |

---

## Implementation Notes

### Pattern to Follow
Follow the same structure as `parrot/memory/episodic/backends/faiss.py` and `pgvector.py`:
- Constructor takes connection config
- `configure()` creates index/schema
- All methods are `async def`
- Graceful error handling with logging

### RediSearch Index Schema
```
FT.CREATE idx:episodes ON HASH PREFIX 1 ep:
  SCHEMA
    embedding VECTOR HNSW 6 TYPE FLOAT32 DIM 384 DISTANCE_METRIC COSINE
    tenant_id TAG
    agent_id TAG
    user_id TAG
    session_id TAG
    room_id TAG
    crew_id TAG
    is_failure TAG
    category TAG
    importance NUMERIC SORTABLE
    created_at NUMERIC SORTABLE
    expires_at NUMERIC SORTABLE
    situation TEXT
    action_taken TEXT
    lesson_learned TEXT
```

### Key Constraints
- Use `redis.asyncio` (already in project)
- Lazy-import redis; handle `ModuleNotFoundError` gracefully
- Redis Stack is required (RediSearch module). On `configure()`, check `FT._LIST` or `MODULE LIST` and raise clear error if RediSearch not available
- Embedding stored as bytes (numpy float32 tobytes)
- All namespace filter fields are TAG type for exact match filtering
- HNSW index parameters: M=16, EF_CONSTRUCTION=200 (reasonable defaults)

### References in Codebase
- `parrot/memory/episodic/backends/faiss.py` — in-memory backend pattern
- `parrot/memory/episodic/backends/pgvector.py` — production backend pattern
- `parrot/memory/episodic/backends/base.py` — `AbstractEpisodeBackend` protocol
- `parrot/memory/episodic/cache.py` — existing Redis usage pattern (connection handling)

---

## Acceptance Criteria

- [ ] `RedisVectorBackend` implements all `AbstractEpisodeBackend` protocol methods
- [ ] RediSearch index created with HNSW vector field + tag fields
- [ ] Vector search uses KNN with namespace pre-filtering
- [ ] Graceful degradation on Redis connection failure (returns empty, logs warning)
- [ ] Missing RediSearch module detected at `configure()` with clear error message
- [ ] All tests pass: `pytest tests/unit/memory/episodic/backends/test_redis_vector.py -v`
- [ ] Imports work: `from parrot.memory.episodic.backends.redis_vector import RedisVectorBackend`

---

## Test Specification

```python
# tests/unit/memory/episodic/backends/test_redis_vector.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.memory.episodic.backends.redis_vector import RedisVectorBackend
from parrot.memory.episodic.models import EpisodicMemory, EpisodeOutcome, MemoryNamespace


@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.ft = MagicMock()
    redis.ft.return_value.search = AsyncMock()
    redis.ft.return_value.create_index = AsyncMock()
    return redis


@pytest.fixture
def backend(mock_redis):
    b = RedisVectorBackend(redis_url="redis://localhost:6379")
    b._redis = mock_redis
    return b


@pytest.fixture
def sample_episode():
    return EpisodicMemory(
        agent_id="test-agent",
        situation="User asked about weather",
        action_taken="Called weather API",
        outcome=EpisodeOutcome.SUCCESS,
        category="TOOL_EXECUTION",
        embedding=[0.1] * 384,
    )


class TestRedisVectorBackend:
    async def test_store_episode(self, backend, sample_episode):
        episode_id = await backend.store(sample_episode)
        assert episode_id == sample_episode.episode_id

    async def test_search_similar(self, backend):
        results = await backend.search_similar(
            embedding=[0.1] * 384,
            namespace_filter={"agent_id": "test-agent"},
            top_k=5,
        )
        assert isinstance(results, list)

    async def test_graceful_degradation(self, backend, sample_episode):
        backend._redis.hset = AsyncMock(side_effect=ConnectionError("Redis down"))
        # Should not raise, should return gracefully
        result = await backend.store(sample_episode)
        assert result is None or isinstance(result, str)

    async def test_namespace_filtering(self, backend):
        ns = MemoryNamespace(agent_id="agent-1", tenant_id="t1")
        results = await backend.search_similar(
            embedding=[0.1] * 384,
            namespace_filter=ns.build_filter(),
            top_k=5,
        )
        assert isinstance(results, list)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-512-redis-vector-backend.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker
**Date**: 2026-04-02
**Notes**: All 21 unit tests pass. Implements all AbstractEpisodeBackend protocol methods. Graceful degradation on connection failure. Clear error when RediSearch module missing.

**Deviations from spec**: none
