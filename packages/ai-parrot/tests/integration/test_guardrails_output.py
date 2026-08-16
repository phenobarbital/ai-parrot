"""Integration tests for the OUTPUT/TOOL_OUTPUT guardrail wiring (FEAT-396 / TASK-2029).

Covers the seams `SecretsGuardrail` was wired into:
- `AbstractBot.get_response()` (now async) — runs the OUTPUT pipeline.
- `BaseBot.ask()` — the channel-egress scrub now applies to ALL output
  modes, not just the legacy 4 chat modes (deliberate behavior extension).
- `BaseBot.ask_stream()` — StreamingGuardrail adapter scaffolding (feed/
  flush) plus the OUTPUT_STREAM `GuardrailPipeline` plus the final-AIMessage
  OUTPUT pipeline run.
- `AbstractTool.execute()`'s FEAT-252 hook — delegates through
  `_run_tool_output_guardrails()`, which resolves the tool's OWNING BOT's
  real TOOL_OUTPUT `GuardrailPipeline` (stamped by `ToolManager`, see
  `TestToolOutputPerBotResolution` below), falling back to the process-wide
  default `SecretsGuardrail` only when no pipeline was stamped. Behavioral
  parity for the default-policy path verified against the existing
  `tests/test_feat252_containment.py` suite, which stays green unmodified.
"""
from typing import ClassVar
from unittest.mock import MagicMock, patch

import pytest
from parrot.bots.basic import BasicBot
from parrot.bots.guardrails.base import (
    Guardrail,
    GuardrailAction,
    GuardrailResult,
    GuardrailStage,
)
from parrot.bots.guardrails.streaming import StreamingGuardrail
from parrot.models import AIMessage, CompletionUsage
from parrot.tools.abstract import AbstractTool


def _patched_bot(**kwargs) -> BasicBot:
    """Construct a BasicBot without loading the real pytector model."""
    with patch(
        "parrot.bots.guardrails.builtin.prompt_injection._get_shared_injection_detector"
    ) as mock_get_shared:
        mock_get_shared.return_value = MagicMock()
        return BasicBot(
            name="TestBot", injection_detection=False, **kwargs
        )


def _ai_message(output: str) -> AIMessage:
    return AIMessage(
        input="q",
        output=output,
        model="m",
        provider="p",
        usage=CompletionUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
    )


class TestGetResponseOutputPipeline:
    @pytest.mark.asyncio
    async def test_enable_redaction_true_scrubs_final_response(self):
        bot = _patched_bot(enable_redaction=True)
        assert bot._guardrail_pipelines[GuardrailStage.OUTPUT].has_guardrails

        response = _ai_message("API_KEY=sk-1234abcdefghij")
        # get_response() calls self.as_markdown() first; stub it out so this
        # test isolates the OUTPUT-pipeline behavior from formatting concerns.
        bot.as_markdown = MagicMock(return_value=response.output)

        result = await bot.get_response(response)

        assert "sk-1234abcdefghij" not in result.output
        assert "REDACTED" in result.output

    @pytest.mark.asyncio
    async def test_enable_redaction_false_leaves_response_untouched(self):
        bot = _patched_bot(enable_redaction=False)
        assert not bot._guardrail_pipelines[GuardrailStage.OUTPUT].has_guardrails

        response = _ai_message("API_KEY=sk-1234abcdefghij")
        bot.as_markdown = MagicMock(return_value=response.output)

        result = await bot.get_response(response)

        assert result.output == "API_KEY=sk-1234abcdefghij"



