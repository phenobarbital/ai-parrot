"""Unit tests for PBAC filtering, re-verification and audit (FEAT-477, TASK-2605).

Exercises `PBACGuard` directly against a plain `StreamableHttpMCPServer`
with tools registered straight from `build_exposure_set()` — deliberately
NOT through `AgentMCPMount`/`_AgentBoundMCPServer`. TASK-2610 wired a
`PBACGuard` (built once per mounted agent, keyed off `_pctx_var`) directly
into `_AgentBoundMCPServer.handle_tools_list`/`handle_tools_call`; calling
those methods with a second, standalone `PBACGuard` — as this file did
before TASK-2610 — would double-guard through two independent `PBACGuard`
instances and require `_pctx_var` to already be published, which is
`_guard()`'s job, not this unit test's. A plain server keeps this file's
`PBACGuard` unit tests focused on `PBACGuard` itself.
"""
import json

import pytest
from parrot.auth.permission import PermissionContext, UserSession
from parrot.mcp.agent_tools import build_exposure_set, mcp_tool
from parrot.mcp.config import MCPServerConfig
from parrot.mcp.principal_guard import PBACGuard, resource_for, resource_from_aggregate
from parrot.mcp.transports.streamable_http import StreamableHttpMCPServer
from pydantic import BaseModel


class Args(BaseModel):
    q: str


class Ret(BaseModel):
    ok: bool


class _FakeToolManager:
    def __init__(self, tools: dict):
        self._tools = tools

    def list_tools(self) -> list[str]:
        return list(self._tools)

    def get_tool(self, name: str):
        return self._tools.get(name)


class _FinanceAgent:
    name = "finance"

    def __init__(self):
        self.tool_manager = _FakeToolManager({})

    @mcp_tool(
        name="forecast", description="d", args_schema=Args, returns=Ret, scope="finance:read"
    )
    async def forecast(self, q: str) -> dict:
        return {"forecast": q}

    @mcp_tool(
        name="restricted_tool", description="d", args_schema=Args, returns=Ret, scope="finance:admin"
    )
    async def restricted(self, q: str) -> dict:
        return {"restricted": q}


def _pctx(user_id: str) -> PermissionContext:
    return PermissionContext(
        session=UserSession(user_id=user_id, tenant_id="acme", roles=frozenset())
    )


class _PolicyResolver:
    """Fake `PBACPermissionResolver`-shaped resolver: denies `restricted_tool`."""

    async def can_execute(self, pctx, resource: str, required_permissions) -> bool:
        return "restricted_tool" not in resource


@pytest.fixture
def server():
    """A plain `StreamableHttpMCPServer` with `_FinanceAgent`'s tools
    registered directly (exposure set + its own `tool_manager` tools) —
    the same registration `AgentMCPMount._register_agent_tools` performs,
    without going through the mount (see module docstring).
    """
    agent = _FinanceAgent()
    srv = StreamableHttpMCPServer(MCPServerConfig(name="test-pbac"))
    for tool in build_exposure_set(agent):
        srv.register_tool(tool)
    # AgentMethodTool holds `agent` by weak reference only (TASK-2600) — keep
    # a strong one alive for the test's duration.
    srv._test_agent = agent
    return srv


@pytest.fixture
def guard(server):
    return PBACGuard("finance", server, resolver=_PolicyResolver().can_execute)


@pytest.fixture
def guard_no_resolver(server):
    return PBACGuard("finance", server, resolver=None)


@pytest.fixture
def denied_pctx():
    return _pctx("denied-user")


@pytest.fixture
def ok_pctx():
    return _pctx("ok-user")


class _LedgerSpy:
    def __init__(self):
        self.calls: list[dict] = []

    def __call__(self, entry: dict) -> None:
        self.calls.append(entry)

    @property
    def last(self) -> dict:
        return self.calls[-1]


@pytest.fixture
def ledger_spy():
    return _LedgerSpy()


@pytest.fixture
def guard_with_ledger(server, ledger_spy):
    return PBACGuard(
        "finance", server, resolver=_PolicyResolver().can_execute, audit_sink=ledger_spy
    )


class TestPBACGuard:
    async def test_tools_list_filtered_by_policy(self, guard, denied_pctx):
        listed = await guard.tools_list({}, denied_pctx)
        names = [t["name"] for t in listed["tools"]]
        assert "restricted_tool" not in names
        assert "forecast" in names

    async def test_tools_call_reverifies_policy(self, guard, denied_pctx):
        resp = await guard.tools_call({"name": "restricted_tool"}, denied_pctx)
        assert resp["isError"] is True
        assert "Traceback" not in json.dumps(resp)

    async def test_denial_is_audited(self, guard_with_ledger, denied_pctx, ledger_spy):
        await guard_with_ledger.tools_call({"name": "restricted_tool"}, denied_pctx)
        assert ledger_spy.last["decision"] == "deny"

    async def test_every_call_audited_with_arg_hash(self, guard_with_ledger, ok_pctx, ledger_spy):
        await guard_with_ledger.tools_call(
            {"name": "forecast", "arguments": {"q": "secret"}}, ok_pctx
        )
        entry = ledger_spy.last
        assert entry["decision"] == "allow"
        assert "duration" in entry
        assert "secret" not in json.dumps(entry)

    async def test_deny_by_default_unknown_tool(self, guard, ok_pctx):
        resp = await guard.tools_call({"name": "nope"}, ok_pctx)
        assert resp["isError"] is True

    async def test_deny_by_default_when_no_resolver(self, guard_no_resolver, ok_pctx):
        listed = await guard_no_resolver.tools_list({}, ok_pctx)
        assert listed["tools"] == []
        resp = await guard_no_resolver.tools_call({"name": "forecast"}, ok_pctx)
        assert resp["isError"] is True

    def test_aggregate_name_same_resource(self, guard):
        assert guard.resource_from_aggregate("finance__forecast") == guard.resource_for(
            "forecast"
        )
        assert resource_from_aggregate("finance__forecast") == resource_for("finance", "forecast")

    async def test_permitted_call_executes_and_returns_result(self, guard, ok_pctx):
        resp = await guard.tools_call({"name": "forecast", "arguments": {"q": "x"}}, ok_pctx)
        assert resp.get("isError") in (False, None)
