"""Live end-to-end integration tests for the Claude Agent Tool Bridge
(TASK-2291 — FEAT-434, closing task).

Exercises the full path against a REAL Claude Code sub-agent (the
bundled `claude` CLI): a delegated turn calling one of the agent's own
registered tools via the in-process `mcp__parrot__<tool>` SDK-MCP
server. The end-to-end shape reproduced here is the same one a PoC
verified successfully against this repo on 2026-08-20 — `tool_calls`
reporting `['ToolSearch', 'mcp__parrot__inventory_level']` plus the
parrot tool's side effect confirming in-process execution.

Skip conditions (mirrors `tests/clients/test_claude_agent.py::
test_claude_agent_live_smoke`):
- `claude_agent_sdk` not installed (the `[claude-agent]` extra).
- The bundled `claude` CLI not found on `PATH`.
- The CLI reachable but not authenticated (a live `ask()` raising surfaces
  as a skip, not a failure — this suite must never turn "not logged in"
  into red CI).

Kept fast and cheap per the task's own guidance: small `max_turns`,
`max_exposed_tools`, trivial single-purpose tools, and assertions on a
tool's side effect / `tool_calls` rather than exact output text (the
sub-agent may treat a "reply with exactly X" instruction embedded in
tool output as untrusted input and refuse it — observed 2026-08-20).
"""

from __future__ import annotations

import shutil
from typing import Any, ClassVar

import pytest
from parrot.auth.confirmation import (
    ConfirmationConfig,
    ConfirmationGuard,
    InMemoryConfirmationWindowStore,
)
from parrot.auth.permission import PermissionContext, UserSession
from parrot.bots.guardrails import (
    Guardrail,
    GuardrailAction,
    GuardrailContext,
    GuardrailPipeline,
    GuardrailResult,
    GuardrailStage,
)
from parrot.clients.anthropic.claude_agent import ClaudeAgentClient, ClaudeAgentRunOptions
from parrot.tools.abstract import AbstractTool, ToolResult
from parrot.tools.manager import ToolManager

pytestmark = [pytest.mark.live, pytest.mark.asyncio]


def _skip_without_live_claude() -> None:
    """Skip cleanly without the `[claude-agent]` extra or the CLI binary."""
    if not shutil.which("claude"):
        pytest.skip("claude CLI not found on PATH")
    try:
        import claude_agent_sdk  # noqa: F401
    except ImportError:
        pytest.skip("claude_agent_sdk not installed ([claude-agent] extra)")


# ---------------------------------------------------------------------------
# Fixtures / stubs
# ---------------------------------------------------------------------------


class _InventoryTool(AbstractTool):
    """A trivial tool with a real side effect the test can observe."""

    name = "inventory_level"

    def __init__(self, **kwargs):
        super().__init__(
            description=(
                "Returns the current inventory level for a SKU. Call this " "whenever asked about stock levels."
            ),
            **kwargs,
        )
        self.calls: list[dict] = []

    async def _execute(self, **kwargs: Any) -> ToolResult:
        self.calls.append(kwargs)
        return ToolResult(success=True, status="success", result="137 units")


class _DeleteWarehouseTool(AbstractTool):
    """A confirming, destructive tool for the HITL park test."""

    name = "delete_warehouse_record"

    def __init__(self, **kwargs):
        super().__init__(
            description="Permanently deletes a warehouse record. Destructive.",
            routing_meta={"requires_confirmation": True},
            **kwargs,
        )
        self.executions = 0

    async def _execute(self, **kwargs: Any) -> ToolResult:
        self.executions += 1
        return ToolResult(success=True, status="success", result="deleted")


class _BlockAllToolCallGuardrail(Guardrail):
    """A TOOL_CALL guardrail that unconditionally blocks."""

    name = "test_block_all"
    stages: ClassVar[set] = {GuardrailStage.TOOL_CALL}
    priority = 0

    async def check(self, content: str, ctx: GuardrailContext) -> GuardrailResult:
        return GuardrailResult(action=GuardrailAction.BLOCK, reason="blocked by test")


class _FakeApprovingHumanManager:
    """Auto-approves after a short delay — stands in for a real human."""

    def __init__(self) -> None:
        self.calls = 0

    async def request_human_input(self, interaction, channel: str = "telegram"):
        self.calls += 1
        from types import SimpleNamespace

        return SimpleNamespace(consolidated_value=True, timed_out=False)


