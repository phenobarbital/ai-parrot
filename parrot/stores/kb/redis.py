"""Redis-backed knowledge base primitives."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from redis.asyncio import Redis

from .abstract import AbstractKnowledgeBase
from ...conf import REDIS_HISTORY_URL


class RedisKnowledgeBase(AbstractKnowledgeBase):
    """Base class for knowledge bases that persist facts in Redis."""

    def __init__(
        self,
        *,
        namespace: str,
        redis_url: str | None = None,
        decode_responses: bool = True,
        encoding: str = "utf-8",
        **kwargs: Any,
    ) -> None:
        """Configure the Redis connection and base KB metadata."""

        super().__init__(**kwargs)
        self.namespace = namespace
        self.redis_url = redis_url or REDIS_HISTORY_URL
        self.redis = Redis.from_url(
            self.redis_url,
            decode_responses=decode_responses,
            encoding=encoding,
            socket_connect_timeout=5,
            socket_timeout=5,
            retry_on_timeout=True,
        )

    async def should_activate(self, query: str, context: Dict[str, Any]) -> Tuple[bool, float]:
        """Default activation strategy based on configured patterns."""

        if self.always_active:
            return True, 1.0

        query_lower = (query or "").lower()
        for pattern in self.activation_patterns:
            if pattern in query_lower:
                return True, 0.8

        return False, 0.0

    async def save_fact(
        self,
        user_id: str,
        fact_id: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Persist a fact for a user."""

        payload = {
            "id": fact_id,
            "content": content,
            "metadata": metadata or {},
        }
        await self.redis.hset(self._key(user_id), fact_id, json.dumps(payload))

    async def delete_fact(self, user_id: str, fact_id: str) -> None:
        """Remove a stored fact."""

        await self.redis.hdel(self._key(user_id), fact_id)

    async def clear_facts(self, user_id: str) -> None:
        """Remove all stored facts for a user."""

        await self.redis.delete(self._key(user_id))

    async def get_all_facts(self, user_id: str) -> Dict[str, Dict[str, Any]]:
        """Return all stored facts without applying query filters."""

        if not user_id:
            return {}

        raw_facts = await self.redis.hgetall(self._key(user_id))
        facts: Dict[str, Dict[str, Any]] = {}
        for fact_id, payload in raw_facts.items():
            try:
                data = json.loads(payload)
            except (TypeError, json.JSONDecodeError):
                data = {"content": payload, "metadata": {}}

            data.setdefault("id", fact_id)
            data.setdefault("metadata", {})
            facts[fact_id] = data

        return facts

    async def search(
        self,
        query: str,
        *,
        user_id: str | None = None,
        limit: Optional[int] = None,
        **_: Any,
    ) -> List[Dict[str, Any]]:
        """Retrieve stored facts filtered by the query string."""

        if not user_id:
            return []

        query_lower = (query or "").lower()
        all_facts = await self.get_all_facts(user_id)

        def matches(item: Dict[str, Any]) -> bool:
            if not query_lower:
                return True

            if query_lower in (item.get("content") or "").lower():
                return True

            metadata = item.get("metadata") or {}
            return any(
                query_lower in str(value).lower()
                for value in metadata.values()
                if value is not None
            )

        results = [fact for fact in all_facts.values() if matches(fact)]

        if limit is not None:
            return results[:limit]

        return results

    def _key(self, user_id: str) -> str:
        """Compose the Redis hash key for the user."""

        return f"{self.namespace}:{user_id}"
