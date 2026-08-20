"""Unit tests for :class:`ClaudeAgentToolBridge` (TASK-2287 — FEAT-434 Claude
Agent Tool Bridge).

Covers spec §3 Module 1 / §5 acceptance criteria:

* Tool -> ``SdkMcpTool`` conversion reuses ``MCPToolAdapter``'s schema.
* The ``confirm`` property is stripped on this path only — the adapter
  itself, and therefore the stdio proxy, is never mutated.
* A tool whose schema conversion fails is skipped (with a warning); the
  rest of the tool set is still exposed.
* Every handler dispatches exclusively through
  ``ToolManager.execute_tool()`` — never ``tool.execute()``.
* Every failure mode (tool exception, timeout, HITL denial) maps to a
  recoverable MCP error result; the handler never raises.
* ``claude_agent_sdk`` stays a strictly lazy import — the module imports
  fine without it, and only ``build_server()`` needs it.

`create_sdk_mcp_server` is patched to a recorder in most tests below —
that lets assertions inspect the real ``SdkMcpTool`` objects (name,
description, input_schema, handler) our code builds without depending on
`claude_agent_sdk`'s internal ``mcp.server.Server``/wire-protocol layer,
which is out of scope for this bridge module.
"""
from __future__ import annotations

import asyncio
import sys
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from parrot.auth.permission import PermissionContext, UserSession
from parrot.mcp.adapter import MCPToolAdapter
from parrot.tools.abstract import AbstractTool, ToolResult

# ---------------------------------------------------------------------------
# Fixtures / stubs
# ---------------------------------------------------------------------------


class _EchoTool(AbstractTool):
    """A trivial tool with a real args_schema (default base schema)."""

    name = "echo_tool"

    def __init__(self, **kwargs):
        # AbstractTool.__init__ falls back to the class *docstring* (not the
        # class-level `description` attribute) when `description=` isn't
        # passed explicitly — pass it here so tests see the intended text.
        super().__init__(description="Echoes its input.", **kwargs)

    async def _execute(self, **kwargs: Any) -> ToolResult:
        return ToolResult(success=True, status="success", result="echoed")


class _ConfirmingTool(AbstractTool):
    """A tool requiring confirmation — the adapter injects `confirm`."""

    name = "confirming_tool"

    def __init__(self, **kwargs):
        super().__init__(
            description="A destructive tool.",
            routing_meta={"requires_confirmation": True},
            **kwargs,
        )

    async def _execute(self, **kwargs: Any) -> ToolResult:
        return ToolResult(success=True, status="success", result="done")


class _BrokenSchemaTool(AbstractTool):
    """A tool whose `MCPToolAdapter.to_mcp_tool_definition()` call blows up."""

    name = "broken_tool"

    def __init__(self, **kwargs):
        super().__init__(description="Deliberately broken for the skip test.", **kwargs)

    async def _execute(self, **kwargs: Any) -> ToolResult:
        return ToolResult(success=True, status="success", result=None)


@pytest.fixture
def permission_context() -> PermissionContext:
    return PermissionContext(session=UserSession(user_id="u1", tenant_id="t1", roles=frozenset()))


@pytest.fixture
def captured_server(monkeypatch):
    """Patch `claude_agent_sdk.create_sdk_mcp_server` to a recorder.

    Returns a dict populated with `name` and `tools` (the real list of
    `SdkMcpTool` objects our code built) after `build_server()` runs.
    """
    import claude_agent_sdk

    captured: dict[str, Any] = {}

    def _fake_create(name: str, version: str = "1.0.0", tools=None):
        captured["name"] = name
        captured["version"] = version
        captured["tools"] = tools or []
        return {"type": "sdk", "name": name, "instance": None}

    monkeypatch.setattr(claude_agent_sdk, "create_sdk_mcp_server", _fake_create)
    return captured


def _make_bridge(tool_manager=None, **kwargs):
    from parrot.clients.claude_agent_bridge import ClaudeAgentToolBridge

    return ClaudeAgentToolBridge(tool_manager or MagicMock(), **kwargs)


