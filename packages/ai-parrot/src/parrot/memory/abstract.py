
import uuid
from typing import TYPE_CHECKING, List, Dict, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime
from abc import ABC, abstractmethod
from datamodel.parsers.json import JSONContent  # pylint: disable=E0611 # noqa
from navconfig.logging import logging

if TYPE_CHECKING:  # pragma: no cover - typing only
    # Imported lazily: ``parrot.models`` must not become a runtime dependency
    # of ``parrot.memory`` (FEAT-524 keeps this package import-cycle free).
    from parrot.models import AIMessage


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
    #: The agent that produced this turn (FEAT-524). Always set by
    #: ``AbstractBot.save_conversation_turn``; ``None`` on records written
    #: before attribution existed.
    chatbot_id: Optional[str] = None

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
            'metadata': self.metadata,
            'chatbot_id': self.chatbot_id
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
            metadata=data.get('metadata', {}),
            # Legacy records predate attribution — absent key means "unknown".
            chatbot_id=data.get('chatbot_id')
        )

    @classmethod
    def from_ai_message(
        cls,
        *,
        user_message: str,
        response: "AIMessage",
        user_id: str,
        chatbot_id: str,
        context_used: Optional[str] = None,
        turn_id: Optional[str] = None,
        assistant_text: Optional[str] = None,
    ) -> 'ConversationTurn':
        """Build a turn from the ``AIMessage`` a bot round produced.

        This is the canonical constructor used by
        ``AbstractBot.save_conversation_turn`` call sites (FEAT-524). Before
        this existed every bot entry point hand-rolled its own turn with
        slightly different metadata keys; routing through here gives every
        persisted turn one shape.

        Args:
            user_message: The user's text for this round.
            response: The final :class:`~parrot.models.responses.AIMessage`
                returned by the bot — i.e. *after* guardrails, redaction and
                formatting, not the raw client output.
            user_id: Owner of the conversation.
            chatbot_id: The agent producing the turn. Must be the bot's
                ``memory_key_id`` — attribution and storage key must agree.
            context_used: Optional retrieval context string used this round.
            turn_id: Explicit turn id. Defaults to ``response.turn_id``, then
                to a fresh uuid4.
            assistant_text: Overrides the assistant text taken from
                ``response``. Used by the streaming partial-save path, where
                the accumulated text is authoritative and the ``AIMessage`` is
                synthesized after the fact.

        Returns:
            A fully populated :class:`ConversationTurn`.
        """
        if assistant_text is not None:
            answer = assistant_text
        else:
            answer = getattr(response, "to_text", None)
            if answer is None:
                answer = str(getattr(response, "content", "") or "")

        tool_calls = getattr(response, "tool_calls", None) or []
        usage = getattr(response, "usage", None)

        return cls(
            turn_id=turn_id or getattr(response, "turn_id", None) or str(uuid.uuid4()),
            user_id=user_id,
            user_message=user_message,
            assistant_response=answer,
            context_used=context_used,
            tools_used=[tc.name for tc in tool_calls],
            metadata={
                "model": getattr(response, "model", None),
                "provider": getattr(response, "provider", None),
                "usage": usage.model_dump() if hasattr(usage, "model_dump") else usage,
                "finish_reason": getattr(response, "finish_reason", None),
                "response_time": getattr(response, "response_time", None),
            },
            chatbot_id=chatbot_id,
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

    # NOTE (FEAT-524): ``get_messages_for_api()`` was removed here. Rendering a
    # history into messages is provider-agnostic work that belongs in
    # ``parrot.memory.render.render_history()``, and mapping the result onto a
    # provider's shape belongs in ``AbstractClient._format_history()``.

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