class TestAskOutputPipelineAllModes:
    @pytest.mark.asyncio
    async def test_run_output_pipeline_applies_regardless_of_mode(self):
        """The OUTPUT pipeline (via _run_output_pipeline) is mode-agnostic —
        the old channel-egress scrub only fired for 4 chat OutputModes; the
        unified pipeline call in ask() now runs unconditionally."""
        bot = _patched_bot(enable_redaction=True)
        response = _ai_message("PASSWORD=hunter2secret")

        result = await bot._run_output_pipeline(response, method="ask")

        assert "hunter2secret" not in result.output
        assert "REDACTED" in result.output

    @pytest.mark.asyncio
    async def test_structured_output_left_untouched(self):
        """Non-string `.output` (e.g. a formatted dict/DataFrame) is skipped,
        matching the pre-migration `isinstance(response.output, str)` guard."""
        bot = _patched_bot(enable_redaction=True)
        response = _ai_message("placeholder")
        response.output = {"content": "API_KEY=sk-1234abcdefghij"}

        result = await bot._run_output_pipeline(response, method="ask")

        assert result.output == {"content": "API_KEY=sk-1234abcdefghij"}

    @pytest.mark.asyncio
    async def test_empty_output_pipeline_is_noop(self):
        bot = _patched_bot(enable_redaction=False)
        response = _ai_message("API_KEY=sk-1234abcdefghij")

        result = await bot._run_output_pipeline(response, method="ask")

        assert result.output == "API_KEY=sk-1234abcdefghij"
        assert result is response  # zero-overhead short-circuit, same object


class TestStreamingGuardrailAdapterScaffolding:
    def test_no_adapters_registered_by_default(self):
        bot = _patched_bot()
        assert bot._streaming_guardrails == []

    @pytest.mark.asyncio
    async def test_feed_flush_passthrough_when_empty(self):
        bot = _patched_bot()
        text, blocked, flag_reports = await bot._feed_streaming_guardrails("hello")
        assert (text, blocked) == ("hello", False)
        assert flag_reports == {}
        assert bot._flush_streaming_guardrails() == ""

    @pytest.mark.asyncio
    async def test_registered_adapter_transforms_chunks(self):
        """Proves the StreamingGuardrail scaffolding (TASK-2024 contract)
        actually drives ask_stream's per-chunk loop end-to-end, even though
        no built-in guardrail implements it yet."""
        bot = _patched_bot()

        class UpperAdapter(StreamingGuardrail):
            def feed(self, chunk: str) -> str:
                return chunk.upper()

            def flush(self) -> str:
                return "[END]"

        bot._streaming_guardrails.append(UpperAdapter())

        text, blocked, _ = await bot._feed_streaming_guardrails("hello")
        assert (text, blocked) == ("HELLO", False)
        assert bot._flush_streaming_guardrails() == "[END]"

    @pytest.mark.asyncio
    async def test_withholding_adapter_can_buffer(self):
        bot = _patched_bot()

        class BufferingAdapter(StreamingGuardrail):
            def __init__(self):
                self._buf = []

            def feed(self, chunk: str) -> str:
                self._buf.append(chunk)
                return ""  # withhold everything until flush

            def flush(self) -> str:
                return "".join(self._buf)

        bot._streaming_guardrails.append(BufferingAdapter())

        text_a, blocked_a, _ = await bot._feed_streaming_guardrails("a")
        text_b, blocked_b, _ = await bot._feed_streaming_guardrails("b")
        assert (text_a, blocked_a) == ("", False)
        assert (text_b, blocked_b) == ("", False)
        assert bot._flush_streaming_guardrails() == "ab"

    @pytest.mark.asyncio
    async def test_custom_guardrail_registered_for_output_stream_actually_runs(self):
        """Regression test: a custom Guardrail declaring
        stages={GuardrailStage.OUTPUT_STREAM} must actually be invoked by
        ask_stream's chunk loop — the OUTPUT_STREAM GuardrailPipeline
        `build_pipelines_from_config` builds was previously constructed but
        never run anywhere (dead pipeline), fixed post-review."""
        from parrot.bots.guardrails.base import (
            Guardrail,
            GuardrailAction,
            GuardrailResult,
        )

        seen_chunks = []

        class RecordingStreamGuardrail(Guardrail):
            name = "recorder"
            stages: ClassVar[set] = {GuardrailStage.OUTPUT_STREAM}
            priority = 50
            on_error = "fail_open"

            async def check(self, content, ctx):
                seen_chunks.append(content)
                return GuardrailResult(action=GuardrailAction.TRANSFORM, content=content.upper())

        bot = _patched_bot(guardrails=[RecordingStreamGuardrail()])
        assert bot._guardrail_pipelines[GuardrailStage.OUTPUT_STREAM].has_guardrails

        text, blocked, _ = await bot._feed_streaming_guardrails("hello")
        assert blocked is False
        assert text == "HELLO"
        assert seen_chunks == ["hello"]

    @pytest.mark.asyncio
    async def test_custom_guardrail_can_block_the_stream(self):
        class BlockingStreamGuardrail(Guardrail):
            name = "blocker"
            stages: ClassVar[set] = {GuardrailStage.OUTPUT_STREAM}
            priority = 50
            on_error = "fail_closed"

            async def check(self, content, ctx):
                return GuardrailResult(action=GuardrailAction.BLOCK, reason="blocked_stream")

        bot = _patched_bot(guardrails=[BlockingStreamGuardrail()])

        text, blocked, flag_reports = await bot._feed_streaming_guardrails("hello")
        assert blocked is True
        assert text == ""
        assert flag_reports == {}


