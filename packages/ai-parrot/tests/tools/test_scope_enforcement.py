"""FEAT-622 M3b: the tenant scope gate runs first, for every tenant-bound tool, before any side effect."""
from __future__ import annotations

import asyncio
import importlib

import pytest
from aiohttp.test_utils import make_mocked_request
from pydantic import BaseModel

from parrot.auth.confirmation import _approved_call
from parrot.core.events.lifecycle.events import BeforeToolCallEvent
from parrot.tools.abstract import AbstractTool
from parrot.tools.scope import ToolScopeUnavailable
from parrot.tools.server_params import ServerParam
from parrot.tools.toolkit import AbstractToolkit
from parrot.utils.helpers import RequestContext, _current_ctx

from ._host_probe import host_plugins  # noqa: F401
from .test_tool_scope import _Agent, _Caller, _Scope


def _bind(scope=None, *, with_request=True):
    kwargs = {} if scope is None else {"studio_scope": scope}
    request = make_mocked_request("POST", "/x") if with_request else None
    return _current_ctx.set(RequestContext(request=request, **kwargs))


def _probe():
    probe = importlib.import_module("plugins.tools.probe")
    for key in probe.COUNTERS:
        probe.COUNTERS[key] = 0
    return probe


BAD_SCOPES = {
    "no_context": None,
    "no_tenant": _Scope(caller=_Caller(tenant=None)),
    "tenant_mismatch": _Scope(agent=_Agent(tenant="other")),
}


def _bind_for(reason):
    if reason == "no_context":
        return _bind(None, with_request=False)
    if reason == "no_scope":
        return _bind(None)
    return _bind(BAD_SCOPES[reason])


@pytest.mark.parametrize("reason", ["no_context", "no_scope", "no_tenant", "tenant_mismatch"])
async def test_standalone_tool_refuses_before_side_effects(host_plugins, reason):  # noqa: F811
    """ProbeTool is tenant-bound with NO scope-sourced params: the gate still runs, before every hook."""
    probe = _probe()
    tool = probe.ProbeTool()
    seen: list = []

    async def before(event):
        seen.append(event)

    tool.events.subscribe(BeforeToolCallEvent, before)
    token = _bind_for(reason)
    try:
        result = await tool.execute(value="x")
    finally:
        _current_ctx.reset(token)
    await asyncio.sleep(0)
    assert result.status == "error" and result.success is False
    assert result.metadata["error_code"] == "tool_scope_unavailable" and result.metadata["reason"] == reason
    assert result.metadata["tool_name"] == "tp_probe_tool"
    assert probe.COUNTERS["tool_opened"] == 0 and probe.COUNTERS["executed"] == 0
    assert seen == []   # no BeforeToolCallEvent on refusal


async def test_standalone_tool_runs_inside_a_valid_scope(host_plugins):  # noqa: F811
    probe = _probe()
    tool = probe.ProbeTool()   # access undeclared => a write: it also needs ToolManager's approval token
    token = _bind(_Scope())
    try:
        with _approved_call(tool, {"value": "x"}):
            result = await tool.execute(value="x")
        refused = await tool.execute(value="x")   # scope fine, no approval: the second gate refuses
    finally:
        _current_ctx.reset(token)
    assert result.status == "success" and refused.metadata["error_code"] == "confirmation_required"
    assert probe.COUNTERS["executed"] == 1


async def test_toolkit_gate_runs_before_ensure_open_and_pre_execute(host_plugins):  # noqa: F811
    probe = _probe()
    toolkit = probe.ProbeToolkit()
    pre_calls: list = []

    async def pre(*args, **kwargs):
        pre_calls.append(1)

    toolkit._pre_execute = pre
    whoami = next(tool for tool in toolkit.get_tools() if tool.name == "tp_whoami")
    token = _bind(None)  # a request context with no studio_scope
    try:
        result = await whoami.execute()
    finally:
        _current_ctx.reset(token)
    assert result.metadata["error_code"] == "tool_scope_unavailable" and result.metadata["reason"] == "no_scope"
    assert probe.COUNTERS["opened"] == 0 and pre_calls == []
    token = _bind(_Scope())
    try:
        ok = await whoami.execute()
    finally:
        _current_ctx.reset(token)
    assert ok.status == "success" and probe.COUNTERS["opened"] == 1


