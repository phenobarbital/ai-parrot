"""Invocation lifecycle events.

FEAT-176 — Lifecycle Events System.

Covers: before/after/failed agent invocations (ask, ask_stream, conversation).
"""
from dataclasses import dataclass
from typing import Optional

from navigator_eventbus.lifecycle.base import LifecycleEvent


@dataclass(frozen=True)
class BeforeInvokeEvent(LifecycleEvent):
    """Emitted just before an agent invocation begins.

    Attributes:
        agent_name: Name of the invoking agent.
        method: The method being called (``"ask"``, ``"ask_stream"``,
            ``"conversation"``).
        question: The user's input question (may be truncated for safety).
        user_id: Optional user identifier.
        session_id: Optional session identifier.
    """

    agent_name: str = ""
    method: str = ""                   # "ask" | "ask_stream" | "conversation"
    question: str = ""
    user_id: Optional[str] = None
    session_id: Optional[str] = None


@dataclass(frozen=True)
class AfterInvokeEvent(LifecycleEvent):
    """Emitted after a successful agent invocation completes.

    NOT emitted when the invocation fails (InvokeFailedEvent is used instead).

    Attributes:
        agent_name: Name of the invoking agent.
        method: The method that was called.
        duration_ms: Wall-clock time in milliseconds.
        input_tokens: Input token count (if available from the LLM response).
        output_tokens: Output token count (if available from the LLM response).
    """

    agent_name: str = ""
    method: str = ""
    duration_ms: float = 0.0
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None


@dataclass(frozen=True)
class InvokeFailedEvent(LifecycleEvent):
    """Emitted when an agent invocation raises an unhandled exception.

    AfterInvokeEvent is NOT emitted when this event fires.

    Attributes:
        agent_name: Name of the invoking agent.
        method: The method that was called.
        duration_ms: Wall-clock time in milliseconds until failure.
        error_type: ``type(exc).__name__`` of the exception.
        error_message: String representation of the exception.
    """

    agent_name: str = ""
    method: str = ""
    duration_ms: float = 0.0
    error_type: str = ""
    error_message: str = ""