class TestSecretsToolOutputRegressionSuite:
    """The actual DEFAULT-policy tool-seam regression coverage lives in the
    existing, pre-migration `tests/test_feat252_containment.py` suite (18
    tests, unmodified) — it stays green against the FEAT-396 hook change,
    which is the behavioral-parity signal for that path. The PER-BOT
    resolution behavior (the actual fix — see `TestToolOutputPerBotResolution`
    below) has no pre-migration equivalent, since it didn't exist before."""

    def test_containment_suite_file_exists(self):
        from pathlib import Path

        suite = (
            Path(__file__).resolve().parents[1] / "test_feat252_containment.py"
        )
        assert suite.is_file()


class _EchoTool(AbstractTool):
    """Minimal tool returning whatever `result` was constructed with."""
    name = "echo_tool"
    description = "test"

    def __init__(self, result, **kwargs):
        super().__init__(**kwargs)
        self._result = result

    async def _execute(self, **kwargs):
        return self._result


class TestToolOutputPerBotResolution:
    """Regression tests for the TOOL_OUTPUT architecture gap found in code
    review: `ToolManager`/`AbstractTool` previously had no reference to the
    owning bot's TOOL_OUTPUT `GuardrailPipeline` at all — the FEAT-252 hook
    always used a hardcoded, process-wide default `SecretsGuardrail`
    (default `ScrubPolicy`), so a bot's `guardrails=[...]` TOOL_OUTPUT
    registrations (a custom Guardrail subclass, or a non-default
    `SecretsGuardrail` policy) were silently ignored — a direct AC
    violation ("a custom Guardrail subclass can be attached per bot via
    guardrails=[...] at any stage"). Fixed by stamping the real per-bot
    pipeline onto `ToolManager`/`AbstractTool`, mirroring the existing
    `enable_redaction` stamping chain exactly (`tools/manager.py`)."""

    @pytest.mark.asyncio
    async def test_custom_tool_output_guardrail_actually_runs(self):
        """A custom Guardrail registered via guardrails=[...] for
        TOOL_OUTPUT must be invoked when a bot executes a tool — not
        silently bypassed in favor of the hardcoded default."""
        seen = []

        class RecordingToolOutputGuardrail(Guardrail):
            name = "recorder"
            stages: ClassVar[set] = {GuardrailStage.TOOL_OUTPUT}
            priority = 20
            on_error = "fail_open"

            async def check(self, content, ctx):
                seen.append(content)
                return GuardrailResult(action=GuardrailAction.TRANSFORM, content=content.upper())

        bot = _patched_bot(guardrails=[RecordingToolOutputGuardrail()])
        tool = _EchoTool(result="hello world")
        bot.tool_manager.add_tool(tool)

        # NOTE: ToolManager.execute_tool() unwraps ToolResult and returns
        # `.result` directly (see tools/manager.py's `return out`).
        result = await bot.tool_manager.execute_tool("echo_tool", {})

        assert seen == ["hello world"]
        assert result == "HELLO WORLD"

    @pytest.mark.asyncio
    async def test_custom_tool_output_guardrail_can_block(self):
        class BlockingToolOutputGuardrail(Guardrail):
            name = "blocker"
            stages: ClassVar[set] = {GuardrailStage.TOOL_OUTPUT}
            priority = 20
            on_error = "fail_closed"

            async def check(self, content, ctx):
                return GuardrailResult(action=GuardrailAction.BLOCK, reason="blocked_tool_output")

        bot = _patched_bot(guardrails=[BlockingToolOutputGuardrail()])
        tool = _EchoTool(result="secret plan")
        bot.tool_manager.add_tool(tool)

        result = await bot.tool_manager.execute_tool("echo_tool", {})

        assert "secret plan" not in str(result)
        assert "blocked_tool_output" in str(result)

    @pytest.mark.asyncio
    async def test_non_string_result_uses_scrub_escape_hatch(self):
        """dict/list ToolResult.result values can't go through
        Guardrail.check(content: str) — SecretsGuardrail's scrub() escape
        hatch is used instead, resolved from the REAL per-bot pipeline
        (proving the fix applies to the non-string path too, not just the
        string BLOCK/TRANSFORM path above)."""
        bot = _patched_bot(enable_redaction=True)
        tool = _EchoTool(result={"api_key": "sk-1234abcdefghij", "ok": "plain"})
        bot.tool_manager.add_tool(tool)

        result = await bot.tool_manager.execute_tool("echo_tool", {})

        assert result["ok"] == "plain"
        assert "sk-1234abcdefghij" not in str(result["api_key"])

    @pytest.mark.asyncio
    async def test_no_bot_falls_back_to_default_singleton(self):
        """A tool with no `_tool_output_pipeline` stamped (not owned by a
        guardrails-aware bot) falls back to the pre-FEAT-396 default-policy
        scrubber — matching `test_feat252_containment.py`'s standalone-tool
        usage pattern exactly."""
        tool = _EchoTool(result="API_KEY=sk-1234abcdefghij")
        tool.enable_redaction = True
        assert tool._tool_output_pipeline is None

        result = await tool.execute()

        assert "sk-1234abcdefghij" not in str(result.result)


