---
id: F001
query: Q001
type: read
file: packages/parrot-formdesigner/src/parrot_formdesigner/services/cache.py
---

## FormCache — Existing Redis Pattern (300 lines)

**Key prefix**: `"parrot:form:"` + form_id
**TTL**: configurable via `ttl_seconds` (default 3600)
**Redis lib**: `redis.asyncio.Redis` (lazy import)
**Connection**: `Redis.from_url(redis_url)` with double-checked locking
**Serialization**: Pydantic `model_dump_json()` / `model_validate_json()`
**Write pattern**: `redis.setex(key, ttl_secs, json_str)`
**Two-tier**: in-memory dict + Redis; memory checked first, Redis fallback
**Async safety**: `asyncio.Lock` throughout
**Invalidation**: async callbacks via `on_invalidate()`
**Cleanup**: `close()` method for Redis connection

This is the primary pattern to follow for the partial-saves service.
The new service should share the same `redis_url` and follow identical
lazy-init and error-handling patterns.
