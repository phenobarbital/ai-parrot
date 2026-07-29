---
type: Wiki Entity
title: OntologyCache
id: class:parrot.knowledge.ontology.cache.OntologyCache
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Redis cache for ontology pipeline results.
---

# OntologyCache

Defined in [`parrot.knowledge.ontology.cache`](../summaries/mod:parrot.knowledge.ontology.cache.md).

```python
class OntologyCache
```

Redis cache for ontology pipeline results.

Cache key format: ``{prefix}:{tenant}:{user}:{pattern}``
Extended format (FEAT-158): ``{prefix}:{tenant}:{user}:{pattern}:e={k1}={v1},...``
when ``resolved_entities`` is provided and non-empty.

Args:
    redis_client: An async Redis client (aioredis or redis.asyncio).

## Methods

- `def build_key(tenant_id: str, user_id: str, pattern: str, resolved_entities: dict[str, str] | None=None) -> str` — Build a cache key for a pipeline result.
- `async def get(self, key: str) -> EnrichedContext | None` — Retrieve a cached EnrichedContext.
- `async def set(self, key: str, context: EnrichedContext, ttl: int | None=None) -> None` — Store an EnrichedContext in cache.
- `async def invalidate_tenant(self, tenant_id: str) -> None` — Delete all cache keys for a specific tenant.
- `async def invalidate_all(self) -> None` — Delete all ontology cache keys across all tenants.
- `async def subscribe_invalidation(self, manager: 'TenantOntologyManager') -> None` — Subscribe to ontology:invalidate:* and trigger cache + manager invalidation.
