from typing import List, Dict, Any, Optional, TypedDict
from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
from datamodel.parsers.json import json_encoder, json_decoder  # pylint: disable=E0611 # noqa


@dataclass
class ConversationSession:
    """Data structure for conversation session."""
    user_id: str
    session_id: str
    messages: List[Dict[str, Any]]
    system_prompt: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ConversationMemory(ABC):
    """Abstract base class for conversation memory storage."""

    @abstractmethod
    async def create_session(
        self, user_id: str, session_id: str,
        system_prompt: Optional[str] = None
    ) -> ConversationSession:
        """Create a new conversation session."""
        pass

    @abstractmethod
    async def get_session(self, user_id: str, session_id: str) -> Optional[ConversationSession]:
        """Get a conversation session."""
        pass

    @abstractmethod
    async def update_session(self, session: ConversationSession) -> None:
        """Update a conversation session."""
        pass

    @abstractmethod
    async def add_message(self, user_id: str, session_id: str, message: Dict[str, Any]) -> None:
        """Add a message to the conversation."""
        pass

    @abstractmethod
    async def clear_session(self, user_id: str, session_id: str) -> None:
        """Clear a conversation session."""
        pass

    @abstractmethod
    async def list_sessions(self, user_id: str) -> List[str]:
        """List all session IDs for a user."""
        pass


class InMemoryConversationMemory(ConversationMemory):
    """In-memory implementation of conversation memory."""

    def __init__(self):
        self._sessions: Dict[str, Dict[str, ConversationSession]] = {}

    def _get_key(self, user_id: str, session_id: str) -> tuple:
        return (user_id, session_id)

    async def create_session(
        self,
        user_id: str,
        session_id: str,
        system_prompt: Optional[str] = None
    ) -> ConversationSession:
        if user_id not in self._sessions:
            self._sessions[user_id] = {}

        session = ConversationSession(
            user_id=user_id,
            session_id=session_id,
            messages=[],
            system_prompt=system_prompt
        )

        self._sessions[user_id][session_id] = session
        return session

    async def get_session(self, user_id: str, session_id: str) -> Optional[ConversationSession]:
        return self._sessions.get(user_id, {}).get(session_id)

    async def update_session(self, session: ConversationSession) -> None:
        if session.user_id not in self._sessions:
            self._sessions[session.user_id] = {}
        self._sessions[session.user_id][session.session_id] = session

    async def add_message(self, user_id: str, session_id: str, message: Dict[str, Any]) -> None:
        session = await self.get_session(user_id, session_id)
        if session:
            session.messages.append(message)
            await self.update_session(session)

    async def clear_session(self, user_id: str, session_id: str) -> None:
        if user_id in self._sessions and session_id in self._sessions[user_id]:
            del self._sessions[user_id][session_id]

    async def list_sessions(self, user_id: str) -> List[str]:
        return list(self._sessions.get(user_id, {}).keys())


class RedisConversationMemory(ConversationMemory):
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
