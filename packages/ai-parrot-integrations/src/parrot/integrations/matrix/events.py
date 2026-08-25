"""Custom Matrix event types for AI-Parrot (m.parrot.* namespace).

These events extend the Matrix protocol to support agent-to-agent
communication, task lifecycle, and streaming within Matrix rooms.
"""

import importlib.util
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

try:
    from mautrix.types import EventType, SerializableAttrs

    HAS_MAUTRIX = True
except ImportError:
    HAS_MAUTRIX = False


# ---------------------------------------------------------------------------
# Custom event type identifiers
# ---------------------------------------------------------------------------


class ParrotEventType:
    """Matrix event type constants for AI-Parrot."""

    # State event: agent's A2A card published in a room
    AGENT_CARD = "m.parrot.agent_card"

    # Message events
    TASK = "m.parrot.task"
    RESULT = "m.parrot.result"
    STATUS = "m.parrot.status"
    FEEDBACK = "m.parrot.feedback"

    # State events
    CHANNEL = "m.parrot.channel"
    TUNNEL = "m.parrot.tunnel"


# Register with mautrix if available
if HAS_MAUTRIX:
    AGENT_CARD_EVENT = EventType.find(
        ParrotEventType.AGENT_CARD,
        t_class=EventType.Class.STATE,
    )
    TASK_EVENT = EventType.find(
        ParrotEventType.TASK,
        t_class=EventType.Class.MESSAGE,
    )
    RESULT_EVENT = EventType.find(
        ParrotEventType.RESULT,
        t_class=EventType.Class.MESSAGE,
    )
    STATUS_EVENT = EventType.find(
        ParrotEventType.STATUS,
        t_class=EventType.Class.MESSAGE,
    )
    FEEDBACK_EVENT = EventType.find(
        ParrotEventType.FEEDBACK,
        t_class=EventType.Class.MESSAGE,
    )
    CHANNEL_EVENT = EventType.find(
        ParrotEventType.CHANNEL,
        t_class=EventType.Class.STATE,
    )
    TUNNEL_EVENT = EventType.find(
        ParrotEventType.TUNNEL,
        t_class=EventType.Class.STATE,
    )
else:
    AGENT_CARD_EVENT = None
    TASK_EVENT = None
    RESULT_EVENT = None
    STATUS_EVENT = None
    FEEDBACK_EVENT = None
    CHANNEL_EVENT = None
    TUNNEL_EVENT = None


# ---------------------------------------------------------------------------
# Pydantic content models for each event type
# ---------------------------------------------------------------------------


class AgentCardEventContent(BaseModel):
    """Content of m.parrot.agent_card state event.

    Publishes an agent's A2A card as room state so other
    agents/clients can discover it.
    """

    name: str
    description: str
    version: str = "1.0"
    skills: List[Dict[str, Any]] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    capabilities: Dict[str, Any] = Field(default_factory=dict)
    default_input_modes: List[str] = Field(default_factory=lambda: ["text/plain", "application/json"])
    default_output_modes: List[str] = Field(default_factory=lambda: ["text/plain", "application/json"])
    protocol_version: str = "0.3"
    icon_url: Optional[str] = None
    # Original A2A URL (for fallback to HTTP transport)
    a2a_url: Optional[str] = None


class TaskEventContent(BaseModel):
    """Content of m.parrot.task message event.

    Represents a task submission from a user or another agent.
    Maps to A2A Task.create().
    """

    task_id: str
    context_id: Optional[str] = None
    content: str  # The prompt / task text
    metadata: Dict[str, Any] = Field(default_factory=dict)
    # Routing hints
    target_agent: Optional[str] = None
    skill_id: Optional[str] = None
    # Swarm tunnel routing (FEAT-463)
    correlation_id: Optional[str] = None
    hops: int = Field(default=0, ge=0)
    origin_session: Optional[str] = None
    expected_schema: Optional[Dict[str, Any]] = None


class ResultEventContent(BaseModel):
    """Content of m.parrot.result message event.

    Represents a completed task result. Maps to TaskState.COMPLETED.
    """

    task_id: str
    context_id: Optional[str] = None
    content: str  # The result text
    artifacts: List[Dict[str, Any]] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    success: bool = True
    error: Optional[str] = None


