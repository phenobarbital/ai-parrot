"""
Redis-based caching for Tool and Toolkit API responses.

Provides a lightweight cache layer that can be composed into any tool
or toolkit to avoid redundant API calls within a configurable TTL.
"""
import hashlib
from typing import Any, Optional

import redis.asyncio as aioredis
from datamodel.parsers.json import json_encoder, json_decoder  # pylint: disable=E0611 # noqa
from navconfig.logging import logging

from ..conf import REDIS_URL

# Default TTL for tool cache entries (5 minutes).
DEFAULT_TOOL_CACHE_TTL = 300


class ToolCache:
    """Redis-backed cache for tool/toolkit API responses.

    Generates deterministic cache keys from tool name, method, and
    call parameters so that identical queries are served from Redis
    instead of hitting external APIs.

    Attributes:
        prefix: Key prefix used in Redis to namespace tool cache entries.
        ttl: Default time-to-live in seconds for cached values.
    """

    def __init__(
        self,
        prefix: str = "tool_cache",
        ttl: int = DEFAULT_TOOL_CACHE_TTL,
        redis_url: Optional[str] = None,
    ):
        self.prefix = prefix
        self.ttl = ttl
        self.logger = logging.getLogger("ToolCache")
        self._redis: Optional[aioredis.Redis] = None
        self._redis_url = redis_url or REDIS_URL

    async def _get_redis(self) -> aioredis.Redis:
        """Lazy-initialise the async Redis connection."""
        if self._redis is None:
            self._redis = aioredis.from_url(
                self._redis_url,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
                retry_on_timeout=True,
            )
        return self._redis

    def _build_key(self, tool_name: str, method: str, **params) -> str:
        """Build a deterministic Redis key from tool, method and params.

        Args:
            tool_name: Identifier of the tool (e.g. ``fred_api``).
            method: Logical method or endpoint name.
            **params: Query parameters (API keys are excluded by caller).

        Returns:
            A namespaced Redis key string.
        """
        sorted_params = json_encoder(
            {k: v for k, v in sorted(params.items()) if v is not None}
        )
        param_hash = hashlib.md5(sorted_params.encode()).hexdigest()
        return f"{self.prefix}:{tool_name}:{method}:{param_hash}"

    async def get(
        self, tool_name: str, method: str, **params
    ) -> Optional[Any]:
        """Retrieve a cached value if it exists and has not expired.

        Args:
            tool_name: Identifier of the tool.
            method: Logical method or endpoint name.
            **params: Query parameters used to build the cache key.

        Returns:
            The cached Python object, or ``None`` on cache miss.
        """
        try:
            r = await self._get_redis()
            key = self._build_key(tool_name, method, **params)
            cached = await r.get(key)
            if cached is not None:
                self.logger.debug("Cache HIT: %s", key)
                return json_decoder(cached)
            self.logger.debug("Cache MISS: %s", key)
            return None
        except Exception as e:
            self.logger.warning("ToolCache get error: %s", e)
            return None

    async def set(
        self,
        tool_name: str,
        method: str,
        value: Any,
        ttl: Optional[int] = None,
        **params,
    ) -> None:
        """Store a value in the cache with a TTL.

        Args:
            tool_name: Identifier of the tool.
            method: Logical method or endpoint name.
            value: The value to cache (must be JSON-serialisable).
            ttl: Override TTL in seconds; defaults to instance TTL.
            **params: Query parameters used to build the cache key.
        """
        try:
            r = await self._get_redis()
            key = self._build_key(tool_name, method, **params)
            await r.setex(key, ttl or self.ttl, json_encoder(value))
            self.logger.debug("Cache SET: %s (ttl=%s)", key, ttl or self.ttl)
        except Exception as e:
            self.logger.warning("ToolCache set error: %s", e)

    async def close(self) -> None:
        """Close the underlying Redis connection."""
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None
