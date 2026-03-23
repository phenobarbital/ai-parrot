from typing import Dict, List, Optional, Any
from .abstract import ConversationMemory, ConversationHistory, ConversationTurn


class InMemoryConversation(ConversationMemory):
    """In-memory implementation of conversation memory."""

    def __init__(self):
        super().__init__()
        self._histories: Dict[str, Dict[str, Dict[str, ConversationHistory]]] = {}

    def _get_chatbot_key(self, chatbot_id: Optional[str]) -> str:
        return str(chatbot_id) if chatbot_id else "_default"

    async def create_history(
        self,
        user_id: str,
        session_id: str,
        metadata: Optional[Dict[str, Any]] = None,
        chatbot_id: Optional[str] = None
    ) -> ConversationHistory:
        """Create a new conversation history."""
        chatbot_key = self._get_chatbot_key(chatbot_id)
        self._histories.setdefault(user_id, {})
        self._histories[user_id].setdefault(chatbot_key, {})

        history = ConversationHistory(
            session_id=session_id,
            user_id=user_id,
            chatbot_id=chatbot_id,
            metadata=metadata or {}
        )

        self._histories[user_id][chatbot_key][session_id] = history
        return history

    async def get_history(
        self,
        user_id: str,
        session_id: str,
        chatbot_id: Optional[str] = None
    ) -> Optional[ConversationHistory]:
        """Get a conversation history."""
        user_histories = self._histories.get(user_id, {})
        result: Optional[ConversationHistory] = None
        if chatbot_id is not None:
            chatbot_key = self._get_chatbot_key(chatbot_id)
            result = user_histories.get(chatbot_key, {}).get(session_id)
        else:
            for histories in user_histories.values():
                if session_id in histories:
                    result = histories[session_id]
                    break
        if result and self.debug:
            self.logger.debug(f"DEBUG: History has {len(result.turns)} turns")
        return result

    async def update_history(self, history: ConversationHistory) -> None:
        """Update a conversation history."""
        chatbot_key = self._get_chatbot_key(history.chatbot_id)
        self._histories.setdefault(history.user_id, {})
        self._histories[history.user_id].setdefault(chatbot_key, {})
        self._histories[history.user_id][chatbot_key][history.session_id] = history

    async def add_turn(
        self,
        user_id: str,
        session_id: str,
        turn: ConversationTurn,
        chatbot_id: Optional[str] = None
    ) -> None:
        """Add a turn to the conversation."""
        history = await self.get_history(user_id, session_id, chatbot_id)
        if history:
            history.add_turn(turn)

    async def clear_history(
        self,
        user_id: str,
        session_id: str,
        chatbot_id: Optional[str] = None
    ) -> None:
        """Clear a conversation history."""
        history = await self.get_history(user_id, session_id, chatbot_id)
        if history:
            history.clear_turns()

    async def list_sessions(
        self,
        user_id: str,
        chatbot_id: Optional[str] = None
    ) -> List[str]:
        """List all session IDs for a user."""
        user_histories = self._histories.get(user_id, {})
        if chatbot_id is not None:
            chatbot_key = self._get_chatbot_key(chatbot_id)
            return list(user_histories.get(chatbot_key, {}).keys())
        sessions: List[str] = []
        seen = set()
        for histories in user_histories.values():
            for session in histories.keys():
                if session not in seen:
                    seen.add(session)
                    sessions.append(session)
        return sessions

    async def delete_history(
        self,
        user_id: str,
        session_id: str,
        chatbot_id: Optional[str] = None
    ) -> bool:
        """Delete a conversation history entirely."""
        if user_id not in self._histories:
            return False

        if chatbot_id is not None:
            chatbot_key = self._get_chatbot_key(chatbot_id)
            histories = self._histories[user_id].get(chatbot_key)
            if histories and session_id in histories:
                del histories[session_id]
                return True
            return False

        removed = False
        for histories in self._histories[user_id].values():
            if session_id in histories:
                del histories[session_id]
                removed = True
                break
        return removed