def _tool_by_name(captured: dict, name: str):
    for sdk_tool in captured["tools"]:
        if sdk_tool.name == name:
            return sdk_tool
    raise AssertionError(f"{name!r} not among captured tools: {captured['tools']!r}")


# ---------------------------------------------------------------------------
# TestServerAssembly
# ---------------------------------------------------------------------------


class TestServerAssembly:
    def test_tool_becomes_sdk_mcp_tool_with_adapter_schema(self, captured_server):
        bridge = _make_bridge()
        tool = _EchoTool()
        expected_schema = MCPToolAdapter(tool).to_mcp_tool_definition()["inputSchema"]

        bridge.build_server([tool])

        sdk_tool = _tool_by_name(captured_server, "echo_tool")
        assert sdk_tool.description == "Echoes its input."
        assert sdk_tool.input_schema == expected_schema

    def test_confirm_property_stripped_from_properties_and_required(self, captured_server):
        bridge = _make_bridge()
        tool = _ConfirmingTool()

        bridge.build_server([tool])

        sdk_tool = _tool_by_name(captured_server, "confirming_tool")
        properties = sdk_tool.input_schema.get("properties", {})
        required = sdk_tool.input_schema.get("required", [])
        assert "confirm" not in properties
        assert "confirm" not in required

    def test_adapter_not_mutated_stdio_schema_keeps_confirm(self, captured_server):
        bridge = _make_bridge()
        tool = _ConfirmingTool()

        bridge.build_server([tool])

        # The stdio proxy builds its own adapter fresh each time — confirm
        # must still be injected there, proving the bridge never mutated
        # MCPToolAdapter itself.
        stdio_schema = MCPToolAdapter(tool).to_mcp_tool_definition()["inputSchema"]
        assert "confirm" in stdio_schema.get("properties", {})
        assert "confirm" in stdio_schema.get("required", [])

    def test_schema_extraction_failure_skips_only_that_tool(self, captured_server, monkeypatch):
        bridge = _make_bridge()
        good_tool = _EchoTool()
        bad_tool = _BrokenSchemaTool()

        original_to_def = MCPToolAdapter.to_mcp_tool_definition

        def _boom(self):
            if self.tool.name == "broken_tool":
                raise RuntimeError("schema conversion exploded")
            return original_to_def(self)

        monkeypatch.setattr(MCPToolAdapter, "to_mcp_tool_definition", _boom)

        bridge.build_server([good_tool, bad_tool])

        names = [t.name for t in captured_server["tools"]]
        assert "echo_tool" in names
        assert "broken_tool" not in names
        assert bridge.exposed_names() == ["mcp__parrot__echo_tool"]

    def test_exposed_names_use_mcp_ns_prefix(self, captured_server):
        bridge = _make_bridge(namespace="myns")
        bridge.build_server([_EchoTool()])

        assert bridge.exposed_names() == ["mcp__myns__echo_tool"]
        assert captured_server["name"] == "myns"


# ---------------------------------------------------------------------------
# TestHandlerDispatch
# ---------------------------------------------------------------------------


class TestHandlerDispatch:
    async def test_handler_dispatches_through_execute_tool(self, captured_server, permission_context):
        tool_manager = MagicMock()
        tool_manager.execute_tool = AsyncMock(return_value="ok")
        bridge = _make_bridge(tool_manager)

        bridge.build_server([_EchoTool()], permission_context)
        handler = _tool_by_name(captured_server, "echo_tool").handler

        await handler({"text": "hi"})

        tool_manager.execute_tool.assert_awaited_once_with(
            "echo_tool", {"text": "hi"}, permission_context
        )

    async def test_handler_never_calls_tool_execute_directly(self, captured_server, monkeypatch):
        tool_manager = MagicMock()
        tool_manager.execute_tool = AsyncMock(return_value="ok")
        bridge = _make_bridge(tool_manager)
        tool = _EchoTool()

        def _forbidden(*args, **kwargs):
            raise AssertionError("tool.execute() must never be called by the bridge")

        monkeypatch.setattr(tool, "execute", _forbidden)
        monkeypatch.setattr(tool, "_execute", _forbidden)

        bridge.build_server([tool])
        handler = _tool_by_name(captured_server, "echo_tool").handler

        result = await handler({})
        assert result["isError"] is False

    async def test_handler_maps_toolresult_to_mcp_content(self, captured_server):
        tool_manager = MagicMock()
        tool_manager.execute_tool = AsyncMock(return_value="raw payload")
        bridge = _make_bridge(tool_manager)
        bridge.build_server([_EchoTool()])
        handler = _tool_by_name(captured_server, "echo_tool").handler

        result = await handler({})

        assert result["isError"] is False
        assert result["content"][0]["text"] == "raw payload"

    async def test_permission_context_forwarded(self, captured_server, permission_context):
        tool_manager = MagicMock()
        tool_manager.execute_tool = AsyncMock(return_value="ok")
        bridge = _make_bridge(tool_manager)
        bridge.build_server([_EchoTool()], permission_context)
        handler = _tool_by_name(captured_server, "echo_tool").handler

        await handler({})

        _, _, ctx_arg = tool_manager.execute_tool.await_args.args
        assert ctx_arg is permission_context


