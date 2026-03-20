# TASK-368: Redis Cache Helpers

**Feature**: Ontological Graph RAG
**Spec**: `sdd/specs/ontological-graph-rag.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (1h)
**Depends-on**: TASK-360
**Assigned-to**: —

---

## Context

> Redis cache helpers for full-pipeline result caching with CRON invalidation.
> Implements spec Module 16.

---

## Scope

### Create `parrot/knowledge/ontology/cache.py`

`OntologyCache`:
- `__init__(self, redis_client)` — receive Redis client.
- `build_key(tenant_id: str, user_id: str, pattern: str) -> str` — format: `{ONTOLOGY_CACHE_PREFIX}:{tenant}:{user}:{pattern}`.
- `async get(self, key: str) -> EnrichedContext | None` — deserialize cached JSON.
- `async set(self, key: str, context: EnrichedContext, ttl: int = None)` — serialize to JSON, set with TTL (default `ONTOLOGY_CACHE_TTL`).
- `async invalidate_tenant(self, tenant_id: str)` — delete all keys matching `{ONTOLOGY_CACHE_PREFIX}:{tenant}:*` (pattern-based deletion).
- `async invalidate_all(self)` — delete all ontology cache keys.

---

## Acceptance Criteria

- [ ] Cache key format: `{prefix}:{tenant}:{user}:{pattern}`.
- [ ] `get()` returns `None` on cache miss.
- [ ] `set()` uses `ONTOLOGY_CACHE_TTL` as default TTL.
- [ ] `invalidate_tenant()` deletes only that tenant's keys.
- [ ] Unit tests with mocked Redis.

---

## Files to Create / Modify

| File | Action |
|---|---|
| `parrot/knowledge/ontology/cache.py` | **Create** |
