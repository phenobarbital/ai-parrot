"""Data models for chat persistence.

Dedicated models that capture the full interaction payload
(user input, agent output, metadata, tool calls, sources, timing).
"""

from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class MessageRole(str, Enum):
    """Role of the message sender."""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


@dataclass
class ToolCall:
    """A single tool invocation within a turn."""
    name: str
    status: str = "completed"
    output: Optional[Any] = None
    arguments: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "name": self.name,
            "status": self.status,
            "output": self.output,
            "arguments": self.arguments,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ToolCall":
        """Deserialize from dictionary."""
        return cls(
            name=data.get("name", "unknown"),
            status=data.get("status", "completed"),
            output=data.get("output"),
            arguments=data.get("arguments"),
        )


@dataclass
class Source:
    """A source/reference returned by the agent."""
    content: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {"content": self.content, "metadata": self.metadata}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Source":
        """Deserialize from dictionary."""
        return cls(
            content=data.get("content", ""),
            metadata=data.get("metadata", {}),
        )


@dataclass
class ChatMessage:
    """Represents a single chat message (one direction: user OR assistant).

    This is the atomic persistence unit — one document per message in
    DocumentDB and one entry per message in the Redis turn list.
    """
    message_id: str
    session_id: str
    user_id: str
    agent_id: str
    role: str  # MessageRole value
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    # Agent-response specific fields (empty for user messages)
    output: Optional[Any] = None
    output_mode: Optional[str] = None
    data: Optional[Any] = None
    code: Optional[str] = None
    model: Optional[str] = None
    provider: Optional[str] = None
    response_time_ms: Optional[int] = None
    tool_calls: List[ToolCall] = field(default_factory=list)
    sources: List[Source] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary suitable for DocumentDB storage."""
        return {
            "message_id": self.message_id,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "agent_id": self.agent_id,
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp.isoformat()
            if isinstance(self.timestamp, datetime)
            else str(self.timestamp),
            "output": _safe_serialize(self.output),
            "output_mode": self.output_mode,
            "data": _safe_serialize(self.data),
            "code": self.code,
            "model": self.model,
            "provider": self.provider,
            "response_time_ms": self.response_time_ms,
            "tool_calls": [tc.to_dict() for tc in self.tool_calls],
            "sources": [s.to_dict() for s in self.sources],
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChatMessage":
        """Deserialize from dictionary."""
        ts = data.get("timestamp")
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        elif not isinstance(ts, datetime):
            ts = datetime.now()

        return cls(
            message_id=data["message_id"],
            session_id=data["session_id"],
            user_id=data["user_id"],
            agent_id=data.get("agent_id", ""),
            role=data.get("role", MessageRole.ASSISTANT.value),
            content=data.get("content", ""),
            timestamp=ts,
            output=data.get("output"),
            output_mode=data.get("output_mode"),
            data=data.get("data"),
            code=data.get("code"),
            model=data.get("model"),
            provider=data.get("provider"),
            response_time_ms=data.get("response_time_ms"),
            tool_calls=[
                ToolCall.from_dict(tc)
                for tc in data.get("tool_calls", [])
            ],
            sources=[
                Source.from_dict(s) for s in data.get("sources", [])
            ],
            metadata=data.get("metadata", {}),
        )


@dataclass
class Conversation:
    """Conversation metadata — one document per session in DocumentDB.

    Tracks the lifecycle of a conversation session: when it started,
    when the last message was sent, token counts, title, etc.
    """
    session_id: str
    user_id: str
    agent_id: str
    title: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    message_count: int = 0
    last_user_message: Optional[str] = None
    last_assistant_message: Optional[str] = None
    model: Optional[str] = None
    provider: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary suitable for DocumentDB storage."""
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "agent_id": self.agent_id,
            "title": self.title,
            "created_at": self.created_at.isoformat()
            if isinstance(self.created_at, datetime)
            else str(self.created_at),
            "updated_at": self.updated_at.isoformat()
            if isinstance(self.updated_at, datetime)
            else str(self.updated_at),
            "message_count": self.message_count,
            "last_user_message": self.last_user_message,
            "last_assistant_message": self.last_assistant_message,
            "model": self.model,
            "provider": self.provider,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Conversation":
        """Deserialize from dictionary."""
        def _parse_dt(val: Any) -> datetime:
            if isinstance(val, datetime):
                return val
            if isinstance(val, str):
                return datetime.fromisoformat(val)
            return datetime.now()

        return cls(
            session_id=data["session_id"],
            user_id=data["user_id"],
            agent_id=data.get("agent_id", ""),
            title=data.get("title"),
            created_at=_parse_dt(data.get("created_at")),
            updated_at=_parse_dt(data.get("updated_at")),
            message_count=data.get("message_count", 0),
            last_user_message=data.get("last_user_message"),
            last_assistant_message=data.get("last_assistant_message"),
            model=data.get("model"),
            provider=data.get("provider"),
            metadata=data.get("metadata", {}),
        )


def _safe_serialize(obj: Any) -> Any:
    """Convert complex objects to serializable form."""
    if obj is None:
        return None
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    if hasattr(obj, "to_json"):
        return obj.to_json()
    try:
        # Covers primitives, lists, dicts
        return obj
    except Exception:
        return str(obj)
