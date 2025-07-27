from typing import Dict, List, Optional, Any
from .abstract import ConversationMemory, ConversationHistory, ConversationTurn


class InMemoryConversation(ConversationMemory):
    """In-memory implementation of conversation memory."""

    def __init__(self):
        super().__init__()
        self._histories: Dict[str, Dict[str, ConversationHistory]] = {}

    def _get_key(self, user_id: str, session_id: str) -> tuple:
        return (user_id, session_id)

    async def create_history(
        self,
        user_id: str,
        session_id: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> ConversationHistory:
        """Create a new conversation history."""
        if user_id not in self._histories:
            self._histories[user_id] = {}

        history = ConversationHistory(
            session_id=session_id,
            user_id=user_id,
            metadata=metadata or {}
        )

        self._histories[user_id][session_id] = history
        return history

    async def get_history(self, user_id: str, session_id: str) -> Optional[ConversationHistory]:
        """Get a conversation history."""
        result = self._histories.get(user_id, {}).get(session_id)
        if result and self.debug:
            self.logger.debug(f"DEBUG: History has {len(result.turns)} turns")
        return result

    async def update_history(self, history: ConversationHistory) -> None:
        """Update a conversation history."""
        if history.user_id not in self._histories:
            self._histories[history.user_id] = {}
        self._histories[history.user_id][history.session_id] = history

    async def add_turn(self, user_id: str, session_id: str, turn: ConversationTurn) -> None:
        """Add a turn to the conversation."""
        history = await self.get_history(user_id, session_id)
        if history:
            history.add_turn(turn)

    async def clear_history(self, user_id: str, session_id: str) -> None:
        """Clear a conversation history."""
        history = await self.get_history(user_id, session_id)
        if history:
            history.clear_turns()

    async def list_sessions(self, user_id: str) -> List[str]:
        """List all session IDs for a user."""
        return list(self._histories.get(user_id, {}).keys())

    async def delete_history(self, user_id: str, session_id: str) -> bool:
        """Delete a conversation history entirely."""
        if user_id in self._histories and session_id in self._histories[user_id]:
            del self._histories[user_id][session_id]
            return True
        return False
