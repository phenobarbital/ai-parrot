"""Trusted semantic identity and scoped request-context binding."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from copy import deepcopy
from typing import Literal

from parrot.auth import PermissionContext
from parrot.auth.context import _pctx_var
from parrot.core.events.lifecycle import TraceContext
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .errors import SemanticAccessError, SemanticResultError


class SemanticRequestIdentity(BaseModel, frozen=True):
    """Host-authenticated identity for retained semantic results."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    ctx: PermissionContext
    channel: Literal["http", "agent", "mcp-local"]
    agent_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def snapshot_context(self) -> "SemanticRequestIdentity":
        """Copy trusted request context so later caller mutations cannot alter it."""
        object.__setattr__(self, "ctx", deepcopy(self.ctx))
        if not self.agent_id.strip() or not self.session_id.strip():
            raise ValueError("agent_id and session_id must not be blank")
        return self


SemanticRequestIdentity.model_rebuild(_types_namespace={"TraceContext": TraceContext})


_semantic_pctx_var: ContextVar[PermissionContext | None] = ContextVar("semantic_pctx", default=None)
_identity_var: ContextVar[SemanticRequestIdentity | None] = ContextVar("semantic_identity", default=None)


def current_pctx() -> PermissionContext | None:
    """Return the current trusted permission context.

    Returns:
        The bound permission context, or ``None`` outside a binding scope.
    """
    return _semantic_pctx_var.get()


def current_identity() -> SemanticRequestIdentity | None:
    """Return the complete retention identity, if bound.

    Returns:
        The bound identity, or ``None`` for context-only or unbound calls.
    """
    return _identity_var.get()


def require_identity() -> SemanticRequestIdentity:
    """Deny retention/handoff when no complete trusted scope is bound.

    Returns:
        The bound trusted identity.

    Raises:
        SemanticResultError: If no complete identity is bound.
    """
    identity = _identity_var.get()
    if identity is None:
        raise SemanticResultError(
            "identity_required",
            "Result retention requires a host-bound agent/session identity",
        )
    return identity


def _trusted_scope(ctx: PermissionContext) -> tuple[object, ...]:
    """Return the canonical trusted attributes of a permission context."""
    return (ctx.user_id, ctx.tenant_id, frozenset(ctx.roles), ctx.session.metadata, ctx.extra)


@asynccontextmanager
async def bind_semantic_context(
    ctx: PermissionContext, *, identity: SemanticRequestIdentity | None = None
) -> AsyncIterator[None]:
    """Bind copied context and identity; restore all tokens in finally.

    Args:
        ctx: Host-authenticated permission context for this call.
        identity: Optional complete retention identity; it must describe the same subject as ``ctx``.

    Yields:
        None while the binding is active.

    Raises:
        SemanticAccessError: If ``ctx`` is missing or disagrees with ``identity``.
    """
    if not isinstance(ctx, PermissionContext):
        raise SemanticAccessError("context_required", "A trusted permission context is required")
    if identity is not None and _trusted_scope(identity.ctx) != _trusted_scope(ctx):
        raise SemanticAccessError("identity_mismatch", "Identity does not match the trusted request context")
    bound = deepcopy(ctx)
    satellite_token = _semantic_pctx_var.set(bound)
    try:
        core_token = _pctx_var.set(bound)
        try:
            identity_token = _identity_var.set(identity)
            try:
                yield
            finally:
                _identity_var.reset(identity_token)
        finally:
            _pctx_var.reset(core_token)
    finally:
        _semantic_pctx_var.reset(satellite_token)
