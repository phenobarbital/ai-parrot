from typing import Dict, List, Optional, Any
from .abstract import ConversationMemory, ConversationSession


class InMemoryConversation(ConversationMemory):
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
