"""Custom Matrix event types for AI-Parrot (m.parrot.* namespace).

These events extend the Matrix protocol to support agent-to-agent
communication, task lifecycle, and streaming within Matrix rooms.
"""
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
else:
    AGENT_CARD_EVENT = None
    TASK_EVENT = None
    RESULT_EVENT = None
    STATUS_EVENT = None


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
    default_input_modes: List[str] = Field(
        default_factory=lambda: ["text/plain", "application/json"]
    )
    default_output_modes: List[str] = Field(
        default_factory=lambda: ["text/plain", "application/json"]
    )
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
