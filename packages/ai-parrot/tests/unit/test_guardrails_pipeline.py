"""Unit tests for the guardrails pipeline (FEAT-396 / TASK-2025)."""
from typing import ClassVar

import pytest
from parrot.bots.guardrails.base import (
    Guardrail,
    GuardrailAction,
    GuardrailContext,
    GuardrailResult,
    GuardrailStage,
)
from parrot.bots.guardrails.pipeline import GuardrailPipeline


# Stub guardrails for testing
class PassGuardrail(Guardrail):
    name = "pass_guard"
    stages: ClassVar[set] = {GuardrailStage.INPUT}
    priority = 100
    on_error = "fail_open"

    async def check(self, content, ctx):
        return GuardrailResult(action=GuardrailAction.PASS)


class TransformGuardrail(Guardrail):
    name = "transform_guard"
    stages: ClassVar[set] = {GuardrailStage.INPUT}
    priority = 50
    on_error = "fail_open"

    async def check(self, content, ctx):
        return GuardrailResult(action=GuardrailAction.TRANSFORM, content=content.upper())


class BlockGuardrail(Guardrail):
    name = "block_guard"
    stages: ClassVar[set] = {GuardrailStage.INPUT}
    priority = 10
    on_error = "fail_closed"

    async def check(self, content, ctx):
        return GuardrailResult(action=GuardrailAction.BLOCK, reason="blocked")


class FlagGuardrail(Guardrail):
    name = "flag_guard"
    stages: ClassVar[set] = {GuardrailStage.OUTPUT}
    priority = 200
    on_error = "fail_open"

    async def check(self, content, ctx):
        return GuardrailResult(action=GuardrailAction.FLAG, report={"score": 0.9})


class RaisingGuardrail(Guardrail):
    name = "raises"
    stages: ClassVar[set] = {GuardrailStage.INPUT}
    priority = 50
    on_error = "fail_open"

    async def check(self, content, ctx):
        raise RuntimeError("boom")


@pytest.fixture
def ctx():
    return GuardrailContext(stage=GuardrailStage.INPUT, agent_name="test")


@pytest.mark.asyncio
class TestPipelineOrdering:
    async def test_priority_order(self, ctx):
        pipeline = GuardrailPipeline()
        pipeline.add(PassGuardrail())
        pipeline.add(TransformGuardrail())
        outcome = await pipeline.run("hello", ctx)
        assert outcome.content == "HELLO"

    async def test_stable_order_within_band(self, ctx):
        # Two same-priority guardrails should both run, in insertion order.
        seen = []

        class First(Guardrail):
            name = "first"
            stages: ClassVar[set] = {GuardrailStage.INPUT}
            priority = 50
            on_error = "fail_open"

            async def check(self, content, c):
                seen.append("first")
                return GuardrailResult(action=GuardrailAction.PASS)

        class Second(Guardrail):
            name = "second"
            stages: ClassVar[set] = {GuardrailStage.INPUT}
            priority = 50
            on_error = "fail_open"

            async def check(self, content, c):
                seen.append("second")
                return GuardrailResult(action=GuardrailAction.PASS)

        pipeline = GuardrailPipeline()
        pipeline.add(First())
        pipeline.add(Second())
        await pipeline.run("hello", ctx)
        assert seen == ["first", "second"]


@pytest.mark.asyncio
class TestPipelineBlock:
    async def test_block_shortcircuits(self, ctx):
        pipeline = GuardrailPipeline()
        pipeline.add(BlockGuardrail())
        pipeline.add(TransformGuardrail())
        outcome = await pipeline.run("hello", ctx)
        assert outcome.blocked is True
        assert outcome.content != "HELLO"
        assert outcome.content is None
        assert outcome.reason == "blocked"


@pytest.mark.asyncio
class TestPipelineErrorContract:
    async def test_fail_open_continues(self, ctx):
        pipeline = GuardrailPipeline()
        pipeline.add(RaisingGuardrail())
        pipeline.add(PassGuardrail())
        outcome = await pipeline.run("hello", ctx)
        assert outcome.blocked is False

    async def test_fail_closed_blocks(self, ctx):
        g = RaisingGuardrail()
        g.on_error = "fail_closed"
        pipeline = GuardrailPipeline()
        pipeline.add(g)
        outcome = await pipeline.run("hello", ctx)
        assert outcome.blocked is True
        assert outcome.reason == "guardrail_error:raises"


