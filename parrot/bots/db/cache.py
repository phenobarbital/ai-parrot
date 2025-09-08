from typing import Dict, Any, List, Optional, Union
import hashlib
from redis.asyncio import Redis
from datamodel.parsers.json import json_encoder, json_decoder  # pylint: disable=E0611 # noqa
from querysource.conf import CACHE_URL


class SchemaCache:
    """Redis-based LRU cache for schema metadata."""

    def __init__(self, redis_url: str = None, key_prefix: str = "schema_cache", ttl: int = 3600):
        self.redis_url = redis_url or CACHE_URL
        self.key_prefix = key_prefix
        self.ttl = ttl  # Time to live in seconds
        self._redis = None

    async def _get_redis(self) -> Redis:
        """Get or create Redis connection."""
        if self._redis is None:
            self._redis = Redis.from_url(
                self.redis_url,
                decode_responses=True,
                encoding="utf-8",
                socket_connect_timeout=5,
                socket_timeout=5,
                retry_on_timeout=True
            )
        return self._redis

    def _make_cache_key(self, search_term: str, search_type: str = "all", limit: int = 10) -> str:
        """Create a cache key for the search parameters."""
        # Create a hash of the parameters for consistent key generation
        params = f"{search_term}:{search_type}:{limit}"
        hash_key = hashlib.md5(params.encode()).hexdigest()
        return f"{self.key_prefix}:search:{hash_key}"

    async def get(
        self,
        search_term: str,
        search_type: str = "all",
        limit: int = 10
    ) -> Optional[List[Dict[str, Any]]]:
        """Get cached search results."""
        try:
            redis = await self._get_redis()
            cache_key = self._make_cache_key(search_term, search_type, limit)
            data = await redis.get(cache_key)
            if data:
                return json_decoder(data)
        except Exception as e:
            # Log error but don't fail the operation
            print(f"Cache get error: {e}")
        return None

    async def set(
        self,
        search_term: str,
        search_type: str,
        limit: int,
        results: List[Dict[str, Any]]
    ) -> None:
        """Set cached search results with TTL."""
        try:
            redis = await self._get_redis()
            cache_key = self._make_cache_key(search_term, search_type, limit)
            data = json_encoder(results)
            await redis.setex(cache_key, self.ttl, data)
        except Exception as e:
            # Log error but don't fail the operation
            print(f"Cache set error: {e}")

    async def invalidate_all(self) -> None:
        """Invalidate all cache entries."""
        try:
            redis = await self._get_redis()
            keys = await redis.keys(f"{self.key_prefix}:*")
            if keys:
                await redis.delete(*keys)
        except Exception as e:
            print(f"Cache invalidation error: {e}")

    async def close(self) -> None:
        """Close Redis connection."""
        if self._redis:
            await self._redis.close()
