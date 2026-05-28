"""Session state data models for collaborative multi-agent investigation sessions.

Pydantic v2 models for tracking the lifecycle, per-agent round results, and
overall state of a ``MatrixCollaborativeSession``. These are pure data models
with no Matrix I/O.
"""
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class SessionPhase(str, Enum):
    """Phase in the collaborative session lifecycle.

    Attributes:
        CREATED: Session created but not yet started.
        INVESTIGATING: All agents investigating the question in parallel.
        CROSS_POLLINATING: Agents refining answers using peers' findings.
        SYNTHESIZING: Dedicated summarizer agent producing the final answer.
        COMPLETED: Session finished successfully.
        FAILED: Session encountered an unrecoverable error.
    """

    CREATED = "created"
    INVESTIGATING = "investigating"
    CROSS_POLLINATING = "cross_pollinating"
    SYNTHESIZING = "synthesizing"
    COMPLETED = "completed"
    FAILED = "failed"


class AgentRoundResult(BaseModel):
    """Result from one agent for one investigation round.

    Stores the text response and the Matrix event ID of the message
    posted to the room (used for ``m.in_reply_to`` threading in
    cross-pollination rounds).

    Attributes:
        agent_name: Internal agent name (key in crew config).
        display_name: Human-readable agent display name.
        mxid: Full Matrix user ID of the virtual agent.
        round_number: Round index (0 = investigation, 1..N = cross-pollination).
        result_text: Agent's response text.
        event_id: Matrix event ID of the posted message (for reply-to threading).
        timestamp: When the result was produced.
    """

    agent_name: str
    display_name: str
    mxid: str
    round_number: int
    result_text: str
    event_id: str  # Matrix event ID for reply-to threading
    timestamp: datetime


class CollaborativeSessionState(BaseModel):
    """Full state of a collaborative investigation session.

    Tracks all phase transitions, per-agent results across rounds, and
    the final synthesized answer. Serializable for archiving.

    Attributes:
        session_id: Unique session identifier (UUID).
        room_id: Matrix room where the session takes place.
        question: The original question from the ``!investigate`` command.
        phase: Current lifecycle phase.
        current_round: Current cross-pollination round (0 = investigation).
        max_rounds: Configured maximum cross-pollination rounds.
        agent_results: Per-agent results keyed by agent_name, list by round.
        started_at: When the session started (None if not yet started).
        completed_at: When the session ended (None if not yet ended).
        final_synthesis: Summarizer's final answer text (None until synthesized).
    """

    session_id: str
    room_id: str
    question: str
    phase: SessionPhase = SessionPhase.CREATED
    current_round: int = 0
    max_rounds: int = 1
    agent_results: Dict[str, List[AgentRoundResult]] = Field(
        default_factory=dict,
        description="agent_name → list of results per round",
    )
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    final_synthesis: Optional[str] = None
