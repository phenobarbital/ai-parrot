# TASK-308 — Redis Hot Cache for Episodes

**Feature**: FEAT-045 (Episodic Memory Store v2)
**Spec**: `sdd/specs/episodicmemorystore.spec.md`
**Status**: pending
**Priority**: medium
**Effort**: M
**Depends on**: TASK-304
**Parallel**: true
**Parallelism notes**: Only imports EpisodicMemory from TASK-304 models. No file overlap with TASK-305/306/307. Can run in parallel.

---

## Objective

Implement `EpisodeRedisCache` for caching recent episodes and failures per namespace in Redis, enabling fast access without hitting the backend.

## Files to Create/Modify

- `parrot/memory/episodic/cache.py` — new file

## Implementation Details

### EpisodeRedisCache

Per brainstorm section 9:

```python
class EpisodeRedisCache:
    def __init__(
        self,
        redis_client: Any,  # aioredis/redis.asyncio client
        default_ttl: int = 3600,  # 1 hour
        max_recent: int = 50,  # Max recent episodes per namespace
    ) -> None: ...
```

**Redis Key Structure**:
- `episodic:{tenant}:{agent}:recent` — ZSET scored by timestamp (recent episodes)
- `episodic:{tenant}:{agent}:{episode_id}` — HASH (full episode data)
- `episodic:{tenant}:{agent}:failures` — LIST (last N failure episode IDs)

**Methods**:

- `async cache_episode(namespace: MemoryNamespace, episode: EpisodicMemory) -> None`:
  1. Store episode as HASH at `episodic:{prefix}:{episode_id}`.
  2. ZADD to recent ZSET with timestamp score.
  3. If `episode.is_failure`, LPUSH to failures LIST.
  4. ZREMRANGEBYRANK to enforce max_recent cap.
  5. Set TTL on all keys.

- `async get_recent(namespace: MemoryNamespace, limit: int = 10) -> list[EpisodicMemory] | None`:
  1. ZREVRANGE from recent ZSET.
  2. HGETALL for each episode ID.
  3. Return deserialized episodes, or None if cache miss.

- `async get_failures(namespace: MemoryNamespace, limit: int = 5) -> list[EpisodicMemory] | None`:
  1. LRANGE from failures LIST.
  2. HGETALL for each episode ID.
  3. Return deserialized episodes, or None if cache miss.

- `async invalidate(namespace: MemoryNamespace) -> None`:
  1. Delete recent ZSET, failures LIST, and all episode HASHes for this namespace.

- `async get_episode(namespace: MemoryNamespace, episode_id: str) -> EpisodicMemory | None`:
  1. HGETALL from episode HASH.

**Serialization**: Use `episode.to_dict()` → JSON for HASH values. Deserialize with `EpisodicMemory.from_dict()`.

**Graceful degradation**: If Redis is unavailable, all methods return None (cache miss) and log a warning. Never raise exceptions that would break the recording flow.

## Acceptance Criteria

- [ ] `cache_episode()` stores episode in HASH + ZSET + failures LIST.
- [ ] `get_recent()` returns cached episodes ordered by timestamp.
- [ ] `get_failures()` returns cached failure episodes.
- [ ] `invalidate()` removes all cached data for a namespace.
- [ ] TTL is enforced on all keys.
- [ ] `max_recent` cap is enforced via ZREMRANGEBYRANK.
- [ ] Graceful degradation: returns None when Redis is unavailable.
