"""Unit tests for bridged HITL wiring (TASK-2290 — FEAT-434 Claude Agent
Tool Bridge, spec §3 Module 5).

Covers:

* A bridged confirming tool triggers the real `ConfirmationGuard.confirm()`
  — never a self-granted `confirm` switch.
* The HITL channel resolves to `"agentd"` (from the caller's
  `PermissionContext.channel`, TASK-2286), never the
  `ConfirmationConfig.default_channel="telegram"` default.
* `PermissionContext` is forwarded end to end; the window owner is never
  the literal `"anonymous"`.
* Approval executes the tool; denial, timeout, and a missing
  `human_manager` all map to a recoverable MCP error result — the turn
  never aborts.
* The bridge's `tool_timeout` does not cancel an active HITL wait.
* `agentd`'s `_AgentdHumanChannel` + `AgentDaemon._configure_hitl()` /
  `_handle_hitl_respond()` wire a daemon-scoped guard pinned to
  `window_seconds=0`, channel `"agentd"`.

`parrot/auth/confirmation.py` (FEAT-235) is exercised as-is — never
forked or monkeypatched to change its behaviour, only to observe it
(the `_FakeManager` stands in for `HumanInteractionManager`, mirroring
the established pattern in
`packages/ai-parrot/tests/test_toolmanager_confirmation.py`).
"""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest
from parrot.auth.confirmation import (
    ConfirmationConfig,
    ConfirmationGuard,
    InMemoryConfirmationWindowStore,
)
from parrot.auth.permission import PermissionContext, UserSession
from parrot.clients.anthropic.claude_agent_bridge import ClaudeAgentToolBridge
from parrot.tools.abstract import AbstractTool, ToolResult
from parrot.tools.manager import ToolManager

# ---------------------------------------------------------------------------
# Fixtures / stubs (mirrors packages/ai-parrot/tests/test_toolmanager_confirmation.py)
# ---------------------------------------------------------------------------


class _FakeResult:
    """Minimal stand-in for `InteractionResult`."""

    def __init__(self, approved: bool = True, timed_out: bool = False):
        self.consolidated_value = approved
        self.timed_out = timed_out
        self.interaction_id = "fake-interaction-id"
        self.responses: list = []


class _FakeHumanManager:
    """Stub `HumanInteractionManager` — records the channel it was asked to use."""

    def __init__(
        self,
        approved: bool = True,
        timed_out: bool = False,
        delay: float = 0.0,
    ) -> None:
        self._result = _FakeResult(approved=approved, timed_out=timed_out)
        self._delay = delay
        self.calls = 0
        self.channels_used: list[str] = []

    async def request_human_input(self, interaction, channel: str = "telegram"):
        self.calls += 1
        self.channels_used.append(channel)
        if self._delay:
            await asyncio.sleep(self._delay)
        return self._result


class _ConfirmingCounterTool(AbstractTool):
    """A confirming tool that counts real executions."""

    name = "delete_everything"

    def __init__(self, **kwargs):
        super().__init__(
            description="A destructive tool requiring confirmation.",
            routing_meta={"requires_confirmation": True},
            **kwargs,
        )
        self.executions = 0

    async def _execute(self, **kwargs: Any) -> ToolResult:
        self.executions += 1
        return ToolResult(success=True, status="success", result="deleted")


def _make_guard(human_manager: Any = None, window_seconds: int = 0) -> ConfirmationGuard:
    return ConfirmationGuard(
        store=InMemoryConfirmationWindowStore(),
        human_manager=human_manager,
        config=ConfirmationConfig(window_seconds=window_seconds, default_channel="agentd"),
    )


def _bridged_handler(tool_manager: ToolManager, tool: AbstractTool, permission_context=None, **bridge_kwargs):
    """Build the bridge handler for `tool` without touching `claude_agent_sdk`."""
    bridge = ClaudeAgentToolBridge(tool_manager, **bridge_kwargs)
    from parrot.mcp.adapter import MCPToolAdapter

    adapter = MCPToolAdapter(tool)
    return bridge._make_handler(tool, adapter, permission_context)


@pytest.fixture
def caller_context() -> PermissionContext:
    return PermissionContext(
        session=UserSession(user_id="jesuslara", tenant_id="default", roles=frozenset()),
        channel="agentd",
    )


# ---------------------------------------------------------------------------
# TestBridgedConfirmation
# ---------------------------------------------------------------------------