class StatusEventContent(BaseModel):
    """Content of m.parrot.status message event.

    Progress updates for in-flight tasks.
    Maps to TaskState.WORKING / FAILED / INPUT_REQUIRED.
    """

    task_id: str
    state: str  # "working", "failed", "input_required", "cancelled"
    message: Optional[str] = None
    progress: Optional[float] = None  # 0.0 - 1.0
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Swarm envelope, feedback, and state-event content models (FEAT-463)
# ---------------------------------------------------------------------------


class AgentAnswer(BaseModel):
    """Fixed envelope returned by ``AgentSwarmToolkit.ask_agent``.

    Attributes:
        answer: The answer payload — free text or, when ``expected_schema``
            is supplied to ``ask_agent``, an object validated against it.
        confidence: Optional confidence score in ``[0.0, 1.0]``.
        sources: Optional list of source references cited by the answer.
        metadata: Optional free-form metadata about how the answer was produced.
    """

    answer: Any
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    sources: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def validate_against(self, schema: Optional[Dict[str, Any]]) -> None:
        """Validate ``answer`` against a JSON Schema, when one is given.

        Uses ``jsonschema`` when it is already installed; otherwise falls
        back to a minimal required-keys / type check. No dependency is
        added to satisfy this — see spec §Codebase Contract.

        Args:
            schema: A JSON Schema dict, or ``None`` to skip validation.

        Raises:
            ValueError: If ``answer`` does not satisfy ``schema``.
        """
        if not schema:
            return
        if importlib.util.find_spec("jsonschema") is not None:
            import jsonschema

            try:
                jsonschema.validate(self.answer, schema)
            except jsonschema.ValidationError as exc:
                raise ValueError(str(exc)) from exc
            return

        # Minimal fallback: type + required keys (no jsonschema dependency).
        expected_type = schema.get("type")
        if expected_type == "object":
            if not isinstance(self.answer, dict):
                raise ValueError(f"expected object, got {type(self.answer).__name__}")
            required = schema.get("required", [])
            missing = [k for k in required if k not in self.answer]
            if missing:
                raise ValueError(f"missing required keys: {missing}")
        elif expected_type == "string" and not isinstance(self.answer, str):
            raise ValueError(f"expected string, got {type(self.answer).__name__}")
        elif expected_type == "array" and not isinstance(self.answer, list):
            raise ValueError(f"expected array, got {type(self.answer).__name__}")
        elif expected_type in ("number", "integer") and not isinstance(self.answer, (int, float)):
            raise ValueError(f"expected {expected_type}, got {type(self.answer).__name__}")
        elif expected_type == "boolean" and not isinstance(self.answer, bool):
            raise ValueError(f"expected boolean, got {type(self.answer).__name__}")

    @classmethod
    def from_text(cls, text: str) -> "AgentAnswer":
        """Parse a raw LLM reply into an ``AgentAnswer``.

        If ``text`` is a JSON object with an ``"answer"`` key, it is parsed
        into the corresponding fields; otherwise the raw text is wrapped
        as-is in ``answer``.

        Args:
            text: The raw text returned by the agent.

        Returns:
            A populated ``AgentAnswer``.
        """
        stripped = text.strip()
        if stripped.startswith("{"):
            try:
                data = json.loads(stripped)
            except (json.JSONDecodeError, ValueError):
                data = None
            if isinstance(data, dict) and "answer" in data:
                return cls(**data)
        return cls(answer=text)


class FeedbackEventContent(BaseModel):
    """Content of m.parrot.feedback message event.

    Represents feedback about a previous tunnel exchange, sent from one
    agent to another.
    """

    correlation_id: str
    about_event_id: str
    from_agent: str
    to_agent: str
    rating: int = Field(..., ge=-1, le=5)
    comment: Optional[str] = None


class ChannelStateContent(BaseModel):
    """Content of m.parrot.channel state event (``state_key=""``).

    Published by ``ChannelManager`` to describe a declared channel's
    configuration as Matrix room state.
    """

    name: str
    visibility: str
    answer_policy: str
    agents: List[str]
    version: int = 1


class TunnelStateContent(BaseModel):
    """Content of m.parrot.tunnel state event (``state_key=""``).

    Published by ``TunnelRegistry`` to describe a private agent-to-agent
    tunnel room's metadata as Matrix room state.
    """

    agents: List[str]
    created_at: datetime
    ttl_minutes: int
    origin_session: Optional[str] = None
