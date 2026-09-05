"""Agent-identity and user-context ContextVars for observability.

FEAT-228 TASK-1499. Provides task-local carriers that the bot sets around
each public invocation and the LLM client reads when building its lifecycle
events. Because ``ContextVar`` values are copied into tasks spawned via
``asyncio.create_task``, any LLM client call made within the invocation
observes the correct values. Nested invocations push/pop their own
tokens, so an inner agent's calls are attributed to the inner agent and the
outer values are restored on exit.

Public surface:
  * ``current_agent_name`` — module-level ``ContextVar[Optional[str]]`` with
    default ``None``.
  * ``current_user_id`` — module-level ``ContextVar[Optional[str]]`` with
    default ``None``. Carries the ``user_id`` from the bot invocation scope
    so OTEL span attributes can include per-user identity for usage tracking
    (e.g. OpenLIT per-user dashboards). NEVER used in metric labels
    (cardinality explosion).
  * ``current_session_id`` — module-level ``ContextVar[Optional[str]]`` with
    default ``None``. Same rationale as ``current_user_id``.
  * ``current_memory_key_id`` — module-level ``ContextVar[Optional[str]]``
    with default ``None``. FEAT-525: carries the bot's ``memory_key_id``
    (the key a conversation is stored under) so ``read_omitted_content``
    can scope its omission-store lookup without a bot reference. Bound
    *after* ``user_id``/``session_id`` are defaulted, so it is never set
    while the other two are still ``None``.
  * ``agent_identity(name)`` — context-manager helper that does a token-based
    ``set()`` / ``reset()`` so nested scopes restore the prior value.
  * ``invocation_context(agent_name, user_id, session_id, memory_key_id)`` —
    context-manager that binds all four ContextVars atomically. Preferred
    over setting them individually.
  * ``current_run_id`` — module-level ``ContextVar[Optional[str]]`` with
    default ``None``. FEAT-479: carries the dev-loop / dev-flow run
    identifier so usage-accounting events emitted deep inside
    ``AbstractClient`` can be attributed to the run that triggered them.
  * ``current_seat`` — module-level ``ContextVar[Optional[str]]`` with
    default ``None``. FEAT-479: carries the accounting seat — a node id
    (``"qa"``) or a pool worker id (``"development.w1"``). Deliberately a
    free string, not ``parrot.flows.dev_loop.session_state.NodeId`` (a
    closed ``Literal`` that cannot express pool-worker seats).
  * ``usage_attribution(run_id, seat)`` — context-manager that binds
    ``current_run_id`` and ``current_seat`` atomically.

Stdlib only — no third-party dependency.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, Optional

__all__ = [
    "current_agent_name",
    "current_user_id",
    "current_session_id",
    "current_memory_key_id",
    "agent_identity",
    "invocation_context",
    "current_run_id",
    "current_seat",
    "usage_attribution",
]

current_agent_name: ContextVar[Optional[str]] = ContextVar("parrot_current_agent_name", default=None)

current_user_id: ContextVar[Optional[str]] = ContextVar("parrot_current_user_id", default=None)

current_session_id: ContextVar[Optional[str]] = ContextVar("parrot_current_session_id", default=None)

#: FEAT-525: the bot's ``memory_key_id`` for the current invocation. Bound
#: after ``user_id``/``session_id`` are defaulted at every entry point (see
#: ``bots/base.py``) so ``read_omitted_content`` never observes a session
#: that is only partially scoped.
current_memory_key_id: ContextVar[Optional[str]] = ContextVar("parrot_current_memory_key_id", default=None)


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


@contextmanager
def invocation_context(
    agent_name: Optional[str],
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    memory_key_id: Optional[str] = None,
) -> Iterator[None]:
    """Bind agent name, user_id, session_id and memory_key_id for the block.

    Uses token-based ``set()`` / ``reset()`` on all four ContextVars so
    nested invocations restore the prior values correctly on exit.

    Args:
        agent_name: The ``AbstractBot.name`` of the invoking agent.
        user_id: The user identifier from the invocation scope.
        session_id: The session identifier from the invocation scope.
        memory_key_id: The bot's ``memory_key_id`` (FEAT-525). Callers
            should pass this only after ``user_id``/``session_id`` have
            already been defaulted.

    Example::

        with invocation_context("porygon", user_id="u-42", session_id="s-7",
                                memory_key_id="porygon"):
            # current_agent_name.get() == "porygon"
            # current_user_id.get() == "u-42"
            # current_session_id.get() == "s-7"
            # current_memory_key_id.get() == "porygon"
        # all four restored to their prior values
    """
    tok_agent = current_agent_name.set(agent_name)
    tok_user = current_user_id.set(user_id)
    tok_session = current_session_id.set(session_id)
    tok_memkey = current_memory_key_id.set(memory_key_id)
    try:
        yield
    finally:
        current_memory_key_id.reset(tok_memkey)
        current_session_id.reset(tok_session)
        current_user_id.reset(tok_user)
        current_agent_name.reset(tok_agent)


current_run_id: ContextVar[Optional[str]] = ContextVar("parrot_current_run_id", default=None)

current_seat: ContextVar[Optional[str]] = ContextVar("parrot_current_seat", default=None)


@contextmanager
def usage_attribution(
    run_id: Optional[str],
    seat: Optional[str] = None,
) -> Iterator[None]:
    """Bind run/seat attribution for events emitted inside this block.

    Uses token-based ``set()`` / ``reset()`` so nested blocks restore the
    prior values rather than clearing them.

    Args:
        run_id: The dev-loop / dev-flow run identifier.
        seat: The accounting seat — a node id (``"qa"``) or a pool worker id
            (``"development.w1"``). Deliberately a free string, not a
            ``NodeId``.

    Example::

        with usage_attribution("run-abc123", "development.w1"):
            ...  # AfterClientCallEvents emitted here carry this attribution
    """
    tok_run = current_run_id.set(run_id)
    tok_seat = current_seat.set(seat)
    try:
        yield
    finally:
        current_seat.reset(tok_seat)
        current_run_id.reset(tok_run)
