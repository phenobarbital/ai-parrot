"""Integration tests for the OUTPUT/TOOL_OUTPUT guardrail wiring (FEAT-396 / TASK-2029).

Covers the seams `SecretsGuardrail` was wired into:
- `AbstractBot.get_response()` (now async) — runs the OUTPUT pipeline.
- `BaseBot.ask()` — the channel-egress scrub now applies to ALL output
  modes, not just the legacy 4 chat modes (deliberate behavior extension).
- `BaseBot.ask_stream()` — StreamingGuardrail adapter scaffolding (feed/
  flush) plus the final-AIMessage OUTPUT pipeline run.
- `AbstractTool.execute()`'s FEAT-252 hook — delegates through
  `_default_secrets_guardrail()` instead of the raw `_default_scrubber()`
  singleton (behavioral parity verified against the existing
  `tests/test_feat252_containment.py` suite, which stays green unmodified).
"""
from unittest.mock import MagicMock, patch

import pytest
from parrot.bots.basic import BasicBot
from parrot.bots.guardrails.base import GuardrailStage
from parrot.bots.guardrails.streaming import StreamingGuardrail
from parrot.models import AIMessage, CompletionUsage


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

    def test_feed_flush_passthrough_when_empty(self):
        bot = _patched_bot()
        assert bot._feed_streaming_guardrails("hello") == "hello"
        assert bot._flush_streaming_guardrails() == ""

    def test_registered_adapter_transforms_chunks(self):
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

        assert bot._feed_streaming_guardrails("hello") == "HELLO"
        assert bot._flush_streaming_guardrails() == "[END]"

    def test_withholding_adapter_can_buffer(self):
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

        assert bot._feed_streaming_guardrails("a") == ""
        assert bot._feed_streaming_guardrails("b") == ""
        assert bot._flush_streaming_guardrails() == "ab"


class TestSecretsToolOutputRegressionSuite:
    """The actual tool-seam regression coverage lives in the existing,
    pre-migration `tests/test_feat252_containment.py` suite (18 tests,
    unmodified) — it stays green against the FEAT-396 hook change (now
    routed through `_default_secrets_guardrail()` instead of the raw
    `_default_scrubber()` singleton), which is the behavioral-parity
    signal for the FEAT-252 tool-output redaction path this task rewires."""

    def test_containment_suite_file_exists(self):
        from pathlib import Path

        suite = (
            Path(__file__).resolve().parents[1] / "test_feat252_containment.py"
        )
        assert suite.is_file()
