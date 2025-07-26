from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime


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
    """Manages conversation history for a session."""
    session_id: str
    user_id: Optional[str] = None
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

    def to_dict(self) -> Dict[str, Any]:
        """Serialize conversation history to dictionary."""
        return {
            'session_id': self.session_id,
            'user_id': self.user_id,
            'turns': [
                {
                    'turn_id': turn.turn_id,
                    'user_message': turn.user_message,
                    'assistant_response': turn.assistant_response,
                    'context_used': turn.context_used,
                    'tools_used': turn.tools_used,
                    'timestamp': turn.timestamp.isoformat(),
                    'metadata': turn.metadata
                }
                for turn in self.turns
            ],
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
            'metadata': self.metadata
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ConversationHistory':
        """Deserialize conversation history from dictionary."""
        history = cls(
            session_id=data['session_id'],
            user_id=data.get('user_id'),
            created_at=datetime.fromisoformat(data['created_at']),
            updated_at=datetime.fromisoformat(data['updated_at']),
            metadata=data.get('metadata', {})
        )

        for turn_data in data.get('turns', []):
            turn = ConversationTurn(
                turn_id=turn_data['turn_id'],
                user_message=turn_data['user_message'],
                assistant_response=turn_data['assistant_response'],
                context_used=turn_data.get('context_used'),
                tools_used=turn_data.get('tools_used', []),
                timestamp=datetime.fromisoformat(turn_data['timestamp']),
                metadata=turn_data.get('metadata', {})
            )
            history.turns.append(turn)

        return history
