"""Global registry singleton and scope() context manager.

FEAT-176 — Lifecycle Events System.

This module provides the process-wide singleton ``EventRegistry`` that
observes every lifecycle event unless an agent opts out via
``forward_to_global=False``.

The ``scope()`` context manager replaces the global registry with a fresh
one for the duration of the block, then restores the previous registry on
exit — even if the block raises. This is required for test isolation,
especially under pytest parallelism.

Storage uses a ``ContextVar`` so that each asyncio task sees a coherent
registry and nested ``scope()`` blocks operate independently via the
ContextVar token/reset pattern.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, Optional

from parrot.core.events.lifecycle.registry import EventRegistry


# Module-level mutable state is limited to this single ContextVar.
# Never use a plain module-level variable — ContextVar ensures asyncio-task
# safety and correct behavior with nested scope() blocks.
_GLOBAL_REGISTRY: ContextVar[Optional[EventRegistry]] = ContextVar(
    "parrot_lifecycle_global_registry",
    default=None,
)


def get_global_registry() -> EventRegistry:
    """Return the process-wide singleton ``EventRegistry``.

    Lazily constructs the registry on first call.  Subsequent calls in the
    same context return the same instance until a :func:`scope` block
    replaces it.

    The global registry is constructed with ``forward_to_global=False`` to
    prevent infinite recursion (it must not forward events back to itself).

    Returns:
        The current context's global ``EventRegistry`` instance.
    """
    reg = _GLOBAL_REGISTRY.get()
    if reg is None:
        # Global registry never forwards to itself — would cause infinite recursion.
        reg = EventRegistry(forward_to_global=False)
        _GLOBAL_REGISTRY.set(reg)
    return reg


@contextmanager
def scope() -> Iterator[EventRegistry]:
    """Replace the global registry with a fresh one for the block duration.

    Yields a new ``EventRegistry(forward_to_global=False)`` and restores the
    previous registry on exit, even if the block raises.  Use this in tests
    and isolated execution contexts to prevent event leakage between scopes.

    The token-based restore via ``ContextVar.reset(token)`` is the only
    correct way to restore the prior value — direct re-assignment would break
    the ContextVar chain for nested scopes.

    Yields:
        A fresh, isolated ``EventRegistry`` instance.

    Warning:
        Tasks scheduled via ``create_task`` inside the scope may still hold a
        reference to the scoped registry after ``scope()`` exits.  In tests,
        always ``await asyncio.sleep(0)`` before asserting on events forwarded
        to the global registry to ensure all scheduled tasks have completed.

    Example::

        with scope() as reg:
            reg.subscribe(BeforeInvokeEvent, my_listener)
            await agent.ask("hello")
        # Subscriptions are gone after the block.
    """
    fresh = EventRegistry(forward_to_global=False)
    token = _GLOBAL_REGISTRY.set(fresh)
    try:
        yield fresh
    finally:
        _GLOBAL_REGISTRY.reset(token)