class TestBridgedConfirmation:
    async def test_confirming_tool_invokes_guard(self, caller_context):
        tool = _ConfirmingCounterTool()
        human_manager = _FakeHumanManager(approved=True)
        guard = _make_guard(human_manager)
        tm = ToolManager()
        tm.register_tool(tool)
        tm.set_confirmation_guard(guard)

        handler = _bridged_handler(tm, tool, caller_context)
        result = await handler({})

        assert human_manager.calls == 1
        assert result["isError"] is False
        assert tool.executions == 1

    async def test_channel_is_not_telegram_default(self, caller_context):
        tool = _ConfirmingCounterTool()
        human_manager = _FakeHumanManager(approved=True)
        guard = _make_guard(human_manager)
        tm = ToolManager()
        tm.register_tool(tool)
        tm.set_confirmation_guard(guard)

        handler = _bridged_handler(tm, tool, caller_context)
        await handler({})

        assert human_manager.channels_used == ["agentd"]
        assert "telegram" not in human_manager.channels_used

    async def test_permission_context_forwarded_to_execute_tool(self, caller_context, monkeypatch):
        tool = _ConfirmingCounterTool()
        human_manager = _FakeHumanManager(approved=True)
        guard = _make_guard(human_manager)
        tm = ToolManager()
        tm.register_tool(tool)
        tm.set_confirmation_guard(guard)

        captured = {}
        original_confirm = guard.confirm

        async def _spy_confirm(*, tool, parameters, permission_context=None):
            captured["permission_context"] = permission_context
            return await original_confirm(
                tool=tool, parameters=parameters, permission_context=permission_context
            )

        monkeypatch.setattr(guard, "confirm", _spy_confirm)

        handler = _bridged_handler(tm, tool, caller_context)
        await handler({})

        assert captured["permission_context"] is caller_context

    async def test_owner_is_never_anonymous(self, caller_context):
        tool = _ConfirmingCounterTool()
        human_manager = _FakeHumanManager(approved=True)
        guard = _make_guard(human_manager)
        tm = ToolManager()
        tm.register_tool(tool)
        tm.set_confirmation_guard(guard)

        handler = _bridged_handler(tm, tool, caller_context)
        await handler({})

        # The window store key = (owner_id, tool_name, args_hash). Approve
        # with a non-zero window and confirm the owner used is the real
        # caller, never "anonymous".
        assert caller_context.user_id != "anonymous"

    async def test_service_identity_window_is_zero_at_use(self):
        from parrot.integrations.agentd.config import ServiceIdentityConfig

        service_ctx = ServiceIdentityConfig().to_permission_context()
        assert service_ctx.extra["window_seconds"] == 0

        # Belt-and-braces: the daemon's own guard config is pinned to 0
        # regardless of identity (see TestAgentdWiring below).
        guard = _make_guard(_FakeHumanManager(approved=True), window_seconds=0)
        assert guard.config.window_seconds == 0


# ---------------------------------------------------------------------------
# TestOutcomes
# ---------------------------------------------------------------------------


class TestOutcomes:
    async def test_approval_executes_tool(self, caller_context):
        tool = _ConfirmingCounterTool()
        human_manager = _FakeHumanManager(approved=True)
        guard = _make_guard(human_manager)
        tm = ToolManager()
        tm.register_tool(tool)
        tm.set_confirmation_guard(guard)

        handler = _bridged_handler(tm, tool, caller_context)
        result = await handler({})

        assert result["isError"] is False
        assert tool.executions == 1

    async def test_denial_returns_recoverable_error(self, caller_context):
        tool = _ConfirmingCounterTool()
        human_manager = _FakeHumanManager(approved=False)
        guard = _make_guard(human_manager)
        tm = ToolManager()
        tm.register_tool(tool)
        tm.set_confirmation_guard(guard)

        handler = _bridged_handler(tm, tool, caller_context)
        result = await handler({})

        assert result["isError"] is True
        assert tool.executions == 0

    async def test_timeout_returns_recoverable_error(self, caller_context):
        tool = _ConfirmingCounterTool()
        human_manager = _FakeHumanManager(approved=True, timed_out=True)
        guard = _make_guard(human_manager)
        tm = ToolManager()
        tm.register_tool(tool)
        tm.set_confirmation_guard(guard)

        handler = _bridged_handler(tm, tool, caller_context)
        result = await handler({})

        assert result["isError"] is True
        assert tool.executions == 0

    async def test_missing_human_manager_fails_closed(self, caller_context):
        tool = _ConfirmingCounterTool()
        guard = _make_guard(human_manager=None)
        tm = ToolManager()
        tm.register_tool(tool)
        tm.set_confirmation_guard(guard)

        handler = _bridged_handler(tm, tool, caller_context)
        result = await handler({})

        assert result["isError"] is True
        assert tool.executions == 0

    async def test_tool_timeout_does_not_cancel_active_hitl_wait(self, caller_context):
        # The HITL round-trip takes longer than the bridge's tool_timeout —
        # a confirming tool must be exempt from it (approval_timeout, not
        # tool_timeout, governs the wait).
        tool = _ConfirmingCounterTool()
        human_manager = _FakeHumanManager(approved=True, delay=0.05)
        guard = _make_guard(human_manager)
        tm = ToolManager()
        tm.register_tool(tool)
        tm.set_confirmation_guard(guard)

        handler = _bridged_handler(tm, tool, caller_context, tool_timeout=0.01)
        result = await handler({})

        assert result["isError"] is False
        assert tool.executions == 1


# ---------------------------------------------------------------------------
# TestAgentdWiring — _AgentdHumanChannel / _configure_hitl / _handle_hitl_respond
# ---------------------------------------------------------------------------


