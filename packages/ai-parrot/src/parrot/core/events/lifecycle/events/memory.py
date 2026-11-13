"""Conversation-memory lifecycle events.

FEAT-525 — Per-Turn Conversation Compaction.

Covers: the deterministic (Stage 0/0.5/1) retention pipeline signaling
that it can no longer fit a session's history within its budget.

FEAT-886 adds :class:`TurnCompletedEvent`, the raw saved-turn payload that is
published to the turn bus only (never to ``EventRegistry``).
"""

from dataclasses import dataclass, field
from typing import Any, Dict

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


@dataclass(frozen=True)
class TurnCompletedEvent(LifecycleEvent):
    """One saved conversation turn, raw and pre-normalization (FEAT-886).

    Published to the turn bus only; never passed to ``EventRegistry.emit()`` —
    the payload contains conversation content and must not reach the
    observability fan-out.

    Attributes:
        agent_name: The agent NAME — the ChatStorage key.
        chatbot_id: The bot's ``memory_key_id`` (explicit ``chatbot_id`` or the name).
        user_id: Owner of the conversation.
        session_id: Conversation session.
        turn: ``ConversationTurn.to_dict()`` taken BEFORE ``add_turn`` normalization.
        presentation: ``TurnPresentation.model_dump()`` (output, usage, tenant, ...).
    """

    agent_name: str = ""
    chatbot_id: str = ""
    user_id: str = ""
    session_id: str = ""
    turn: Dict[str, Any] = field(default_factory=dict)
    presentation: Dict[str, Any] = field(default_factory=dict)
