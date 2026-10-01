"""M3a unit tests for the tool scope contract (FEAT-622)."""
from dataclasses import dataclass, field

import pytest
from aiohttp.test_utils import make_mocked_request

from parrot.tools.abstract import AbstractTool
from parrot.tools.scope import (
    ToolScopeUnavailable,
    current_tool_scope,
    ensure_tool_scope,
    is_tenant_bound,
    require_tool_scope,
)
from parrot.tools.toolkit import AbstractToolkit
from parrot.utils.helpers import RequestContext, _current_ctx


@dataclass(frozen=True)
class _Caller:
    user_id: str | None = "u1"
    tenant: str | None = "acme"
    groups: frozenset = field(default_factory=frozenset)
    is_superuser: bool = False


@dataclass(frozen=True)
class _Agent:
    agent_id: object = None
    name: str = "a"
    owner: str | None = "u1"
    tenant: str | None = "acme"
    visibility: str = "private"


@dataclass(frozen=True)
class _Scope:
    caller: _Caller = field(default_factory=_Caller)
    agent: _Agent | None = None


def _ctx(scope=None, *, with_request=True) -> RequestContext:
    request = make_mocked_request("POST", "/x") if with_request else None
    kwargs = {} if scope is None else {"studio_scope": scope}
    return RequestContext(request=request, **kwargs)


def _scope_for(reason: str):
    return {
        "no_context": None,
        "no_scope": _ctx(),
        "no_tenant": _ctx(_Scope(caller=_Caller(tenant=None))),
        "agent_tenant_unset": _ctx(_Scope(agent=_Agent(tenant=None))),
        "tenant_mismatch": _ctx(_Scope(agent=_Agent(tenant="other"))),
    }[reason]


@pytest.mark.parametrize("reason", ["no_context", "no_scope", "no_tenant", "agent_tenant_unset", "tenant_mismatch"])
def test_require_scope_refusals(reason):
    """Each ScopeRefusal from a real RequestContext / no context."""
    token = _current_ctx.set(_scope_for(reason))
    try:
        with pytest.raises(ToolScopeUnavailable) as err:
            require_tool_scope(tool_name="t")
    finally:
        _current_ctx.reset(token)
    assert err.value.reason == reason
    assert err.value.code == "tool_scope_unavailable"


def test_request_none_is_no_context():
    """A context without a request (scheduler/A2A shape) is no_context even with a scope."""
    token = _current_ctx.set(_ctx(_Scope(), with_request=False))
    try:
        assert current_tool_scope() is None
        with pytest.raises(ToolScopeUnavailable) as err:
            require_tool_scope()
    finally:
        _current_ctx.reset(token)
    assert err.value.reason == "no_context"


def test_require_scope_returns_caller_tenant():
    """Happy path returns (caller.tenant, scope); the caller is the principal."""
    scope = _Scope(agent=_Agent())
    token = _current_ctx.set(_ctx(scope))
    try:
        assert require_tool_scope() == ("acme", scope)
        assert current_tool_scope() is scope
    finally:
        _current_ctx.reset(token)


class _Bound(AbstractToolkit):
    tenant_bound = True

    async def ping(self) -> str:
        """Ping."""
        return "pong"


class _Plain(AbstractToolkit):
    async def ping(self) -> str:
        """Ping."""
        return "pong"


@dataclass
class _Param:
    source: str


class _ParamTool(AbstractTool):
    name = "p"
    description = "p"
    server_managed_params = {"tenant_id": _Param("tenant")}

    async def _execute(self, **kwargs):
        return None


def test_is_tenant_bound_variants():
    """Flag, scope-sourced param and ToolkitTool inheritance; plain is not bound."""
    assert is_tenant_bound(_Bound)
    assert is_tenant_bound(_ParamTool)
    assert not is_tenant_bound(_Plain)
    tools = _Bound().get_tools()
    assert tools and all(is_tenant_bound(t) for t in tools)
    assert not any(is_tenant_bound(t) for t in _Plain().get_tools())


def test_ensure_tool_scope_noop_and_refusal():
    """No-op for unbound classes; refuses a bound class without scope."""
    ensure_tool_scope(_Plain)
    with pytest.raises(ToolScopeUnavailable):
        ensure_tool_scope(_Bound, tool_name="ping")
