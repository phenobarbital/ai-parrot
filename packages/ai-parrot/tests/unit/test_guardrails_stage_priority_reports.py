"""FEAT-761 TASK-4825 — per-stage priority + orthogonal reports."""
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


class _Recorder(Guardrail):
    """Stub guardrail that records call order and returns a fixed result."""

    stages: ClassVar[set[GuardrailStage]] = {GuardrailStage.INPUT, GuardrailStage.OUTPUT}

    def __init__(
        self,
        name: str,
        priority: int | dict[GuardrailStage, int],
        result: GuardrailResult,
        log: list[str],
    ) -> None:
        """Initialize a recorder with its fixed pipeline outcome."""
        self.name = name
        self.priority = priority
        self._result = result
        self._log = log

    async def check(self, content: str, ctx: GuardrailContext) -> GuardrailResult:
        """Record execution and return the configured result."""
        self._log.append(self.name)
        return self._result


def _ctx(stage: GuardrailStage) -> GuardrailContext:
    """Build a minimal context for a pipeline stage."""
    return GuardrailContext(stage=stage, agent_name="t")


def _pass() -> GuardrailResult:
    """Build a PASS result for recorder setup."""
    return GuardrailResult(action=GuardrailAction.PASS)


@pytest.mark.asyncio
async def test_scalar_priority_order_is_unchanged() -> None:
    """Scalar priorities retain the historical ascending execution order."""
    log: list[str] = []
    pipeline = GuardrailPipeline()
    pipeline.add(_Recorder("later", 20, _pass(), log))
    pipeline.add(_Recorder("earlier", 10, _pass(), log))

    await pipeline.run("content", _ctx(GuardrailStage.INPUT))

    assert log == ["earlier", "later"]
    assert [guardrail.name for guardrail in pipeline.guardrails] == ["earlier", "later"]


@pytest.mark.asyncio
async def test_mapping_priority_orders_by_stage() -> None:
    """A mapping priority resolves separately for INPUT and OUTPUT runs."""
    log: list[str] = []
    pipeline = GuardrailPipeline()
    mapped = _Recorder(
        "mapped",
        {GuardrailStage.INPUT: 12, GuardrailStage.OUTPUT: 220},
        _pass(),
        log,
    )
    scalar = _Recorder("scalar", 100, _pass(), log)
    pipeline.add(mapped)
    pipeline.add(scalar)

    await pipeline.run("content", _ctx(GuardrailStage.INPUT))
    assert log == ["mapped", "scalar"]

    log.clear()
    await pipeline.run("content", _ctx(GuardrailStage.OUTPUT))
    assert log == ["scalar", "mapped"]
    assert mapped.priority_for(None) == 12
    assert mapped.priority_for(GuardrailStage.TOOL_OUTPUT) == 12


@pytest.mark.asyncio
async def test_stage_priority_ties_preserve_registration_order() -> None:
    """Stable sorting preserves registration order for equal stage priorities."""
    log: list[str] = []
    pipeline = GuardrailPipeline()
    pipeline.add(_Recorder("first", {GuardrailStage.INPUT: 5}, _pass(), log))
    pipeline.add(_Recorder("second", {GuardrailStage.INPUT: 5}, _pass(), log))

    await pipeline.run("content", _ctx(GuardrailStage.INPUT))

    assert log == ["first", "second"]


@pytest.mark.asyncio
async def test_add_invalidates_cached_stage_order() -> None:
    """Adding a guardrail rebuilds the cached order for an already-run stage."""
    log: list[str] = []
    pipeline = GuardrailPipeline()
    pipeline.add(_Recorder("later", 20, _pass(), log))
    await pipeline.run("content", _ctx(GuardrailStage.INPUT))

    log.clear()
    pipeline.add(_Recorder("earlier", 10, _pass(), log))
    await pipeline.run("content", _ctx(GuardrailStage.INPUT))

    assert log == ["earlier", "later"]


@pytest.mark.asyncio
async def test_transform_report_is_surfaced() -> None:
    """TRANSFORM results retain their truthy non-content reports."""
    pipeline = GuardrailPipeline()
    pipeline.add(
        _Recorder(
            "transform",
            10,
            GuardrailResult(action=GuardrailAction.TRANSFORM, content="safe", report={"wrapped": True}),
            [],
        )
    )

    outcome = await pipeline.run("content", _ctx(GuardrailStage.INPUT))

    assert outcome.content == "safe"
    assert outcome.flag_reports == {"transform": {"wrapped": True}}


@pytest.mark.asyncio
async def test_pass_report_is_surfaced() -> None:
    """PASS results retain their truthy non-content reports."""
    pipeline = GuardrailPipeline()
    pipeline.add(_Recorder("pass", 10, GuardrailResult(action=GuardrailAction.PASS, report={"seen": 1}), []))

    outcome = await pipeline.run("content", _ctx(GuardrailStage.INPUT))

    assert outcome.content == "content"
    assert outcome.flag_reports == {"pass": {"seen": 1}}


@pytest.mark.asyncio
async def test_transform_without_report_adds_no_report() -> None:
    """TRANSFORM results without a report leave report metadata unchanged."""
    pipeline = GuardrailPipeline()
    pipeline.add(_Recorder("transform", 10, GuardrailResult(action=GuardrailAction.TRANSFORM, content="safe"), []))

    outcome = await pipeline.run("content", _ctx(GuardrailStage.INPUT))

    assert outcome.flag_reports == {}


@pytest.mark.asyncio
async def test_block_and_flag_report_behavior_is_unchanged() -> None:
    """BLOCK and FLAG reports retain the existing pipeline behavior."""
    block_pipeline = GuardrailPipeline()
    block_pipeline.add(
        _Recorder("block", 10, GuardrailResult(action=GuardrailAction.BLOCK, report={"count": 1}), [])
    )
    block_outcome = await block_pipeline.run("content", _ctx(GuardrailStage.INPUT))

    flag_pipeline = GuardrailPipeline()
    flag_pipeline.add(_Recorder("flag", 10, GuardrailResult(action=GuardrailAction.FLAG), []))
    flag_outcome = await flag_pipeline.run("content", _ctx(GuardrailStage.INPUT))

    assert block_outcome.blocked is True
    assert block_outcome.flag_reports == {"block": {"count": 1}}
    assert flag_outcome.flag_reports == {"flag": {}}


def test_requires_system_prompt_defaults_to_false() -> None:
    """Existing guardrails inherit the opt-in prompt requirement default."""
    assert _Recorder.requires_system_prompt is False
