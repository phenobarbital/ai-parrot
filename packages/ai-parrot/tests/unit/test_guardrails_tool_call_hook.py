"""Unit tests for the TOOL_CALL guardrail hook + bot wiring (FEAT-406 / TASK-2111).

Covers `ToolManager._tool_call_pipeline`, its pre-execution position ahead
of GrantGuard/ConfirmationGuard in `execute_tool()`, BLOCK -> forbidden
`ToolResult` translation, the no-pipeline regression path, and the
`AbstractBot` wiring seam that stamps the bot's real TOOL_CALL pipeline
onto the tool manager (mirrors `_tool_output_pipeline`, verified against
`tests/integration/test_guardrails_output.py::TestToolOutputPerBotResolution`).
"""
from typing import ClassVar
from unittest.mock import MagicMock, patch

import pytest

from parrot.bots.guardrails.base import (
    Guardrail,
    GuardrailAction,
    GuardrailContext,
    GuardrailResult,
    GuardrailStage,
)
from parrot.bots.guardrails.pipeline import GuardrailPipeline
from parrot.tools.abstract import AbstractTool, ToolResult
from parrot.tools.manager import ToolManager

# ── Stubs ──────────────────────────────────────────────────────────────────────


class _RecordingTool(AbstractTool):
    """Minimal AbstractTool that records execution count."""

    name = "recording_tool"
    description = "A tool that records how many times it executed."

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._exec_count = 0

    async def _execute(self, **kwargs) -> ToolResult:
        self._exec_count += 1
        return ToolResult(success=True, status="success", result="executed")


class _PassGuardrail(Guardrail):
    name = "pass_through"
    stages: ClassVar[set] = {GuardrailStage.TOOL_CALL}
    priority = 10
    on_error = "fail_closed"

    async def check(self, content: str, ctx: GuardrailContext) -> GuardrailResult:
        return GuardrailResult(action=GuardrailAction.PASS)


class _BlockGuardrail(Guardrail):
    name = "blocker"
    stages: ClassVar[set] = {GuardrailStage.TOOL_CALL}
    priority = 10
    on_error = "fail_closed"

    def __init__(self):
        self.calls: list[str] = []

    async def check(self, content: str, ctx: GuardrailContext) -> GuardrailResult:
        self.calls.append(content)
        return GuardrailResult(
            action=GuardrailAction.BLOCK,
            reason="policy:business_hours",
            report={"message": "Access denied outside business hours."},
        )


def _make_manager() -> ToolManager:
    return ToolManager()


def _pipeline_with(*guardrails: Guardrail) -> GuardrailPipeline:
    pipeline = GuardrailPipeline()
    for g in guardrails:
        pipeline.add(g)
    return pipeline


# ── Test: TOOL_CALL pipeline runs before grant/confirmation ─────────────────────


class TestToolCallPipelineOrder:
    @pytest.mark.asyncio
    async def test_execute_tool_runs_tool_call_pipeline_first(self):
        """TOOL_CALL pipeline evaluates BEFORE GrantGuard/ConfirmationGuard."""
        mgr = _make_manager()
        tool = _RecordingTool()
        mgr._tools[tool.name] = tool
        mgr._tool_call_pipeline = _pipeline_with(_PassGuardrail())

        call_order: list[str] = []

        class _OrderTrackingGrantGuard:
            async def authorize(self, *, tool, parameters, permission_context=None):
                call_order.append("grant")
                from parrot.auth.grants import GuardDecision
                return GuardDecision(allowed=True, reason="ok")

        class _OrderTrackingConfirmGuard:
            async def confirm(self, *, tool, parameters, permission_context=None):
                call_order.append("confirm")
                from parrot.auth.confirmation import ConfirmationDecision
                return ConfirmationDecision(
                    allowed=True, status="confirmed", reason="ok", parameters=parameters
                )

        # Wrap the pipeline's run() to record ordering too.
        original_run = mgr._tool_call_pipeline.run

        async def _tracking_run(content, ctx):
            call_order.append("tool_call")
            return await original_run(content, ctx)

        mgr._tool_call_pipeline.run = _tracking_run
        mgr._grant_guard = _OrderTrackingGrantGuard()
        mgr._confirmation_guard = _OrderTrackingConfirmGuard()

        await mgr.execute_tool(tool.name, {})

        assert call_order == ["tool_call", "grant", "confirm"]
        assert tool._exec_count == 1


# ── Test: BLOCK translates to forbidden ToolResult ──────────────────────────────


