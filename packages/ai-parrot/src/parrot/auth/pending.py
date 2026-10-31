"""Request-scoped collector for tool needs-auth signals (FEAT-775 M5 / FEAT-776 M1).

A channel wrapper binds a collector around one agent turn; ``ToolManager`` appends every
``AuthRequiredPayload`` it produces. Unbound, recording is a no-op.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, List, Optional

from parrot.auth.credentials import AuthRequiredPayload

_PENDING_AUTH: ContextVar[Optional[List[AuthRequiredPayload]]] = ContextVar("parrot_pending_auth", default=None)


@contextmanager
def collect_auth_requirements() -> Iterator[List[AuthRequiredPayload]]:
    """Bind a fresh list for the current context and yield it.

    Yields:
        The list that ``record_auth_requirement`` appends to while bound.
    """
    collected: List[AuthRequiredPayload] = []
    token = _PENDING_AUTH.set(collected)
    try:
        yield collected
    finally:
        _PENDING_AUTH.reset(token)


def record_auth_requirement(payload: AuthRequiredPayload) -> None:
    """Append ``payload`` to the bound collector; do nothing when none is bound.

    Args:
        payload: The needs-auth payload built by ``ToolManager``.
    """
    collected = _PENDING_AUTH.get()
    if collected is not None:
        collected.append(payload)
