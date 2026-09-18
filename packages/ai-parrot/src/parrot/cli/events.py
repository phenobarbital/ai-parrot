"""Presentation-neutral turn lifecycle events for the Parrot agent CLI (FEAT-573 M4).

One ``TurnRunner`` (parrot/cli/session.py) produces these; the inline REPL and the Textual
workspace consume them. Nothing here performs I/O.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from pydantic import BaseModel, ConfigDict, Field  # verified: parrot/cli/repl.py:18, parrot/models/responses.py:186

from parrot.cli.commands import ConversationTurn  # verified: parrot/cli/commands.py:38

if TYPE_CHECKING:  # added by TASK-3406
    from parrot.cli.commands import CommandContext

#: Awaited after each COMPLETED turn, before control returns to the presenter.
PostTurnHook = Callable[["CommandContext", ConversationTurn], Awaitable[None]]


class TurnEventKind(str, Enum):
    """Discriminator for :class:`TurnEvent` subclasses."""

    STARTED = "started"
    DELTA = "delta"
    TOOL_STARTED = "tool_started"
    TOOL_FINISHED = "tool_finished"
    TOOL_FAILED = "tool_failed"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TurnEvent(BaseModel):
    """Base event: ``seq`` is monotonic per turn (starts at 0), ``at`` is wall-clock."""

    model_config = ConfigDict(arbitrary_types_allowed=True)
    kind: TurnEventKind
    turn_id: str
    seq: int = Field(ge=0)
    at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TurnStarted(TurnEvent):
    kind: TurnEventKind = TurnEventKind.STARTED
    query: str
    streaming: bool


class TextDelta(TurnEvent):
    kind: TurnEventKind = TurnEventKind.DELTA
    text: str


class ToolStarted(TurnEvent):
    """``call_id`` is the lifecycle event's ``trace_context.span_id``; ``args_summary`` is already truncated."""

    kind: TurnEventKind = TurnEventKind.TOOL_STARTED
    call_id: str
    tool_name: str
    args_summary: dict[str, Any] = Field(default_factory=dict)


class ToolFinished(TurnEvent):
    kind: TurnEventKind = TurnEventKind.TOOL_FINISHED
    call_id: str
    tool_name: str
    duration_ms: float
    result_status: str
    result_size_bytes: int


class ToolFailed(TurnEvent):
    kind: TurnEventKind = TurnEventKind.TOOL_FAILED
    call_id: str
    tool_name: str
    duration_ms: float
    error_type: str
    error_message: str


class TurnCompleted(TurnEvent):
    """``message`` is the AIMessage or backend response object (duck-typed: .output/.response/.tool_calls/.usage)."""

    kind: TurnEventKind = TurnEventKind.COMPLETED
    text: str
    message: Any


class TurnFailed(TurnEvent):
    kind: TurnEventKind = TurnEventKind.FAILED
    error_type: str
    error_message: str
    partial_text: str = ""


class TurnCancelled(TurnEvent):
    kind: TurnEventKind = TurnEventKind.CANCELLED
    partial_text: str = ""


class BackendCapabilities(BaseModel):
    """What a bot-like backend can do; read by ``TurnRunner`` via ``getattr(bot, 'capabilities', None)``."""

    streaming: bool = True
    live_tool_events: bool = False
    usage: bool = False
    resume: bool = False


def summarize_message_text(message: Any) -> str:
    """``output`` if str, else ``response``, else ``json.dumps(output)`` — mirrors renderer.py:98-112. Never raises."""
    output = getattr(message, "output", None)
    if output is None:
        output = getattr(message, "response", None) or ""

    if isinstance(output, str):
        return output
    if isinstance(output, (dict, list)):
        try:
            return json.dumps(output, indent=2, default=str)
        except (TypeError, ValueError):
            return str(output)
    if output is not None:
        return str(output)
    return ""