class TestToolCallPipelineBlock:
    @pytest.mark.asyncio
    async def test_block_translates_to_forbidden_toolresult(self):
        mgr = _make_manager()
        tool = _RecordingTool()
        mgr._tools[tool.name] = tool
        blocker = _BlockGuardrail()
        mgr._tool_call_pipeline = _pipeline_with(blocker)

        result = await mgr.execute_tool(tool.name, {"x": 1})

        assert isinstance(result, ToolResult)
        assert result.success is False
        assert result.status == "forbidden"
        assert result.error == "Access denied outside business hours."
        assert tool._exec_count == 0
        # Telemetry/content passed to the guardrail must never carry arguments.
        assert blocker.calls == [f"tool_call:{tool.name}"]


# ── Test: no pipeline -> regression-safe (identical to today) ──────────────────


class TestNoToolCallPipelineRegression:
    @pytest.mark.asyncio
    async def test_no_pipeline_path_unchanged(self):
        mgr = _make_manager()
        tool = _RecordingTool()
        mgr._tools[tool.name] = tool
        assert mgr._tool_call_pipeline is None

        # execute_tool() unwraps a successful ToolResult to its `.result`
        # (see tools/manager.py's `out = result.result`) — same behavior
        # documented in tests/integration/test_guardrails_output.py.
        result = await mgr.execute_tool(tool.name, {})

        assert tool._exec_count == 1
        assert result == "executed"

    @pytest.mark.asyncio
    async def test_empty_pipeline_path_unchanged(self):
        """A stamped-but-empty pipeline (has_guardrails=False) is also a no-op."""
        mgr = _make_manager()
        tool = _RecordingTool()
        mgr._tools[tool.name] = tool
        mgr._tool_call_pipeline = GuardrailPipeline()
        assert not mgr._tool_call_pipeline.has_guardrails

        result = await mgr.execute_tool(tool.name, {})

        assert tool._exec_count == 1
        assert result == "executed"


# ── Test: bot wiring stamps the real TOOL_CALL pipeline ─────────────────────────


def _patched_bot(**kwargs):
    """Construct a BasicBot without loading the real pytector model
    (mirrors tests/integration/test_guardrails_output.py's helper)."""
    from parrot.bots.basic import BasicBot

    with patch(
        "parrot.bots.guardrails.builtin.prompt_injection._get_shared_injection_detector"
    ) as mock_get_shared:
        mock_get_shared.return_value = MagicMock()
        return BasicBot(name="TestBot", injection_detection=False, **kwargs)


class TestBotWiringStampsToolCallPipeline:
    @pytest.mark.asyncio
    async def test_bot_wiring_stamps_tool_call_pipeline(self):
        """tool_manager._tool_call_pipeline is the bot's real TOOL_CALL pipeline."""
        bot = _patched_bot()

        assert bot.tool_manager._tool_call_pipeline is bot._guardrail_pipelines[GuardrailStage.TOOL_CALL]

    @pytest.mark.asyncio
    async def test_custom_tool_call_guardrail_instance_actually_runs(self):
        """A PBACToolCallGuardrail-shaped instance passed via guardrails=[...]
        lands in the TOOL_CALL pipeline and actually runs on dispatch —
        proving the existing generic guardrails=[...] machinery (unchanged
        since TASK-2109/2110) is sufficient bot wiring; no PBAC-specific
        construction code is needed in AbstractBot itself."""
        blocker = _BlockGuardrail()
        bot = _patched_bot(guardrails=[blocker])
        tool = _RecordingTool()
        bot.tool_manager.add_tool(tool)

        assert bot._guardrail_pipelines[GuardrailStage.TOOL_CALL].has_guardrails

        result = await bot.tool_manager.execute_tool(tool.name, {})

        assert "Access denied outside business hours." in str(result)
        assert tool._exec_count == 0

    @pytest.mark.asyncio
    async def test_pbac_not_registered_without_engine(self):
        """No PBAC guardrail passed (e.g. setup_pbac() degraded to
        (None, None, None), so the caller never constructs/passes one) ->
        TOOL_CALL pipeline stays empty; tools execute unaffected."""
        bot = _patched_bot()

        assert not bot._guardrail_pipelines[GuardrailStage.TOOL_CALL].has_guardrails

        tool = _RecordingTool()
        bot.tool_manager.add_tool(tool)
        await bot.tool_manager.execute_tool(tool.name, {})

        assert tool._exec_count == 1