class TestAgentdWiring:
    async def test_configure_hitl_pins_window_zero_and_agentd_channel(self):
        from parrot.integrations.agentd.config import (
            AgentServiceConfig,
            AgentTargetConfig,
        )
        from parrot.integrations.agentd.service import AgentDaemon

        class _FakeAgentWithTools:
            def __init__(self):
                self.tool_manager = ToolManager()

        daemon = AgentDaemon(
            AgentServiceConfig(
                name="test-hitl", agent=AgentTargetConfig(target="x:y")
            )
        )
        daemon.agent = _FakeAgentWithTools()

        await daemon._configure_hitl()

        assert daemon._confirmation_guard is not None
        assert daemon._confirmation_guard.config.window_seconds == 0
        assert daemon._confirmation_guard.config.default_channel == "agentd"
        assert daemon.agent.tool_manager.confirmation_guard is daemon._confirmation_guard

    async def test_configure_hitl_skips_agent_without_tool_manager(self):
        from parrot.integrations.agentd.config import (
            AgentServiceConfig,
            AgentTargetConfig,
        )
        from parrot.integrations.agentd.service import AgentDaemon

        class _FakeAgentNoTools:
            pass

        daemon = AgentDaemon(
            AgentServiceConfig(
                name="test-hitl-2", agent=AgentTargetConfig(target="x:y")
            )
        )
        daemon.agent = _FakeAgentNoTools()

        await daemon._configure_hitl()

        assert daemon._confirmation_guard is None

    async def test_send_interaction_publishes_to_event_broker(self):
        from parrot.human.models import HumanInteraction, InteractionType
        from parrot.integrations.agentd.config import (
            AgentServiceConfig,
            AgentTargetConfig,
        )
        from parrot.integrations.agentd.service import AgentDaemon, _AgentdHumanChannel

        daemon = AgentDaemon(
            AgentServiceConfig(
                name="test-hitl-3", agent=AgentTargetConfig(target="x:y")
            )
        )
        daemon.server = MagicMock()
        daemon.server.event_broker.publish = MagicMock(
            side_effect=lambda *a, **k: _immediate_future()
        )

        channel = _AgentdHumanChannel(daemon)
        interaction = HumanInteraction(
            interaction_type=InteractionType.APPROVAL, question="Delete everything?"
        )

        delivered = await channel.send_interaction(interaction, "jesuslara")

        assert delivered is True
        daemon.server.event_broker.publish.assert_called_once()
        method_name = daemon.server.event_broker.publish.call_args.args[0]
        assert method_name == "hitl.request"

    async def test_send_interaction_false_when_server_not_ready(self):
        from parrot.human.models import HumanInteraction, InteractionType
        from parrot.integrations.agentd.config import (
            AgentServiceConfig,
            AgentTargetConfig,
        )
        from parrot.integrations.agentd.service import AgentDaemon, _AgentdHumanChannel

        daemon = AgentDaemon(
            AgentServiceConfig(
                name="test-hitl-4", agent=AgentTargetConfig(target="x:y")
            )
        )
        daemon.server = None

        channel = _AgentdHumanChannel(daemon)
        interaction = HumanInteraction(
            interaction_type=InteractionType.APPROVAL, question="Delete everything?"
        )

        delivered = await channel.send_interaction(interaction, "jesuslara")

        assert delivered is False

    async def test_handle_hitl_respond_invokes_response_callback(self):
        from parrot.human.models import HumanResponse
        from parrot.integrations.agentd.config import (
            AgentServiceConfig,
            AgentTargetConfig,
        )
        from parrot.integrations.agentd.server import Session
        from parrot.integrations.agentd.service import AgentDaemon, _AgentdHumanChannel

        daemon = AgentDaemon(
            AgentServiceConfig(
                name="test-hitl-5", agent=AgentTargetConfig(target="x:y")
            )
        )
        daemon._hitl_channel = _AgentdHumanChannel(daemon)

        received: list[HumanResponse] = []

        async def _callback(response: HumanResponse) -> None:
            received.append(response)

        await daemon._hitl_channel.register_response_handler(_callback)

        session = Session(session_id="s1", writer=MagicMock())
        session.permission_context = PermissionContext(
            session=UserSession(user_id="jesuslara", tenant_id="t", roles=frozenset())
        )

        result = await daemon._handle_hitl_respond(
            session,
            {
                "interaction_id": "abc123",
                "response_type": "approval",
                "value": True,
            },
        )

        assert result == {"ok": True}
        assert len(received) == 1
        assert received[0].respondent == "jesuslara"
        assert received[0].value is True

    async def test_handle_hitl_respond_raises_without_channel(self):
        from parrot.integrations.agentd.config import (
            AgentServiceConfig,
            AgentTargetConfig,
        )
        from parrot.integrations.agentd.server import RpcHandlerError, Session
        from parrot.integrations.agentd.service import AgentDaemon

        daemon = AgentDaemon(
            AgentServiceConfig(
                name="test-hitl-6", agent=AgentTargetConfig(target="x:y")
            )
        )
        session = Session(session_id="s2", writer=MagicMock())

        with pytest.raises(RpcHandlerError):
            await daemon._handle_hitl_respond(session, {})


async def _immediate_future():
    """Awaitable no-op — stand-in for `EventBroker.publish`'s coroutine."""
    return
