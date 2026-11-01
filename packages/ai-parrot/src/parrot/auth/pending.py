"""Request-scoped collector of tool needs-auth payloads (FEAT-775 M5 / FEAT-776 M1 / FEAT-777 M4)."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, List, Optional

from parrot.auth.credentials import AuthRequiredPayload

_PENDING_AUTH: ContextVar[Optional[List[AuthRequiredPayload]]] = ContextVar("parrot_pending_auth", default=None)


@contextmanager
def collect_auth_requirements() -> Iterator[List[AuthRequiredPayload]]:
    """Bind a fresh list for the current context; reset the ContextVar token on exit."""
    pending: List[AuthRequiredPayload] = []
    token = _PENDING_AUTH.set(pending)
    try:
        yield pending
    finally:
        _PENDING_AUTH.reset(token)


def record_auth_requirement(payload: AuthRequiredPayload) -> None:
    """Append ``payload`` when a collector is bound; otherwise do nothing."""
    pending = _PENDING_AUTH.get()
    if pending is not None:
        pending.append(payload)


__all__ = ["collect_auth_requirements", "record_auth_requirement"]