@pytest.mark.asyncio
class TestPipelineFlagAccumulation:
    async def test_flags_accumulate(self):
        ctx = GuardrailContext(stage=GuardrailStage.OUTPUT, agent_name="test")
        pipeline = GuardrailPipeline()
        pipeline.add(FlagGuardrail())
        outcome = await pipeline.run("text", ctx)
        assert "flag_guard" in outcome.flag_reports
        assert outcome.flag_reports["flag_guard"]["score"] == 0.9

    async def test_multiple_flags_distinct_names(self):
        class FlagA(Guardrail):
            name = "flag_a"
            stages: ClassVar[set] = {GuardrailStage.OUTPUT}
            priority = 200
            on_error = "fail_open"

            async def check(self, content, ctx):
                return GuardrailResult(action=GuardrailAction.FLAG, report={"a": 1})

        class FlagB(Guardrail):
            name = "flag_b"
            stages: ClassVar[set] = {GuardrailStage.OUTPUT}
            priority = 201
            on_error = "fail_open"

            async def check(self, content, ctx):
                return GuardrailResult(action=GuardrailAction.FLAG, report={"b": 2})

        ctx = GuardrailContext(stage=GuardrailStage.OUTPUT, agent_name="test")
        pipeline = GuardrailPipeline()
        pipeline.add(FlagA())
        pipeline.add(FlagB())
        outcome = await pipeline.run("text", ctx)
        assert outcome.flag_reports == {"flag_a": {"a": 1}, "flag_b": {"b": 2}}


@pytest.mark.asyncio
class TestPipelineIdempotency:
    """`GuardrailPipeline` itself does NOT memoize outcomes across `run()`
    calls (a pipeline-level (stage, content) cache was removed post-review
    — see pipeline.py's module docstring: it silently suppressed
    side-effecting guardrails like PromptInjectionGuardrail's security
    audit logging and LegacyPipelineGuardrail's wrapped LLM call on repeat
    identical input, which is a correctness/security regression, not an
    optimization). Outcome idempotency (same input -> same output) is
    still achievable when a guardrail's own transform is naturally
    idempotent (e.g. `str.upper()`) or implements its own content-marker
    check (e.g. `SecretsGuardrail` + `_already_scrubbed`,
    `tests/unit/test_guardrails_secrets.py::test_idempotent`)."""

    async def test_double_run_idempotent(self, ctx):
        """Naturally-idempotent TRANSFORM (str.upper()) produces the same
        content on a second run — without requiring pipeline-level caching."""
        pipeline = GuardrailPipeline()
        pipeline.add(TransformGuardrail())
        outcome1 = await pipeline.run("hello", ctx)
        outcome2 = await pipeline.run(outcome1.content, ctx)
        assert outcome1.content == outcome2.content

    async def test_repeat_same_content_reinvokes_check_every_run(self, ctx):
        """Regression test for the removed stamp cache: a guardrail with
        side effects (here, simulated via a call counter — in production
        this is PromptInjectionGuardrail's SecurityEventLogger audit trail
        or LegacyPipelineGuardrail's wrapped LLM call) MUST run on every
        `run()` call, even for identical repeat content — the pipeline
        must never silently skip check() to "optimize" a repeat input."""
        calls = 0

        class CountingTransform(Guardrail):
            name = "counting"
            stages: ClassVar[set] = {GuardrailStage.INPUT}
            priority = 50
            on_error = "fail_open"

            async def check(self, content, c):
                nonlocal calls
                calls += 1
                return GuardrailResult(action=GuardrailAction.TRANSFORM, content=content.upper())

        pipeline = GuardrailPipeline()
        pipeline.add(CountingTransform())
        outcome1 = await pipeline.run("hello", ctx)
        outcome2 = await pipeline.run("hello", ctx)
        assert calls == 2
        assert outcome1.content == outcome2.content == "HELLO"
        assert outcome1.content == outcome2.content == "HELLO"


@pytest.mark.asyncio
class TestPipelineEmpty:
    async def test_empty_no_overhead(self, ctx):
        pipeline = GuardrailPipeline()
        assert not pipeline.has_guardrails
        outcome = await pipeline.run("hello", ctx)
        assert outcome.content == "hello"
        assert outcome.blocked is False
        assert outcome.telemetry == []


@pytest.mark.asyncio
class TestPipelineTelemetry:
    async def test_telemetry_recorded_per_guardrail(self, ctx):
        pipeline = GuardrailPipeline()
        pipeline.add(PassGuardrail())
        pipeline.add(TransformGuardrail())
        outcome = await pipeline.run("hello", ctx)
        names = [t.name for t in outcome.telemetry]
        assert names == ["transform_guard", "pass_guard"]
        for entry in outcome.telemetry:
            assert entry.duration_ms >= 0
            assert entry.stage == GuardrailStage.INPUT

    async def test_on_telemetry_callback_invoked(self, ctx):
        received = []
        pipeline = GuardrailPipeline(on_telemetry=received.append)
        pipeline.add(PassGuardrail())
        await pipeline.run("hello", ctx)
        assert len(received) == 1
        assert received[0].name == "pass_guard"

    async def test_on_telemetry_callback_error_does_not_break_run(self, ctx):
        def boom(entry):
            raise RuntimeError("telemetry sink down")

        pipeline = GuardrailPipeline(on_telemetry=boom)
        pipeline.add(PassGuardrail())
        outcome = await pipeline.run("hello", ctx)
        assert outcome.blocked is False
