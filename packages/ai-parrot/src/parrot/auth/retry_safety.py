"""Turn-local evidence that no tool body began, for server-authored ``retry_safe`` (FEAT-777 M4)."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Iterator, List, Optional

_TURN: ContextVar[Optional["TurnExecutionTracker"]] = ContextVar("parrot_turn_execution", default=None)


@dataclass
class TurnExecutionTracker:
    """Counts dispatches and how each one ended before/after the tool body."""

    dispatches: int = 0
    bodies_started: int = 0
    pre_body_auth_failures: int = 0
    incomplete_reasons: List[str] = field(default_factory=list)

    def mark_dispatch(self) -> None:
        """A ToolManager dispatch reached the execution boundary."""
        self.dispatches += 1

    def mark_body_started(self) -> None:
        """A tool body (function, executor or ``_execute``) is about to run — permanently unsafe."""
        self.bodies_started += 1

    def mark_pre_body_auth_failure(self) -> None:
        """The credential gate refused before the body ran."""
        self.pre_body_auth_failures += 1

    def mark_incomplete(self, reason: str) -> None:
        """Evidence is not trustworthy (cancellation, unknown path, delegation)."""
        self.incomplete_reasons.append(reason)

    def retry_safe(self, *, auth_requirements: int, reported_tool_calls: int) -> bool:
        """True only for one outstanding auth requirement with every dispatch explained as a pre-body auth failure."""
        return (
            not self.incomplete_reasons
            and self.bodies_started == 0
            and auth_requirements == 1
            and self.dispatches >= 1
            and self.dispatches == self.pre_body_auth_failures
            and reported_tool_calls == self.dispatches
        )


@contextmanager
def track_turn() -> Iterator[TurnExecutionTracker]:
    """Bind a fresh tracker for one chat turn; always reset."""
    tracker = TurnExecutionTracker()
    token = _TURN.set(tracker)
    try:
        yield tracker
    finally:
        _TURN.reset(token)


def current_turn_tracker() -> Optional[TurnExecutionTracker]:
    """Return the tracker bound to this turn, or ``None`` outside a tracked turn."""
    return _TURN.get()


__all__ = ["TurnExecutionTracker", "track_turn", "current_turn_tracker"]
