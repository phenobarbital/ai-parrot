# TASK-305 — PgVector Episode Backend

**Feature**: FEAT-045 (Episodic Memory Store v2)
**Spec**: `sdd/specs/episodicmemorystore.spec.md`
**Status**: pending
**Priority**: high
**Effort**: L
**Depends on**: TASK-304
**Parallel**: false
**Parallelism notes**: Imports EpisodicMemory, MemoryNamespace, EpisodeSearchResult from TASK-304 models.

---

## Objective

Implement the `AbstractEpisodeBackend` Protocol and the `PgVectorBackend` using asyncpg for production episodic memory storage with pgvector similarity search.

## Files to Create/Modify

- `parrot/memory/episodic/backends/abstract.py` — new file (Protocol)
- `parrot/memory/episodic/backends/pgvector.py` — new file
- `parrot/memory/episodic/backends/__init__.py` — update exports

## Implementation Details

### AbstractEpisodeBackend (Protocol)

Per spec section 3.2 — defines the interface:
- `store(episode) -> str`
- `search_similar(embedding, namespace_filter, top_k, score_threshold, include_failures_only) -> list[EpisodeSearchResult]`
- `get_recent(namespace_filter, limit, since) -> list[EpisodicMemory]`
- `get_failures(agent_id, tenant_id, limit) -> list[EpisodicMemory]`
- `delete_expired() -> int`
- `count(namespace_filter) -> int`

### PgVectorBackend

Per spec section 3.3 and brainstorm section 3.3:

```python
class PgVectorBackend:
    def __init__(
        self,
        dsn: str,
        schema: str = "parrot_memory",
        table: str = "episodic_memory",
        pool_size: int = 10,
    ) -> None: ...
```

**configure()**: Creates asyncpg connection pool, schema, table, and all indexes from spec section 2 (indexes). Uses `CREATE TABLE IF NOT EXISTS` and `CREATE INDEX IF NOT EXISTS` for idempotency.

**store()**: INSERT with `ON CONFLICT DO NOTHING` (idempotent on episode_id).

**search_similar()**: Cosine distance query with dimensional WHERE filters:
```sql
SELECT *, 1 - (embedding <=> $1::vector) AS score
FROM {schema}.{table}
WHERE tenant_id = $2 AND agent_id = $3
  AND (user_id = $4 OR $4 IS NULL)
  AND (room_id = $5 OR $5 IS NULL)
  AND ($6 = FALSE OR is_failure = TRUE)
ORDER BY embedding <=> $1::vector
LIMIT $7
```
Score threshold applied post-query.

**get_recent()**: ORDER BY created_at DESC with namespace filter and optional `since` datetime.

**get_failures()**: Uses partial index `WHERE is_failure = TRUE`.

**delete_expired()**: `DELETE FROM ... WHERE expires_at IS NOT NULL AND expires_at < NOW()`.

**count()**: `SELECT COUNT(*) FROM ... WHERE ...` with namespace filter.

### Connection Pool Lifecycle

- `async configure()` — creates pool and schema/table/indexes.
- `async close()` — closes pool.
- Supports `async with` context manager.

## Acceptance Criteria

- [ ] `configure()` creates schema, table, and all 6 indexes idempotently.
- [ ] `store()` inserts an episode and returns episode_id.
- [ ] `search_similar()` returns episodes ranked by cosine similarity with dimensional filters.
- [ ] `get_recent()` returns episodes ordered by created_at DESC.
- [ ] `get_failures()` returns only failure episodes.
- [ ] `delete_expired()` removes expired episodes and returns count.
- [ ] `count()` returns correct count for namespace filter.
- [ ] Connection pool is properly managed (create/close).
