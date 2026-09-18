"""Per-turn correlation for lifecycle events via a ``ContextVar`` (FEAT-573 M3).

``EventRegistry.emit_nowait`` and the global-registry forwarder schedule dispatch with
``loop.create_task``, which copies the emitter's ``contextvars.Context``. Setting
``TURN_SCOPE`` around a turn therefore lets a ``where=`` predicate isolate exactly the
tool events that turn caused — in the CLI and in a multi-tenant server alike.
"""

from __future__ import annotations

import contextlib
from contextvars import ContextVar
from typing import Callable, Iterator, Optional

from navigator_eventbus.lifecycle.base import LifecycleEvent  # verified: parrot/core/events/lifecycle/__init__.py:19

TURN_SCOPE: ContextVar[Optional[str]] = ContextVar("parrot_turn_scope", default=None)


@contextlib.contextmanager
def turn_scope(turn_id: str) -> Iterator[None]:
    """Set ``TURN_SCOPE`` to ``turn_id`` for the body; always reset on exit."""
    token = TURN_SCOPE.set(turn_id)
    try:
        yield
    finally:
        TURN_SCOPE.reset(token)


def in_turn_scope(turn_id: str) -> Callable[[LifecycleEvent], bool]:
    """Predicate for ``EventRegistry.subscribe(where=...)``.

    Returns True when the *emitting* context's ``TURN_SCOPE`` equals ``turn_id``. The value
    is read at dispatch time, never captured at subscription time.
    """

    def _predicate(_event: LifecycleEvent) -> bool:
        return TURN_SCOPE.get(None) == turn_id

    return _predicate


__all__ = ["TURN_SCOPE", "turn_scope", "in_turn_scope"]