class TestGuardrailTelemetryReachesObserver:
    """Regression tests for the telemetry gap found in code review:
    `GuardrailPipeline.on_telemetry` (TASK-2025) was never actually
    supplied by any bot-wiring code, so no `GuardrailTelemetryEntry` ever
    reached a real FEAT-176 observer despite being recorded on every run —
    a direct AC violation ("Telemetry emits guardrail name/stage/action/
    duration/counts... via existing FEAT-176 observers"). Fixed by wiring
    `AbstractBot._on_guardrail_telemetry` as `on_telemetry` for every
    stage's pipeline and forwarding each entry as a `GuardrailActionEvent`
    (a new, additive FEAT-176 `LifecycleEvent` subclass — see
    `guardrails/events.py` — following the same pattern
    `parrot.eval.events` already established for another feature)."""

    @pytest.mark.asyncio
    async def test_output_stage_guardrail_run_emits_telemetry_event(self):
        import asyncio

        from parrot.bots.guardrails.events import GuardrailActionEvent

        bot = _patched_bot(enable_redaction=True)
        captured = []

        async def _capture(event):
            captured.append(event)

        bot.events.subscribe(GuardrailActionEvent, _capture)

        response = _ai_message("API_KEY=sk-1234abcdefghij")
        await bot._run_output_pipeline(response, method="ask")
        # emit_nowait schedules dispatch as a fire-and-forget task on the
        # running loop rather than awaiting it inline — yield control so
        # the scheduled task actually runs before asserting.
        await asyncio.sleep(0.05)

        assert len(captured) == 1
        event = captured[0]
        assert event.guardrail_name == "secrets"
        assert event.stage == "output"
        assert event.action == "transform"
        assert event.duration_ms >= 0
        assert event.agent_name == "TestBot"

    @pytest.mark.asyncio
    async def test_telemetry_never_carries_content(self):
        """Never a literal AC in the field set (structurally impossible —
        GuardrailActionEvent has no content-shaped field) — asserted
        explicitly for documentation/regression value."""
        from dataclasses import fields as dataclass_fields

        from parrot.bots.guardrails.events import GuardrailActionEvent

        field_names = {f.name for f in dataclass_fields(GuardrailActionEvent)}
        assert "content" not in field_names
        assert "text" not in field_names


