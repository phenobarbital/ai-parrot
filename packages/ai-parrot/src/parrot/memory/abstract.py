
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime
from abc import ABC, abstractmethod
from datamodel.parsers.json import JSONContent  # pylint: disable=E0611 # noqa
from navconfig.logging import logging


@dataclass
class ConversationTurn:
    """Represents a single turn in a conversation."""
    turn_id: str
    user_id: str
    user_message: str
    assistant_response: str
    context_used: Optional[str] = None
    tools_used: List[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize turn to dictionary."""
        return {
            'turn_id': self.turn_id,
            'user_id': self.user_id,
            'user_message': self.user_message,
            'assistant_response': self.assistant_response,
            'context_used': self.context_used,
            'tools_used': self.tools_used,
            'timestamp': self.timestamp.isoformat(),
            'metadata': self.metadata
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ConversationTurn':
        """Deserialize turn from dictionary."""
        return cls(
            turn_id=data['turn_id'],
            user_id=data['user_id'],
            user_message=data['user_message'],
            assistant_response=data['assistant_response'],
            context_used=data.get('context_used'),
            tools_used=data.get('tools_used', []),
            timestamp=datetime.fromisoformat(data['timestamp']),
            metadata=data.get('metadata', {})
        )


@dataclass
class ConversationHistory:
    """Manages conversation history for a session - replaces ConversationSession."""
    session_id: str
    user_id: str
    chatbot_id: Optional[str] = None
    turns: List[ConversationTurn] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def add_turn(self, turn: ConversationTurn) -> None:
        """Add a new turn to the conversation history."""
        self.turns.append(turn)
        self.updated_at = datetime.now()

    def get_recent_turns(self, count: int = 5) -> List[ConversationTurn]:
        """Get the most recent turns for context."""
        return self.turns[-count:] if count > 0 else self.turns

    def get_messages_for_api(self, model: str = 'claude') -> List[Dict[str, Any]]:
        """Convert turns to API message format for LLM Model."""
        messages = []
        if model == 'claude':
            # Claude expects messages in a specific format
            for turn in self.turns:
                messages.append({
                    "role": "user",
                    "content": turn.user_message
                })
                messages.append({
                    "role": "assistant",
                    "content": turn.assistant_response
                })
        else:
            # Default format for other models
            # This can be adjusted based on the specific model requirements
            for turn in self.turns:
                # Add user message
                messages.append({
                    "role": "user",
                    "content": [{"type": "text", "text": turn.user_message}]
                })
                # Add assistant response
                messages.append({
                    "role": "assistant",
                    "content": [{"type": "text", "text": turn.assistant_response}]
                })
        return messages

    def clear_turns(self) -> None:
        """Clear all turns from the conversation history."""
        self.turns.clear()
        self.updated_at = datetime.now()

    def to_dict(self) -> Dict[str, Any]:
        """Serialize conversation history to dictionary."""
        return {
            'session_id': self.session_id,
            'user_id': self.user_id,
            'chatbot_id': self.chatbot_id,
            'turns': [turn.to_dict() for turn in self.turns],
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
            'metadata': self.metadata
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ConversationHistory':
        """Deserialize conversation history from dictionary."""
        history = cls(
            session_id=data['session_id'],
            user_id=data['user_id'],
            chatbot_id=data.get('chatbot_id'),
            created_at=datetime.fromisoformat(data['created_at']),
            updated_at=datetime.fromisoformat(data['updated_at']),
            metadata=data.get('metadata', {})
        )

        for turn_data in data.get('turns', []):
            turn = ConversationTurn.from_dict(turn_data)
            history.turns.append(turn)

        return history

class ConversationMemory(ABC):
    """Abstract base class for conversation memory storage."""

    def __init__(self, debug: bool = False):
        self.logger = logging.getLogger(
            f"parrot.Memory.{self.__class__.__name__}"
        )
        self._json = JSONContent()
        self.debug = debug

    @abstractmethod
    async def create_history(
        self,
        user_id: str,
        session_id: str,
        metadata: Optional[Dict[str, Any]] = None,
        chatbot_id: Optional[str] = None
    ) -> ConversationHistory:
        """Create a new conversation history."""
        pass

    @abstractmethod
    async def get_history(
        self,
        user_id: str,
        session_id: str,
        chatbot_id: Optional[str] = None
    ) -> Optional[ConversationHistory]:
        """Get a conversation history."""
        pass

    @abstractmethod
    async def update_history(self, history: ConversationHistory) -> None:
        """Update a conversation history."""
        pass

    @abstractmethod
    async def add_turn(
        self,
        user_id: str,
        session_id: str,
        turn: ConversationTurn,
        chatbot_id: Optional[str] = None
    ) -> None:
        """Add a turn to the conversation."""
        pass

    @abstractmethod
    async def clear_history(
        self,
        user_id: str,
        session_id: str,
        chatbot_id: Optional[str] = None
    ) -> None:
        """Clear a conversation history."""
        pass

    @abstractmethod
    async def list_sessions(
        self,
        user_id: str,
        chatbot_id: Optional[str] = None
    ) -> List[str]:
        """List all session IDs for a user."""
        pass

    @abstractmethod
    async def delete_history(
        self,
        user_id: str,
        session_id: str,
        chatbot_id: Optional[str] = None
    ) -> bool:
        """Delete a conversation history entirely."""
        pass
