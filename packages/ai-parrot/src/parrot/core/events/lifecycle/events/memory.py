"""Conversation-memory lifecycle events.

FEAT-525 — Per-Turn Conversation Compaction.

Covers: the deterministic (Stage 0/0.5/1) retention pipeline signaling
that it can no longer fit a session's history within its budget.
"""
from dataclasses import dataclass
from navigator_eventbus.lifecycle.base import LifecycleEvent


@dataclass(frozen=True)
class Stage2CompactionNeededEvent(LifecycleEvent):
    """Emitted once per session when deterministic pruning can no longer fit the history.

    Emitted from ``AbstractBot.save_conversation_turn`` on the first
    ``False → True`` flip of the persisted ``stage2_needed`` flag (spec
    §2 "Component Diagram", read path). Stage 2 (LLM summary turns) is
    out of scope for this feature; this event is the reserved trigger
    surface a future summarization stage would subscribe to.

    Attributes:
        agent_name: Name of the agent whose history overflowed.
        session_id: The session that needs Stage 2 summarization.
        history_estimate: The compacted history's total estimated token
            size for this round.
        available: The bot's context budget's available token count at
            the time of the flip.
        dropped_turns: Number of turns dropped (beyond pruning) in the
            round that triggered this event.
    """

    agent_name: str = ""
    session_id: str = ""
    history_estimate: int = 0
    available: int = 0
    dropped_turns: int = 0