class TestFlagReportsSurfaceAcrossAllStages:
    """Regression tests for the code-review CRITICAL finding: FLAG reports
    were only ever surfaced onto `AIMessage.metadata["guardrails"]` for the
    OUTPUT stage (via `_run_output_pipeline`) — INPUT, TOOL_OUTPUT and
    OUTPUT_STREAM FLAG reports were computed, timed and telemetered, then
    silently discarded, directly violating the acceptance criterion "FLAG
    reports appear under `AIMessage.metadata["guardrails"]`". Fixed via the
    shared `AbstractBot._merge_guardrail_reports()` helper (INPUT/
    OUTPUT_STREAM, called from `BaseBot.invoke`/`ask`/`ask_stream`) and by
    threading `PipelineOutcome.flag_reports` back out of
    `_run_tool_output_guardrails()` (TOOL_OUTPUT, called from
    `AbstractTool.execute()`)."""

    @pytest.mark.asyncio
    async def test_merge_guardrail_reports_helper_attaches_to_metadata(self):
        """Direct unit test of the shared merge helper every stage's
        seam now calls — the actual fix for the CRITICAL finding."""
        bot = _patched_bot()
        response = _ai_message("hello")

        bot._merge_guardrail_reports(response, {"moderation": {"flagged": True}})

        assert response.metadata["guardrails"] == {"moderation": {"flagged": True}}

    @pytest.mark.asyncio
    async def test_merge_guardrail_reports_is_noop_when_empty(self):
        bot = _patched_bot()
        response = _ai_message("hello")

        bot._merge_guardrail_reports(response, {})

        assert "guardrails" not in response.metadata

    @pytest.mark.asyncio
    async def test_input_stage_flag_report_computed_and_mergeable(self):
        """`_run_input_pipeline` outcome carries the FLAG report for a
        custom INPUT guardrail — proving the data `invoke`/`ask` merge
        onto the final response (via `_merge_guardrail_reports`) actually
        exists at the seam, closing the gap where it was previously
        computed and discarded."""

        class FlaggingInputGuardrail(Guardrail):
            name = "input_flagger"
            stages: ClassVar[set] = {GuardrailStage.INPUT}
            priority = 50
            on_error = "fail_open"

            async def check(self, content, ctx):
                return GuardrailResult(
                    action=GuardrailAction.FLAG,
                    report={"flagged_text_len": len(content)},
                )

        bot = _patched_bot(guardrails=[FlaggingInputGuardrail()])

        outcome = await bot._run_input_pipeline(
            question="hello world",
            user_id="u1",
            session_id="s1",
            method="ask",
        )

        assert outcome.flag_reports == {"input_flagger": {"flagged_text_len": 11}}

        response = _ai_message("hi")
        bot._merge_guardrail_reports(response, outcome.flag_reports)
        assert response.metadata["guardrails"] == {
            "input_flagger": {"flagged_text_len": 11}
        }

    @pytest.mark.asyncio
    async def test_output_stream_flag_report_returned_per_chunk(self):
        """`_feed_streaming_guardrails` now returns the OUTPUT_STREAM FLAG
        report alongside (text, blocked) instead of discarding it — the
        caller (`ask_stream`) accumulates these across chunks and merges
        them onto the final `AIMessage.metadata['guardrails']`."""

        class FlaggingStreamGuardrail(Guardrail):
            name = "stream_flagger"
            stages: ClassVar[set] = {GuardrailStage.OUTPUT_STREAM}
            priority = 50
            on_error = "fail_open"

            async def check(self, content, ctx):
                return GuardrailResult(
                    action=GuardrailAction.FLAG, report={"seen": content}
                )

        bot = _patched_bot(guardrails=[FlaggingStreamGuardrail()])

        text, blocked, flag_reports = await bot._feed_streaming_guardrails("hi")

        assert blocked is False
        assert text == "hi"
        assert flag_reports == {"stream_flagger": {"seen": "hi"}}

    @pytest.mark.asyncio
    async def test_tool_output_flag_report_reaches_result_metadata(self):
        """A FLAG-only TOOL_OUTPUT guardrail's report must reach
        `ToolResult.metadata['guardrails']` — previously
        `_run_tool_output_guardrails()` returned only the (unchanged)
        value, dropping `PipelineOutcome.flag_reports` entirely, so
        TOOL_OUTPUT FLAGs had no plumbing path to the caller at all."""

        class FlaggingToolOutputGuardrail(Guardrail):
            name = "tool_flagger"
            stages: ClassVar[set] = {GuardrailStage.TOOL_OUTPUT}
            priority = 50
            on_error = "fail_open"

            async def check(self, content, ctx):
                return GuardrailResult(
                    action=GuardrailAction.FLAG, report={"tool_name": ctx.tool_name}
                )

        bot = _patched_bot(guardrails=[FlaggingToolOutputGuardrail()])
        tool = _EchoTool(result="hello world")
        bot.tool_manager.add_tool(tool)

        # Call execute() directly (not tool_manager.execute_tool, which
        # unwraps to `.result`) so the full ToolResult.metadata is visible.
        tool_result = await tool.execute()

        assert tool_result.result == "hello world"
        assert tool_result.metadata["guardrails"] == {
            "tool_flagger": {"tool_name": "echo_tool"}
        }


