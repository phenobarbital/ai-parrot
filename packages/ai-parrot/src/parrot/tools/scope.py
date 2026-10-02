"""Tool scope contract (FEAT-622 M3a): what a tool may read from ``studio_scope``."""
from __future__ import annotations

from typing import Any, ClassVar, Literal, Protocol
from uuid import UUID

from parrot.utils.helpers import current_context

ToolAccess = Literal["read", "write"]
ScopeRefusal = Literal[
    "no_context", "no_scope", "no_tenant", "agent_tenant_unset", "tenant_mismatch", "host_tenant_mismatch",
]
_SCOPE_SOURCES = frozenset({"tenant", "caller", "agent"})


class CallerView(Protocol):
    """Satisfied by FEAT-605 ``RequestScope``."""

    user_id: str | None
    tenant: str | None
    groups: frozenset[str]
    is_superuser: bool


class AgentScopeView(Protocol):
    """Satisfied by FEAT-605 ``StudioAgentRef``."""

    agent_id: UUID | None
    name: str
    owner: str | None
    tenant: str | None
    visibility: str


class ToolScopeView(Protocol):
    """Required shape of ``current_context().kwargs["studio_scope"]``."""

    caller: CallerView
    agent: AgentScopeView | None


class ToolScopeUnavailable(Exception):
    """Standard refusal of a tenant-bound tool / options provider."""

    code: ClassVar[str] = "tool_scope_unavailable"

    def __init__(self, reason: ScopeRefusal, *, tool_name: str | None = None) -> None:
        self.reason: ScopeRefusal = reason
        self.tool_name = tool_name
        super().__init__(f"{self.code}: {reason}" + (f" ({tool_name})" if tool_name else ""))


def current_tool_scope() -> ToolScopeView | None:
    """Return the bound ``studio_scope`` or ``None`` (no request context, or nothing bound)."""
    ctx = current_context()
    if ctx is None or ctx.request is None:
        return None
    return ctx.kwargs.get("studio_scope")


def require_tool_scope(*, tool_name: str | None = None) -> tuple[str, ToolScopeView]:
    """Return ``(tenant, scope)`` or raise :class:`ToolScopeUnavailable` (spec "Scope rules" order)."""
    ctx = current_context()
    if ctx is None or ctx.request is None:
        raise ToolScopeUnavailable("no_context", tool_name=tool_name)
    scope = ctx.kwargs.get("studio_scope")
    if scope is None:
        raise ToolScopeUnavailable("no_scope", tool_name=tool_name)
    tenant = scope.caller.tenant
    if tenant is None:
        raise ToolScopeUnavailable("no_tenant", tool_name=tool_name)
    agent = scope.agent
    if agent is not None:
        if agent.tenant is None:
            raise ToolScopeUnavailable("agent_tenant_unset", tool_name=tool_name)
        if agent.tenant != tenant:
            raise ToolScopeUnavailable("tenant_mismatch", tool_name=tool_name)
    return tenant, scope


def is_tenant_bound(cls_or_instance: type | object) -> bool:
    """Effective flag: ``tenant_bound`` or a scope-sourced server-managed param; ToolkitTool inherits."""
    owner = getattr(getattr(cls_or_instance, "bound_method", None), "__self__", None)
    if owner is not None:
        return is_tenant_bound(owner)
    if getattr(cls_or_instance, "tenant_bound", False):
        return True
    params: Any = getattr(cls_or_instance, "server_managed_params", None) or {}
    return any(getattr(param, "source", None) in _SCOPE_SOURCES for param in params.values())


def ensure_tool_scope(cls_or_instance: type | object, *, tool_name: str | None = None) -> None:
    """No-op when not tenant-bound; otherwise :func:`require_tool_scope` (handlers, before construction)."""
    if is_tenant_bound(cls_or_instance):
        require_tool_scope(tool_name=tool_name)
