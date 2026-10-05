"""Request-scoped write identity for the wiki tools (FEAT-569).

The MCP tools used to hardcode ``"agent:mcp"``. The remote server sets the
caller's ``X-Wiki-Actor`` here per request; the local stdio server sets
nothing and keeps the historical default.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

DEFAULT_ACTOR = "agent:mcp"

_ACTOR: ContextVar[str | None] = ContextVar("wiki_actor", default=None)


def current_actor(default: str = DEFAULT_ACTOR) -> str:
    """Return the identity asserting the current write.

    Args:
        default: Value when no actor was set for this context.

    Returns:
        The actor string, e.g. ``"human:jlara"`` or ``"agent:mcp"``.
    """
    return _ACTOR.get() or default


@contextmanager
def actor_scope(actor: str | None) -> Iterator[None]:
    """Set the actor for the enclosed block; ``None`` leaves the context untouched.

    Args:
        actor: Identity to assert, or ``None`` for a no-op scope.
    """
    if actor is None:
        yield
        return
    token = _ACTOR.set(actor)
    try:
        yield
    finally:
        _ACTOR.reset(token)