async def test_options_provider_refuses_on_direct_call(host_plugins):  # noqa: F811
    probe = _probe()
    toolkit = probe.ProbeToolkit()
    for target in (probe.ProbeToolkit, toolkit):   # the probe declares a classmethod; both call shapes are gated
        with pytest.raises(ToolScopeUnavailable) as exc:
            await target.config_options("x")
        assert exc.value.reason == "no_context"
    assert probe.COUNTERS["options_calls"] == 0
    token = _bind(_Scope())
    try:
        assert await probe.ProbeToolkit.config_options("x") == []
    finally:
        _current_ctx.reset(token)
    assert probe.COUNTERS["options_calls"] == 1


async def test_options_gate_covers_an_inherited_provider():
    """A tenant-bound subclass that inherits ``config_options`` is gated too (never double-wrapped)."""
    calls = []

    class Parent(AbstractToolkit):
        async def config_options(self, param):
            calls.append(param)
            return []

    class Child(Parent):
        tenant_bound = True

    class GrandChild(Child):
        async def config_options(self, param):
            return await super().config_options(param)

    for cls in (Child, GrandChild):
        with pytest.raises(ToolScopeUnavailable):
            await cls().config_options("p")
    assert calls == []
    assert await Parent().config_options("p") == [] and calls == ["p"]   # a non-tenant toolkit is untouched


class _Args(BaseModel):
    tenant: str = ""


def test_custom_args_schema_exposing_server_managed_is_typeerror():
    with pytest.raises(TypeError, match="server-managed"):
        class Bad(AbstractTool):
            name = "bad"
            description = "d"
            args_schema = _Args
            server_managed_params = {"tenant": ServerParam(source="tenant")}

            async def _execute(self, **kwargs):
                return 1

    class BadToolkit(AbstractToolkit):
        server_managed_params = {"tenant": ServerParam(source="tenant")}

        async def act(self, tenant: str | None = None) -> str:
            """Act."""
            return "x"

        act._args_schema = _Args

    with pytest.raises(TypeError, match="server-managed"):
        BadToolkit().get_tools()


def test_remote_executor_on_tenant_bound_is_typeerror(host_plugins):  # noqa: F811
    probe = _probe()
    with pytest.raises(TypeError, match="remote executor"):
        probe.ProbeTool(executor=object())
    with pytest.raises(TypeError, match="remote executor"):
        probe.ProbeToolkit(executor=object())
    probe.ProbeTool()   # without an executor it constructs
    probe.ProbeToolkit()


async def test_scope_error_is_structured_tool_result():
    """A ToolScopeUnavailable raised inside the call (e.g. the host's own mismatch) is the same structured result."""
    class Raising(AbstractTool):
        name = "raising"
        description = "d"

        class args_schema(BaseModel):  # noqa: N801
            pass

        async def _execute(self, **kwargs):
            raise ToolScopeUnavailable("host_tenant_mismatch", tool_name="raising")

    result = await Raising().execute()
    assert result.status == "error"
    assert result.metadata["error_code"] == "tool_scope_unavailable"
    assert result.metadata["reason"] == "host_tenant_mismatch" and result.metadata["error_type"] == "ToolScopeUnavailable"


async def test_run_is_gated_like_execute(host_plugins):  # noqa: F811
    """``tool.run`` (raw result, no ToolResult) must not bypass the scope gate or the approval token."""
    probe = _probe()
    tool = probe.ProbeTool()
    for reason in ("no_context", "no_scope", "no_tenant", "tenant_mismatch"):
        token = _bind_for(reason)
        try:
            with pytest.raises(ToolScopeUnavailable) as exc:
                await tool.run(value="x")
        finally:
            _current_ctx.reset(token)
        assert exc.value.reason == reason
    assert probe.COUNTERS["executed"] == 0
    token = _bind(_Scope())
    try:
        with pytest.raises(PermissionError):                      # in scope, but a write without an approval token
            await tool.run(value="x")
        with _approved_call(tool, {"value": "x"}):
            assert await tool.run(value="x") == {"ok": True}
    finally:
        _current_ctx.reset(token)
    assert probe.COUNTERS["executed"] == 1


async def test_voicebot_execute_tool_is_gated(host_plugins):  # noqa: F811
    """VoiceBot dispatches tools through ``run`` (gated), never ``_execute`` directly."""
    voice = pytest.importorskip("parrot.bots.voice")
    probe = _probe()
    bot = object.__new__(voice.VoiceBot)
    bot._voice_tools = [probe.ProbeTool()]
    bot.tool_manager = None
    with pytest.raises(ToolScopeUnavailable):
        await bot.execute_tool("tp_probe_tool", {"value": "x"})
    assert probe.COUNTERS["executed"] == 0