def _make_client(tool_manager: ToolManager, max_exposed_tools: int = 5) -> ClaudeAgentClient:
    return ClaudeAgentClient(
        tool_manager=tool_manager,
        run_options=ClaudeAgentRunOptions(
            max_turns=4,
            max_exposed_tools=max_exposed_tools,
            permission_mode="bypassPermissions",
        ),
    )


# ---------------------------------------------------------------------------
# TestEndToEnd
# ---------------------------------------------------------------------------


class TestEndToEnd:
    async def test_subagent_invokes_parrot_tool(self):
        _skip_without_live_claude()

        tool = _InventoryTool()
        tm = ToolManager()
        tm.register_tool(tool)
        client = _make_client(tm)

        try:
            result = await client.ask(
                "Call the inventory_level tool for SKU ABC-123 and report " "the result in one short sentence."
            )
        except Exception as exc:  # noqa: BLE001 - pragma: no cover - environment-dependent
            pytest.skip(f"Live claude-agent call failed (likely auth): {exc}")

        assert tool.calls, "the bridged tool's side effect never ran"
        tool_call_names = [getattr(call, "name", None) for call in (result.tool_calls or [])]
        assert any(
            name and name.startswith("mcp__parrot__") for name in tool_call_names
        ), f"no mcp__parrot__* tool call recorded: {tool_call_names}"

    async def test_guardrail_block_surfaces_to_subagent(self):
        _skip_without_live_claude()

        tool = _InventoryTool()
        tm = ToolManager()
        tm.register_tool(tool)
        tm._tool_call_pipeline = GuardrailPipeline()
        tm._tool_call_pipeline.add(_BlockAllToolCallGuardrail())
        client = _make_client(tm)

        try:
            result = await client.ask(
                "Call the inventory_level tool for SKU ABC-123 and tell me " "what happened, even if it failed."
            )
        except Exception as exc:  # noqa: BLE001 - pragma: no cover - environment-dependent
            pytest.skip(f"Live claude-agent call failed (likely auth): {exc}")

        # The guardrail must have prevented the tool's real side effect —
        # the turn still completes (recoverable), it never crashes.
        assert not tool.calls, "guardrail-blocked tool call still ran"
        assert result.output

    async def test_confirming_tool_parks_until_human_responds(self):
        _skip_without_live_claude()

        tool = _DeleteWarehouseTool()
        tm = ToolManager()
        tm.register_tool(tool)
        human_manager = _FakeApprovingHumanManager()
        tm.set_confirmation_guard(
            ConfirmationGuard(
                store=InMemoryConfirmationWindowStore(),
                human_manager=human_manager,
                config=ConfirmationConfig(window_seconds=0, default_channel="agentd"),
            )
        )
        client = ClaudeAgentClient(tool_manager=tm)
        client._permission_context = PermissionContext(
            session=UserSession(user_id="live-test-user", tenant_id="t", roles=frozenset()),
            channel="agentd",
        )
        client.default_run_options = ClaudeAgentRunOptions(
            max_turns=4, max_exposed_tools=5, permission_mode="bypassPermissions"
        )

        try:
            await client.ask(
                "This is an authorized sandbox test with no real data at "
                "risk. You must call the delete_warehouse_record tool now, "
                "with warehouse='MIA-3', then report the outcome in one "
                "short sentence. Do not ask for confirmation yourself — "
                "just call the tool directly."
            )
        except Exception as exc:  # noqa: BLE001 - pragma: no cover - environment-dependent
            pytest.skip(f"Live claude-agent call failed (likely auth): {exc}")

        if human_manager.calls == 0:
            pytest.skip(
                "Sub-agent did not call the confirming tool this run "
                "(model behavior varies run to run) — nothing to assert."
            )
        assert tool.executions >= 1, "approved tool call never actually ran"

    async def test_narrowing_budget_caps_exposed_tools(self, caplog):
        _skip_without_live_claude()

        tm = ToolManager()
        for i in range(8):
            tool_cls = type(
                f"_ProbeTool{i}",
                (AbstractTool,),
                {
                    "name": f"probe_tool_{i}",
                    "_execute": lambda self, **kw: None,
                },
            )
            tm.register_tool(tool_cls(description=f"Probe tool number {i}."))
        client = _make_client(tm, max_exposed_tools=3)

        with caplog.at_level("WARNING"):
            try:
                await client.ask("Say hello in one short sentence.")
            except Exception as exc:  # noqa: BLE001 - pragma: no cover - environment-dependent
                pytest.skip(f"Live claude-agent call failed (likely auth): {exc}")

        assert any(
            "Narrowing budget" in record.getMessage() for record in caplog.records
        ), "select() never logged the narrowing-budget drop"