# ---------------------------------------------------------------------------
# TestRecoverableFailures
# ---------------------------------------------------------------------------


class TestRecoverableFailures:
    async def test_tool_error_becomes_error_result(self, captured_server):
        tool_manager = MagicMock()
        tool_manager.execute_tool = AsyncMock(side_effect=ValueError("boom"))
        bridge = _make_bridge(tool_manager)
        bridge.build_server([_EchoTool()])
        handler = _tool_by_name(captured_server, "echo_tool").handler

        result = await handler({})

        assert result["isError"] is True
        assert "boom" in result["content"][0]["text"]

    async def test_timeout_becomes_error_result(self, captured_server):
        tool_manager = MagicMock()

        async def _never_returns(*args, **kwargs):
            await asyncio.sleep(10)

        tool_manager.execute_tool = _never_returns
        bridge = _make_bridge(tool_manager, tool_timeout=0.01)
        bridge.build_server([_EchoTool()])
        handler = _tool_by_name(captured_server, "echo_tool").handler

        result = await handler({})

        assert result["isError"] is True
        assert "echo_tool" in result["content"][0]["text"]
        assert "timed out" in result["content"][0]["text"]

    async def test_hitl_denial_becomes_error_result(self, captured_server):
        tool_manager = MagicMock()
        tool_manager.execute_tool = AsyncMock(
            return_value=ToolResult(
                success=False,
                status="cancelled",
                error="Confirmation cancelled: user declined",
                result=None,
            )
        )
        bridge = _make_bridge(tool_manager)
        bridge.build_server([_ConfirmingTool()])
        handler = _tool_by_name(captured_server, "confirming_tool").handler

        result = await handler({})

        assert result["isError"] is True
        assert "declined" in result["content"][0]["text"]

    async def test_handler_never_raises(self, captured_server):
        tool_manager = MagicMock()
        tool_manager.execute_tool = AsyncMock(side_effect=RuntimeError("catastrophic"))
        bridge = _make_bridge(tool_manager)
        bridge.build_server([_EchoTool()])
        handler = _tool_by_name(captured_server, "echo_tool").handler

        # Must not raise.
        result = await handler({})
        assert result["isError"] is True


# ---------------------------------------------------------------------------
# TestLazyImport
# ---------------------------------------------------------------------------


class TestLazyImport:
    def test_module_imports_without_sdk(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "claude_agent_sdk", None)
        sys.modules.pop("parrot.clients.claude_agent_bridge", None)

        import parrot.clients.claude_agent_bridge as bridge_module

        assert bridge_module.ClaudeAgentToolBridge is not None

    def test_build_server_raises_import_error_with_hint_when_sdk_missing(self, monkeypatch):
        import parrot.clients.claude_agent_bridge as bridge_module

        monkeypatch.setitem(sys.modules, "claude_agent_sdk", None)
        bridge = bridge_module.ClaudeAgentToolBridge(MagicMock())

        with pytest.raises(ImportError) as exc_info:
            bridge.build_server([_EchoTool()])
        assert "pip install ai-parrot[claude-agent]" in str(exc_info.value)
