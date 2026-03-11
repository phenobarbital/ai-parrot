# TASK-306 — FAISS Episode Backend

**Feature**: FEAT-045 (Episodic Memory Store v2)
**Spec**: `sdd/specs/episodicmemorystore.spec.md`
**Status**: pending
**Priority**: high
**Effort**: M
**Depends on**: TASK-304
**Parallel**: true
**Parallelism notes**: Only imports from TASK-304 models (same as TASK-305). Does not share files with TASK-305 (pgvector). Can run in parallel with TASK-305.

---

## Objective

Implement the `FAISSBackend` for local development without PostgreSQL. Uses in-memory FAISS index + dict storage with optional disk persistence.

## Files to Create/Modify

- `parrot/memory/episodic/backends/faiss.py` — new file

## Implementation Details

### FAISSBackend

Per brainstorm section 3.4:

```python
class FAISSBackend:
    def __init__(
        self,
        dimension: int = 384,
        persistence_path: str | None = None,
        max_episodes: int = 10000,
    ) -> None: ...
```

**Storage**: `dict[str, EpisodicMemory]` keyed by episode_id + FAISS `IndexFlatIP` (inner product on normalized vectors = cosine similarity).

**configure()**: Initialize FAISS index. If `persistence_path` exists, load from:
- `{persistence_path}/episodes.faiss` — FAISS index
- `{persistence_path}/episodes.jsonl` — episode metadata (one JSON per line)

**store()**: Add embedding to FAISS index, store episode in dict. If `persistence_path` set, append to JSONL and save FAISS index periodically.

**search_similar()**: FAISS search returns top-K candidates, then apply namespace filter post-search (iterate results, filter by tenant_id/agent_id/user_id/room_id/crew_id). Apply score_threshold.

**get_recent()**: Sort all episodes by created_at DESC, apply namespace filter, return limit.

**get_failures()**: Filter episodes by is_failure=True, apply namespace filter.

**delete_expired()**: Remove from dict + rebuild FAISS index (expensive but rare).

**count()**: Filter episodes by namespace, return len.

**Persistence methods**:
- `async save()` — write FAISS index + JSONL to disk
- `async load()` — read from disk
- Auto-save on every N stores (configurable, default 100)

## Acceptance Criteria

- [ ] `store()` adds episode to FAISS index and dict.
- [ ] `search_similar()` returns episodes ranked by similarity with post-search namespace filtering.
- [ ] `get_recent()` returns episodes ordered by time with namespace filter.
- [ ] `get_failures()` returns only failure episodes.
- [ ] Persistence to disk works (save + load round-trip).
- [ ] `max_episodes` cap is enforced (oldest removed when exceeded).
- [ ] Works without FAISS installed (graceful ImportError with helpful message).
