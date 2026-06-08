"""Agent-identity ContextVar for per-agent cost and usage metrics.

FEAT-228 TASK-1499. Provides a task-local carrier that the bot sets around
each public invocation and the LLM client reads when building its lifecycle
events. Because ``ContextVar`` values are copied into tasks spawned via
``asyncio.create_task``, any LLM client call made within the invocation
observes the correct agent name. Nested invocations push/pop their own
token, so an inner agent's calls are attributed to the inner agent and the
outer value is restored on exit.

Public surface:
  * ``current_agent_name`` — module-level ``ContextVar[Optional[str]]`` with
    default ``None``.
  * ``agent_identity(name)`` — context-manager helper that does a token-based
    ``set()`` / ``reset()`` so nested scopes restore the prior value.

Stdlib only — no third-party dependency.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, Optional

__all__ = ["current_agent_name", "agent_identity"]

current_agent_name: ContextVar[Optional[str]] = ContextVar(
    "parrot_current_agent_name", default=None
)


@contextmanager
def agent_identity(name: Optional[str]) -> Iterator[None]:
    """Bind *name* as the active agent for the duration of the block.

    Uses a token-based ``set()`` / ``reset()`` so nested invocations restore
    the prior value rather than resetting to ``None``.

    Args:
        name: The ``AbstractBot.name`` of the invoking agent.  ``None`` is
            accepted for call-sites that do not have an agent in scope; the
            prior value is still restored correctly on exit.

    Example::

        with agent_identity("porygon"):
            # current_agent_name.get() == "porygon"
            with agent_identity("inner"):
                # current_agent_name.get() == "inner"
            # current_agent_name.get() == "porygon" (restored)
        # current_agent_name.get() is None (restored)
    """
    token = current_agent_name.set(name)
    try:
        yield
    finally:
        current_agent_name.reset(token)
