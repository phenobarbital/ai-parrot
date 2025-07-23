from typing import List, Dict, Any, Optional
from abc import ABC, abstractmethod
from dataclasses import dataclass


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