class TestToolOutputFailClosedNonStringContent:
    """Regression tests for the code-review IMPORTANT finding:
    `on_error="fail_closed"` was not honored for non-string `ToolResult`
    fields (dict/list) — `_run_tool_output_guardrails()` routed those
    through each guardrail's `scrub()` escape hatch directly, with no
    error handling, so a raising `fail_closed` guardrail's exception
    propagated up to `AbstractTool.execute()`'s blanket
    `except Exception: # never let scrub errors break tool execution`
    and was silently swallowed as pass-through — unconditionally fail-open
    for non-string content regardless of the guardrail's declared policy."""

    @pytest.mark.asyncio
    async def test_fail_closed_scrub_error_blocks_dict_value(self):
        from parrot.bots.guardrails.pipeline import GuardrailPipeline
        from parrot.tools.abstract import _run_tool_output_guardrails

        class RaisingFailClosedGuardrail(Guardrail):
            name = "raiser"
            stages: ClassVar[set] = {GuardrailStage.TOOL_OUTPUT}
            priority = 50
            on_error = "fail_closed"

            async def check(self, content, ctx):  # pragma: no cover - unused here
                raise NotImplementedError

            def scrub(self, value, tool_name=None):
                raise RuntimeError("scrub blew up")

        pipeline = GuardrailPipeline()
        pipeline.add(RaisingFailClosedGuardrail())

        value, flag_reports = await _run_tool_output_guardrails(
            pipeline, {"secret": "value"}, "some_tool"
        )

        assert value == {"_blocked_by_guardrail": "raiser"}
        assert flag_reports == {}

    @pytest.mark.asyncio
    async def test_fail_closed_scrub_error_blocks_list_value(self):
        from parrot.bots.guardrails.pipeline import GuardrailPipeline
        from parrot.tools.abstract import _run_tool_output_guardrails

        class RaisingFailClosedGuardrail(Guardrail):
            name = "raiser"
            stages: ClassVar[set] = {GuardrailStage.TOOL_OUTPUT}
            priority = 50
            on_error = "fail_closed"

            async def check(self, content, ctx):  # pragma: no cover - unused here
                raise NotImplementedError

            def scrub(self, value, tool_name=None):
                raise RuntimeError("scrub blew up")

        pipeline = GuardrailPipeline()
        pipeline.add(RaisingFailClosedGuardrail())

        value, flag_reports = await _run_tool_output_guardrails(
            pipeline, ["a", "b"], "some_tool"
        )

        assert value == ["[content removed by guardrail: raiser]"]
        assert flag_reports == {}

    @pytest.mark.asyncio
    async def test_fail_open_scrub_error_leaves_value_unchanged(self):
        """Unchanged pre-existing behavior for `on_error="fail_open"`
        (the default, and `SecretsGuardrail`'s own policy) — a raising
        guardrail must NOT block; content passes through untouched."""
        from parrot.bots.guardrails.pipeline import GuardrailPipeline
        from parrot.tools.abstract import _run_tool_output_guardrails

        class RaisingFailOpenGuardrail(Guardrail):
            name = "raiser"
            stages: ClassVar[set] = {GuardrailStage.TOOL_OUTPUT}
            priority = 50
            on_error = "fail_open"

            async def check(self, content, ctx):  # pragma: no cover - unused here
                raise NotImplementedError

            def scrub(self, value, tool_name=None):
                raise RuntimeError("scrub blew up")

        pipeline = GuardrailPipeline()
        pipeline.add(RaisingFailOpenGuardrail())

        value, flag_reports = await _run_tool_output_guardrails(
            pipeline, {"secret": "value"}, "some_tool"
        )

        assert value == {"secret": "value"}
        assert flag_reports == {}
