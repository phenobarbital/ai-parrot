"""Redis-backed knowledge base primitives."""

from __future__ import annotations
import json
from typing import Any, Dict, List, Optional, Tuple, Callable, Union
from duckdb import identifier
from navconfig.logging import logging
from datamodel.parsers.json import json_encoder, json_decoder  # pylint: disable=E0611 # noqa
from redis.asyncio import Redis
from .abstract import AbstractKnowledgeBase
from ...conf import REDIS_HISTORY_URL


class RedisKnowledgeBase(AbstractKnowledgeBase):
    """
    Generic Redis-based Knowledge Base with CRUD operations.

    Supports both hash storage (HSET/HGET) and simple key-value storage (SET/GET).
    Provides flexible search, filtering, and data management capabilities.
    """

    def __init__(
        self,
        *,
        name: str,
        category: str,
        namespace: str,
        redis_url: str | None = None,
        decode_responses: bool = True,
        encoding: str = "utf-8",
        ttl: Optional[int] = None,
        use_hash_storage: bool = True,
        activation_patterns: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> None:
        """Configure the Redis connection and base KB metadata.

        Args:
            name: Name of the knowledge base
            category: Category identifier
            namespace: Prefix for Redis keys (e.g., 'user_prefs', 'bot_settings')
            activation_patterns: Patterns that activate this KB
            redis_url: Redis connection URL
            use_hash_storage: Use Redis hashes vs simple key-value
            ttl: Default TTL in seconds for keys (None = no expiration)
            **kwargs: Additional arguments passed to parent
        """

        super().__init__(
            name=name,
            category=category,
            activation_patterns=activation_patterns or [],
            **kwargs
        )
        self.namespace = namespace
        self.redis_url = redis_url or REDIS_HISTORY_URL
        self.use_hash_storage = use_hash_storage
        self.default_ttl = ttl
        self.redis = Redis.from_url(
            self.redis_url,
            decode_responses=decode_responses,
            encoding=encoding,
            socket_connect_timeout=5,
            socket_timeout=5,
            retry_on_timeout=True,
        )
        self.logger = logging.getLogger(__name__)

    async def should_activate(self, query: str, context: Dict[str, Any]) -> Tuple[bool, float]:
        """Default activation strategy based on configured patterns."""

        if self.always_active:
            return True, 1.0

        query_lower = (query or "").lower()
        return next(
            (
                (True, 0.8)
                for pattern in self.activation_patterns
                if pattern in query_lower
            ),
            (False, 0.0),
        )

    def _data_matches(
        self,
        data,
        query: str,
        identifier: str,
        field_filter: Optional[List[str]] = None,
        match_fn: Optional[Callable] = None
    ) -> Optional[Dict[str, Any]]:
        """Check if data matches the query."""
        if data and self._matches_query(data, query, field_filter, match_fn):
            return {
                'identifier': identifier,
                'data': data,
                'relevance': self._calculate_relevance(data, query)
            }
        return None

    async def search(
        self,
        query: str,
        *,
        identifier: Optional[str] = None,
        field_filter: Optional[List[str]] = None,
        match_fn: Optional[Callable] = None,
        limit: int = 100,
        **kwargs: Any,
    ) -> List[Dict[str, Any]]:
        """
        Search for entries matching the query.

        Args:
            query: Search query string
            identifier: Specific identifier to search in (optional)
            field_filter: Only search in these fields
            match_fn: Custom matching function(data, query) -> bool
            limit: Maximum results to return
            **kwargs: Additional filters

        Returns:
            List of matching entries with metadata
        """
        query_lower = (query or "").lower()
        results = []

        if identifier:
            # Search in specific identifier
            data = await self.get(identifier, **kwargs)
            if rst := self._data_matches(data, query_lower, identifier, field_filter, match_fn):
                results.append(rst)
        else:
            # Search across all keys with pattern
            pattern = self._get_key('*', *list(kwargs.values()))
            cursor = 0

            while True:
                cursor, keys = await self.redis.scan(
                    cursor,
                    match=pattern,
                    count=100
                )

                for key in keys:
                    if len(results) >= limit:
                        break

                    # Extract identifier from key
                    key_parts = key.split(':')
                    if len(key_parts) >= 2:
                        key_identifier = key_parts[1]

                        data = await self.get(key_identifier, **kwargs)
                        if rst := self._data_matches(data, query_lower, key_identifier, field_filter, match_fn):
                            results.append(rst)

                if cursor == 0 or len(results) >= limit:
                    break

        # Sort by relevance
        results.sort(key=lambda x: x['relevance'], reverse=True)
        return results[:limit]

    def _matches_query(
        self,
        data: Any,
        query: str,
        field_filter: Optional[List[str]] = None,
        match_fn: Optional[Callable] = None
    ) -> bool:
        """Check if data matches the query."""
        if match_fn:
            return match_fn(data, query)

        if isinstance(data, dict):
            fields = field_filter or data.keys()
            for field in fields:
                value = data.get(field)
                if value and query in str(value).lower():
                    return True
        elif isinstance(data, str):
            return query in data.lower()

        return False

    def _calculate_relevance(self, data: Any, query: str) -> float:
        """Calculate relevance score for search results."""
        if isinstance(data, dict):
            score = 0.0
            for value in data.values():
                if value and query in str(value).lower():
                    # Exact match gets higher score
                    score += 1.0 if query == str(value).lower() else 0.5
            return score
        elif isinstance(data, str):
            if query == data.lower():
                return 1.0
            elif query in data.lower():
                return 0.5
        return 0.0

    async def list_all(
        self,
        pattern: Optional[str] = None,
        limit: int = 1000
    ) -> List[Dict[str, Any]]:
        """
        List all entries matching a pattern.

        Args:
            pattern: Key pattern (uses wildcard if None)
            limit: Maximum results

        Returns:
            List of all matching entries
        """
        results = []
        search_pattern = pattern or f"{self.namespace}:*"
        cursor = 0

        while True:
            cursor, keys = await self.redis.scan(
                cursor,
                match=search_pattern,
                count=100
            )

            for key in keys:
                if len(results) >= limit:
                    break

                # Extract identifier
                key_parts = key.split(':')
                if len(key_parts) >= 2:
                    identifier = key_parts[1]
                    data = await self.get(identifier)
                    if data:
                        results.append({
                            'identifier': identifier,
                            'key': key,
                            'data': data
                        })

            if cursor == 0 or len(results) >= limit:
                break

        return results

    async def count(self, pattern: Optional[str] = None) -> int:
        """
        Count entries matching a pattern.

        Args:
            pattern: Key pattern (uses wildcard if None)

        Returns:
            Number of matching keys
        """
        search_pattern = pattern or f"{self.namespace}:*"
        count = 0
        cursor = 0

        while True:
            cursor, keys = await self.redis.scan(
                cursor,
                match=search_pattern,
                count=1000
            )
            count += len(keys)

            if cursor == 0:
                break

        return count

    def _get_key(self, identifier: str, *args) -> str:
        """
        Generate Redis key with namespace.

        Args:
            identifier: Primary identifier (e.g., user_id, chatbot_id)
            *args: Additional key components

        Returns:
            Formatted Redis key
        """
        parts = [self.namespace, identifier]
        parts.extend(str(arg) for arg in args)
        return ":".join(parts)

    def _serialize_data(self, data: Any) -> str:
        """Serialize data to JSON string."""
        try:
            return json_encoder(data)
        except Exception:
            try:
                return json.dumps(data, ensure_ascii=False, separators=(',', ':'), default=str)
            except Exception:
                return str(data)

    def _deserialize_data(self, data: str) -> Any:
        """Deserialize JSON string to Python object."""
        try:
            return json_decoder(data)
        except Exception:
            try:
                return json.loads(data)
            except Exception:
                return data

    # ========== Utility Methods ==========

    async def clear_all(self, pattern: Optional[str] = None) -> int:
        """
        Delete all entries matching a pattern.

        Args:
            pattern: Key pattern (uses prefix if None)

        Returns:
            Number of keys deleted
        """
        search_pattern = pattern or f"{self.namespace}:*"
        deleted = 0
        cursor = 0

        while True:
            cursor, keys = await self.redis.scan(
                cursor,
                match=search_pattern,
                count=100
            )

            if keys:
                deleted += await self.redis.delete(*keys)

            if cursor == 0:
                break

        return deleted

    async def set_ttl(self, identifier: str, ttl: int, **kwargs) -> bool:
        """
        Set TTL for a key.

        Args:
            identifier: Primary identifier
            ttl: TTL in seconds
            **kwargs: Additional key components

        Returns:
            True if successful
        """
        key = self._get_key(identifier, *kwargs.values())
        try:
            return await self.redis.expire(key, ttl) > 0
        except Exception:
            return False

    async def get_ttl(self, identifier: str, **kwargs) -> Optional[int]:
        """
        Get remaining TTL for a key.

        Args:
            identifier: Primary identifier
            **kwargs: Additional key components

        Returns:
            TTL in seconds or None
        """
        key = self._get_key(identifier, *kwargs.values())
        try:
            ttl = await self.redis.ttl(key)
            return ttl if ttl > 0 else None
        except Exception as e:
            self.logger.error(
                f"Error getting TTL for {key}: {e}"
            )
            return None

    async def ping(self) -> bool:
        """Test Redis connection."""
        try:
            await self.redis.ping()
            return True
        except Exception as e:
            self.logger.error(
                f"Redis ping failed: {e}"
            )
            return False

    async def close(self):
        """Close Redis connection."""
        try:
            await self.redis.close()
        except Exception as e:
            self.logger.error(
                f"Error closing Redis connection: {e}"
            )

    # ========== CRUD Operations ==========

    async def insert(
        self,
        identifier: str,
        data: Union[Dict[str, Any], str, Any],
        field: Optional[str] = None,
        ttl: Optional[int] = None,
        **kwargs
    ) -> bool:
        """
        Insert or update data in Redis.

        Args:
            identifier: Primary identifier for the key
            data: Data to store (dict for hash, any for simple storage)
            field: Field name (for hash storage only)
            ttl: TTL in seconds (overrides default)
            **kwargs: Additional key components

        Returns:
            True if successful
        """
        key = self._get_key(identifier, *kwargs.values())

        try:
            if self.use_hash_storage:
                if isinstance(data, dict):
                    # Store entire dict as hash
                    serialized = {
                        k: v if isinstance(v, str) else self._serialize_data(v)
                        for k, v in data.items()
                    }
                    await self.redis.hset(key, mapping=serialized)
                elif field:
                    # Store single field in hash
                    value = data if isinstance(data, str) else self._serialize_data(data)
                    await self.redis.hset(key, field, value)
                else:
                    raise ValueError("For hash storage, provide dict or field name")
            else:
                # Simple key-value storage
                value = data if isinstance(data, str) else self._serialize_data(data)
                await self.redis.set(key, value)

            # Set TTL if specified
            if expiry := ttl or self.default_ttl:
                await self.redis.expire(key, expiry)

            return True

        except Exception as e:
            self.logger.error(f"Error inserting data to {key}: {e}")
            return False

    async def get(
        self,
        identifier: str,
        field: Optional[str] = None,
        default: Any = None,
        **kwargs
    ) -> Any:
        """
        Retrieve data from Redis.

        Args:
            identifier: Primary identifier for the key
            field: Field name (for hash storage only)
            default: Default value if not found
            **kwargs: Additional key components

        Returns:
            Retrieved data or default
        """
        key = self._get_key(identifier, *kwargs.values())

        try:
            if self.use_hash_storage:
                if field:
                    # Get single field
                    value = await self.redis.hget(key, field)
                    if value is None:
                        return default
                    return self._deserialize_data(value) if value else default
                else:
                    # Get all fields
                    data = await self.redis.hgetall(key)
                    if not data:
                        return default
                    # Deserialize values
                    return {
                        k: self._deserialize_data(v) if v else v
                        for k, v in data.items()
                    }
            else:
                # Simple key-value storage
                value = await self.redis.get(key)
                if value is None:
                    return default
                return self._deserialize_data(value) if value else default

        except Exception as e:
            self.logger.error(f"Error getting data from {key}: {e}")
            return default

    async def update(
        self,
        identifier: str,
        data: Union[Dict[str, Any], Any],
        field: Optional[str] = None,
        **kwargs
    ) -> bool:
        """
        Update existing data (alias for insert with merge capability).

        Args:
            identifier: Primary identifier
            data: Data to update
            field: Field name (for hash storage)
            **kwargs: Additional key components

        Returns:
            True if successful
        """
        return await self.insert(identifier, data, field=field, **kwargs)

    async def delete(
        self,
        identifier: str,
        field: Optional[str] = None,
        **kwargs
    ) -> bool:
        """
        Delete data from Redis.

        Args:
            identifier: Primary identifier
            field: Field name to delete (for hash storage only)
            **kwargs: Additional key components

        Returns:
            True if successful
        """
        key = self._get_key(identifier, *kwargs.values())

        try:
            if self.use_hash_storage and field:
                # Delete specific field from hash
                result = await self.redis.hdel(key, field)
            else:
                # Delete entire key
                result = await self.redis.delete(key)
            return result > 0

        except Exception as e:
            self.logger.error(f"Error deleting {key}: {e}")
            return False

    async def exists(self, identifier: str, field: Optional[str] = None, **kwargs) -> bool:
        """
        Check if key or field exists.

        Args:
            identifier: Primary identifier
            field: Field name (for hash storage)
            **kwargs: Additional key components

        Returns:
            True if exists
        """
        key = self._get_key(identifier, *kwargs.values())

        try:
            if self.use_hash_storage and field:
                return await self.redis.hexists(key, field)
            else:
                return await self.redis.exists(key) > 0
        except Exception as e:
            self.logger.error(
                f"Error checking existence of {key}: {e}"
            )
            return False

    # ========== Bulk Operations ==========

    async def bulk_insert(
        self,
        items: List[Dict[str, Any]],
        identifier_key: str = 'id',
        ttl: Optional[int] = None
    ) -> int:
        """
        Insert multiple items in bulk.

        Args:
            items: List of items to insert
            identifier_key: Key name containing the identifier
            ttl: TTL for all items

        Returns:
            Number of items successfully inserted
        """
        count = 0
        for item in items:
            identifier = item.get(identifier_key)
            if not identifier:
                continue

            if await self.insert(identifier, item, ttl=ttl):
                count += 1

        return count

    async def bulk_get(
        self,
        identifiers: List[str],
        **kwargs
    ) -> Dict[str, Any]:
        """
        Retrieve multiple items in bulk.

        Args:
            identifiers: List of identifiers
            **kwargs: Additional key components

        Returns:
            Dict mapping identifier to data
        """
        results = {}
        for identifier in identifiers:
            data = await self.get(identifier, **kwargs)
            if data is not None:
                results[identifier] = data

        return results

    async def bulk_delete(
        self,
        identifiers: List[str],
        **kwargs
    ) -> int:
        """
        Delete multiple items in bulk.

        Args:
            identifiers: List of identifiers to delete
            **kwargs: Additional key components

        Returns:
            Number of items deleted
        """
        count = 0
        for identifier in identifiers:
            if await self.delete(identifier, **kwargs):
                count += 1

        return count
