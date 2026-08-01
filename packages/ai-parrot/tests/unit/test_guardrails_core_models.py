"""Unit tests for the guardrails core models (FEAT-396 / TASK-2024)."""
from typing import ClassVar

import pytest
from parrot.bots.guardrails.base import (
    Guardrail,
    GuardrailAction,
    GuardrailContext,
    GuardrailResult,
    GuardrailStage,
)
from parrot.bots.guardrails.streaming import StreamingGuardrail


class TestGuardrailStage:
    def test_enum_values(self):
        assert GuardrailStage.INPUT == "input"
        assert GuardrailStage.TOOL_OUTPUT == "tool_output"
        assert GuardrailStage.OUTPUT == "output"
        assert GuardrailStage.OUTPUT_STREAM == "output_stream"


class TestGuardrailAction:
    def test_enum_values(self):
        assert GuardrailAction.PASS == "pass"
        assert GuardrailAction.TRANSFORM == "transform"
        assert GuardrailAction.FLAG == "flag"
        assert GuardrailAction.BLOCK == "block"


class TestGuardrailResult:
    def test_pass_result(self):
        r = GuardrailResult(action=GuardrailAction.PASS)
        assert r.content is None
        assert r.report is None
        assert r.reason is None

    def test_transform_result(self):
        r = GuardrailResult(action=GuardrailAction.TRANSFORM, content="cleaned")
        assert r.content == "cleaned"

    def test_flag_result(self):
        r = GuardrailResult(action=GuardrailAction.FLAG, report={"score": 0.5})
        assert r.report["score"] == 0.5

    def test_block_result(self):
        r = GuardrailResult(action=GuardrailAction.BLOCK, reason="injection_detected")
        assert r.reason == "injection_detected"


class TestGuardrailContext:
    def test_minimal_context(self):
        ctx = GuardrailContext(stage=GuardrailStage.INPUT, agent_name="test")
        assert ctx.method == ""
        assert ctx.tool_name is None
        assert ctx.user_id is None
        assert ctx.session_id is None
        assert ctx.extras == {}

    def test_full_context(self):
        ctx = GuardrailContext(
            stage=GuardrailStage.TOOL_OUTPUT,
            agent_name="test-agent",
            user_id="u1",
            session_id="s1",
            method="ask",
            tool_name="search",
            extras={"foo": "bar"},
        )
        assert ctx.tool_name == "search"
        assert ctx.extras == {"foo": "bar"}


class TestGuardrailABC:
    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            Guardrail()

    def test_concrete_subclass_works(self):
        class AlwaysPass(Guardrail):
            name = "always_pass"
            stages: ClassVar[set] = {GuardrailStage.INPUT}
            priority = 0
            on_error = "fail_open"

            async def check(self, content, ctx):
                return GuardrailResult(action=GuardrailAction.PASS)

        g = AlwaysPass()
        assert g.name == "always_pass"
        assert GuardrailStage.INPUT in g.stages


class TestStreamingGuardrailABC:
    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            StreamingGuardrail()

    def test_concrete_subclass_works(self):
        class PassThrough(StreamingGuardrail):
            def feed(self, chunk: str) -> str:
                return chunk

            def flush(self) -> str:
                return ""

        adapter = PassThrough()
        assert adapter.feed("hello") == "hello"
        assert adapter.flush() == ""


@pytest.mark.asyncio
class TestGuardrailCheckIsAsync:
    async def test_check_returns_result(self):
        class Noop(Guardrail):
            name = "noop"
            stages: ClassVar[set] = {GuardrailStage.OUTPUT}
            priority = 200
            on_error = "fail_open"

            async def check(self, content, ctx):
                return GuardrailResult(action=GuardrailAction.PASS)

        g = Noop()
        ctx = GuardrailContext(stage=GuardrailStage.OUTPUT, agent_name="a")
        result = await g.check("hello", ctx)
        assert result.action == GuardrailAction.PASS
