"""Per-task metric match ContextVar and tenant resolution (FEAT-756 M3, D3)."""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Any

from parrot.metrics.models import MetricMatch
from parrot.skills.tenancy import current_skill_tenant, validate_tenant_id

_metric_match: ContextVar[MetricMatch | None] = ContextVar("parrot_metric_match", default=None)


def current_metric_match() -> MetricMatch | None:
    """Return the match bound to the current task, or ``None``."""
    return _metric_match.get()


def bind_metric_match(match: MetricMatch | None) -> Token:
    """Bind ``match`` for the current task and return the reset token."""
    return _metric_match.set(match)


def reset_metric_match(token: Token) -> None:
    """Undo a prior :func:`bind_metric_match` call."""
    _metric_match.reset(token)


def resolve_metric_tenant(
    explicit: str | None = None,
    ctx: Any | None = None,
    default: str | None = None,
) -> str | None:
    """Resolve and validate the first non-empty metric tenant candidate.

    Resolution order is explicit tenant, ``ctx.kwargs["tenant"]``, the
    request-local skill tenant, and finally the supplied default.
    """
    ctx_tenant = None
    ctx_kwargs = getattr(ctx, "kwargs", None) if ctx is not None else None
    if isinstance(ctx_kwargs, dict):
        ctx_tenant = ctx_kwargs.get("tenant")
    chosen = next((candidate for candidate in (explicit, ctx_tenant, current_skill_tenant(), default) if candidate), None)
    return validate_tenant_id(chosen) if chosen else None
