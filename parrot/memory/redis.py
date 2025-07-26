from typing import List, Dict, Any, Optional
from dataclasses import asdict
from redis.asyncio import Redis
from datamodel.parsers.json import json_encoder, json_decoder  # pylint: disable=E0611 # noqa
from .abstract import ConversationMemory, ConversationHistory, ConversationTurn
from ..conf import REDIS_HISTORY_URL


class RedisConversation(ConversationMemory):
    """Redis-based conversation memory (implementation example)."""

    def __init__(
        self,
        redis_url: str = None,
        key_prefix: str = "conversation"
    ):
        self.redis_url = redis_url or REDIS_HISTORY_URL
        self.key_prefix = key_prefix
        self.redis = Redis.from_url(
            self.redis_url,
            decode_responses=True,
            encoding="utf-8",
            auto_close_connection_pool=True
        )

    def _get_key(self, user_id: str, session_id: str) -> str:
        """Generate Redis key for conversation history."""
        return f"{self.key_prefix}:{user_id}:{session_id}"

    def _get_user_sessions_key(self, user_id: str) -> str:
        """Generate Redis key for user's session list."""
        return f"{self.key_prefix}_sessions:{user_id}"

    async def create_history(
        self,
        user_id: str,
        session_id: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> ConversationHistory:
        """Create a new conversation history."""
        history = ConversationHistory(
            session_id=session_id,
            user_id=user_id,
            metadata=metadata or {}
        )
        key = self._get_key(user_id, session_id)
        await self.redis.set(key, json_encoder(history.to_dict()))
        await self.redis.sadd(
            self._get_user_sessions_key(user_id), session_id
        )
        return history

    async def get_history(self, user_id: str, session_id: str) -> Optional[ConversationHistory]:
        """Get a conversation history."""
        key = self._get_key(user_id, session_id)
        data = await self.redis.get(key)
        if data:
            return ConversationHistory.from_dict(json_decoder(data))
        return None

    async def update_history(self, history: ConversationHistory) -> None:
        """Update a conversation history."""
        key = self._get_key(history.user_id, history.session_id)
        await self.redis.set(key, json_encoder(history.to_dict()))

    async def add_message(self, user_id: str, session_id: str, message: Dict[str, Any]) -> None:
        history = await self.get_history(user_id, session_id)
        if history:
            history.messages.append(message)
            await self.update_history(history)

    async def add_turn(self, user_id: str, session_id: str, turn: ConversationTurn) -> None:
        """Add a turn to the conversation."""
        history = await self.get_history(user_id, session_id)
        if history:
            history.add_turn(turn)
            await self.update_history(history)

    async def clear_history(self, user_id: str, session_id: str) -> None:
        """Clear a conversation history."""
        history = await self.get_history(user_id, session_id)
        if history:
            history.clear_turns()
            await self.update_history(history)

    async def list_sessions(self, user_id: str) -> List[str]:
        """List all session IDs for a user."""
        sessions = await self.redis.smembers(self._get_user_sessions_key(user_id))
        return [s.decode() for s in sessions]

    async def delete_history(self, user_id: str, session_id: str) -> bool:
        """Delete a conversation history entirely."""
        key = self._get_key(user_id, session_id)
        result = await self.redis.delete(key)
        await self.redis.srem(self._get_user_sessions_key(user_id), session_id)
        return result > 0
