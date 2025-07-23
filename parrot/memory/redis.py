from typing import List, Dict, Any, Optional
from dataclasses import asdict
from datamodel.parsers.json import json_encoder, json_decoder  # pylint: disable=E0611 # noqa
from .abstract import ConversationMemory, ConversationSession


class RedisConversation(ConversationMemory):
    """Redis-based conversation memory (implementation example)."""

    def __init__(self, redis_client):
        self.redis = redis_client

    async def create_session(
        self,
        user_id: str, session_id: str,
        system_prompt: Optional[str] = None
    ) -> ConversationSession:
        session = ConversationSession(
            user_id=user_id,
            session_id=session_id,
            messages=[],
            system_prompt=system_prompt
        )
        await self.redis.hset(
            f"conversation:{user_id}:{session_id}",
            "data", json_encoder(asdict(session))
        )
        return session

    async def get_session(self, user_id: str, session_id: str) -> Optional[ConversationSession]:
        data = await self.redis.hget(f"conversation:{user_id}:{session_id}", "data")
        if data:
            session_data = json_decoder(data)
            return ConversationSession(**session_data)
        return None

    async def update_session(
        self,
        session: ConversationSession
    ) -> None:
        await self.redis.hset(
            f"conversation:{session.user_id}:{session.session_id}",
            "data", json_encoder(asdict(session))
        )

    async def add_message(self, user_id: str, session_id: str, message: Dict[str, Any]) -> None:
        session = await self.get_session(user_id, session_id)
        if session:
            session.messages.append(message)
            await self.update_session(session)

    async def clear_session(self, user_id: str, session_id: str) -> None:
        await self.redis.delete(f"conversation:{user_id}:{session_id}")

    async def list_sessions(self, user_id: str) -> List[str]:
        keys = await self.redis.keys(f"conversation:{user_id}:*")
        return [key.split(":")[-1] for key in keys]
