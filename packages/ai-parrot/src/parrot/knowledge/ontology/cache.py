"""Redis cache helpers for ontology pipeline results.

Provides key building, serialization, TTL management, and pattern-based
invalidation for the full ontology RAG pipeline cache.
"""
from __future__ import annotations

import logging
from typing import Any

from .schema import EnrichedContext

logger = logging.getLogger("Parrot.Ontology.Cache")

# Default values (overridden by conf at runtime)
_DEFAULT_PREFIX = "parrot:ontology"
_DEFAULT_TTL = 86400


def _get_conf_value(name: str, default: Any) -> Any:
    """Safely get a config value from parrot.conf."""
    try:
        from parrot import conf
        val = getattr(conf, name, None)
        return val if val is not None else default
    except (ImportError, AttributeError):
        return default


class OntologyCache:
    """Redis cache for ontology pipeline results.

    Cache key format: ``{prefix}:{tenant}:{user}:{pattern}``
    Extended format (FEAT-158): ``{prefix}:{tenant}:{user}:{pattern}:e={k1}={v1},...``
    when ``resolved_entities`` is provided and non-empty.

    Args:
        redis_client: An async Redis client (aioredis or redis.asyncio).
    """

    def __init__(self, redis_client: Any = None) -> None:
        self._redis = redis_client

    @staticmethod
    def build_key(
        tenant_id: str,
        user_id: str,
        pattern: str,
        resolved_entities: dict[str, str] | None = None,
    ) -> str:
        """Build a cache key for a pipeline result.

        When ``resolved_entities`` is provided and non-empty, appends a
        deterministic suffix ``':e={k1}={v1},{k2}={v2},...'`` (sorted by key)
        to prevent cross-target cache poisoning (FEAT-158).

        Backwards compatible: omitting ``resolved_entities`` (or passing
        ``None`` or ``{}``) returns the identical key as the pre-FEAT-158
        format ``'{prefix}:{tenant_id}:{user_id}:{pattern}'``.

        Args:
            tenant_id: Tenant identifier.
            user_id: User identifier.
            pattern: Traversal pattern name.
            resolved_entities: Optional mapping of rule_name → graph _id from
                entity extraction (FEAT-158). Sorted by key for determinism.

        Returns:
            Formatted cache key string.
        """
        prefix = _get_conf_value("ONTOLOGY_CACHE_PREFIX", _DEFAULT_PREFIX)
        base = f"{prefix}:{tenant_id}:{user_id}:{pattern}"
        if not resolved_entities:
            return base
        items = ",".join(
            f"{k}={v}" for k, v in sorted(resolved_entities.items())
        )
        return f"{base}:e={items}"

    async def get(self, key: str) -> EnrichedContext | None:
        """Retrieve a cached EnrichedContext.

        Args:
            key: Cache key.

        Returns:
            EnrichedContext if found, None on cache miss or error.
        """
        if not self._redis:
            return None
        try:
            cached = await self._redis.get(key)
            if cached is None:
                return None
            if isinstance(cached, bytes):
                cached = cached.decode("utf-8")
            return EnrichedContext.from_cache(cached)
        except Exception as e:
            logger.warning("Cache get failed for key '%s': %s", key, e)
            return None

    async def set(
        self, key: str, context: EnrichedContext, ttl: int | None = None
    ) -> None:
        """Store an EnrichedContext in cache.

        Args:
            key: Cache key.
            context: EnrichedContext to cache.
            ttl: TTL in seconds. If None, uses ONTOLOGY_CACHE_TTL from conf.
        """
        if not self._redis:
            return
        if ttl is None:
            ttl = _get_conf_value("ONTOLOGY_CACHE_TTL", _DEFAULT_TTL)
        try:
            await self._redis.set(key, context.to_cache(), ex=ttl)
            logger.debug("Cached key '%s' (TTL=%ds)", key, ttl)
        except Exception as e:
            logger.warning("Cache set failed for key '%s': %s", key, e)

    async def invalidate_tenant(self, tenant_id: str) -> None:
        """Delete all cache keys for a specific tenant.

        Args:
            tenant_id: Tenant identifier.
        """
        if not self._redis:
            return
        prefix = _get_conf_value("ONTOLOGY_CACHE_PREFIX", _DEFAULT_PREFIX)
        pattern = f"{prefix}:{tenant_id}:*"
        try:
            keys = []
            async for key in self._redis.scan_iter(match=pattern):
                keys.append(key)
            if keys:
                await self._redis.delete(*keys)
                logger.info(
                    "Invalidated %d cache keys for tenant '%s'",
                    len(keys), tenant_id,
                )
        except Exception as e:
            logger.warning(
                "Cache invalidation failed for tenant '%s': %s",
                tenant_id, e,
            )

    async def invalidate_all(self) -> None:
        """Delete all ontology cache keys across all tenants."""
        if not self._redis:
            return
        prefix = _get_conf_value("ONTOLOGY_CACHE_PREFIX", _DEFAULT_PREFIX)
        pattern = f"{prefix}:*"
        try:
            keys = []
            async for key in self._redis.scan_iter(match=pattern):
                keys.append(key)
            if keys:
                await self._redis.delete(*keys)
                logger.info("Invalidated all %d ontology cache keys", len(keys))
        except Exception as e:
            logger.warning("Full cache invalidation failed: %s", e)
