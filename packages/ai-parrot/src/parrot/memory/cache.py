from typing import Any, Optional, Callable, TypeVar, ParamSpec
from functools import wraps
from abc import ABC
import asyncio
import hashlib
import inspect
import redis.asyncio as aioredis
from datamodel.parsers.json import json_encoder, json_decoder  # pylint: disable=E0611 # noqa
from ..conf import REDIS_URL


P = ParamSpec('P')
T = TypeVar('T')


class CacheMixin(ABC):
    """Mixin to add caching capabilities using Redis."""

    def __init__(self, redis_url: str = None, **kwargs):
        # Redis connection for caching
        self.redis = aioredis.from_url(
            redis_url or REDIS_URL,
            encoding="utf-8",
            decode_responses=True
        )
        self.default_ttl = kwargs.get('default_ttl', 3600)
        self.key_prefix = "hierarchy:"

    def _generate_cache_key(self, query_type: str, **params) -> str:
        """
        Generate a unique cache key based on the query type and parameters.
        """
        # Ordenar params para consistencia
        sorted_params = json_encoder(params)
        param_hash = hashlib.md5(sorted_params.encode()).hexdigest()
        return f"{self.key_prefix}{query_type}:{param_hash}"

    async def get(self, query_type: str, **params) -> Optional[Any]:
        """
        Get a cached value from Redis based on the query type and parameters.
        """
        key = self._generate_cache_key(query_type, **params)

        try:
            return json_decoder(cached) if (cached := await self.redis.get(key)) else None
        except Exception as e:
            print(f"Cache error (get): {e}")
            return None

    async def set(
        self,
        query_type: str,
        value: Any,
        ttl: Optional[int] = None,
        **params
    ):
        """
        Save result to cache with TTL (async).
        """
        key = self._generate_cache_key(query_type, **params)
        ttl = ttl or self.default_ttl

        try:
            await self.redis.setex(
                key,
                ttl,
                json_encoder(value)
            )
        except Exception as e:
            print(f"Cache error (set): {e}")

    async def invalidate_cache(self, object_oid: str):
        """
        Invalidate cache related to an object (async).
        """
        pattern = f"{self.key_prefix}*{object_oid}*"

        try:
            # Use scan_iter to avoid blocking
            keys = []
            async for key in self.redis.scan_iter(match=pattern):
                keys.append(key)

            if keys:
                await self.redis.delete(*keys)
                print(
                    f"Invalidated {len(keys)} keys for {object_oid}"
                )
        except Exception as e:
            print(f"Cache error (invalidate): {e}")

    async def clear_all(self):
        """Clear all hierarchy cache (async)."""
        pattern = f"{self.key_prefix}*"

        try:
            keys = []
            async for key in self.redis.scan_iter(match=pattern):
                keys.append(key)

            if keys:
                await self.redis.delete(*keys)
                print(f"Cleared {len(keys)} cache keys")
        except Exception as e:
            print(f"Cache error (clear): {e}")


def cached_query(
    query_type: str,
    ttl: Optional[int] = None
) -> Callable[[Callable[P, asyncio.Future[T]]], Callable[P, asyncio.Future[T]]]:
    """
    Decorator to cache the result of async methods in classes
    that inherit from CacheMixin.

    Usage:
    ```python
    @cached_query("get_superiors", ttl=600)
    def get_all_superiors(self, employee_oid: str):
        ...
    ```
    """

    def decorator(
        func: Callable[P, asyncio.Future[T]]
    ) -> Callable[P, asyncio.Future[T]]:
        @wraps(func)
        async def wrapper(
            self: CacheMixin,
            *args: P.args,
            **kwargs: P.kwargs
        ) -> T:

            # Build cache parameters
            sig = inspect.signature(func)
            param_names = list(sig.parameters.keys())[1:]  # Skip 'self'

            cache_params = kwargs.copy()
            for i, arg in enumerate(args):
                if i < len(param_names):
                    cache_params[param_names[i]] = arg  # ✅ Mapping arg → param name

            # Attempt to get from cache
            cached_result = await self.get(
                query_type,
                **cache_params
            )
            if cached_result is not None:
                return cached_result

            # Call the original function
            if asyncio.iscoroutinefunction(func):
                result = await func(self, *args, **kwargs)
            else:
                # executing sync method in thread pool
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(
                    None, lambda: func(self, *args, **kwargs)
                )

            # Save to cache, fire and forget:
            asyncio.create_task(
                self.set(
                    query_type,
                    result,
                    ttl,
                    **cache_params
                )
            )

            return result

        return wrapper

    return decorator
