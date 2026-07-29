"""Unit tests for UsageRecordingSubscriber."""

from __future__ import annotations

import pytest

from parrot.core.events.lifecycle.events import AfterClientCallEvent
from navigator_eventbus.lifecycle.registry import EventRegistry
from navigator_eventbus.lifecycle.trace import TraceContext
from parrot.observability.cost.calculator import (
    CostCalculator,
    _reset_pricing_cache_for_tests,
)
from parrot.observability.recorders.base import AbstractLogger
from parrot.observability.recorders.models import UsageRecord
from parrot.observability.recorders.subscriber import UsageRecordingSubscriber


class _CapturingRecorder(AbstractLogger):
    name = "capture"

    def __init__(self) -> None:
        self.records: list[UsageRecord] = []

    async def record(self, record: UsageRecord) -> None:
        self.records.append(record)


class _ExplodingRecorder(AbstractLogger):
    name = "boom"

    async def record(self, record: UsageRecord) -> None:
        raise RuntimeError("backend down")


def _after(model: str = "gpt-4o-mini", it: int = 100, ot: int = 50) -> AfterClientCallEvent:
    return AfterClientCallEvent(
        trace_context=TraceContext.new_root(),
        client_name="openai", model=model, duration_ms=42.0,
        input_tokens=it, output_tokens=ot, finish_reason="stop",
        source_type="client", source_name="openai",
    )


@pytest.mark.asyncio
async def test_builds_record_with_cost_and_resolved_provider() -> None:
    """The subscriber computes cost and resolves provider via gen_ai mapping."""
    _reset_pricing_cache_for_tests()
    cap = _CapturingRecorder()
    sub = UsageRecordingSubscriber(recorders=[cap], cost_calculator=CostCalculator())
    reg = EventRegistry(forward_to_global=False)
    reg.add_provider(sub)

    await reg.emit(_after())

    assert len(cap.records) == 1
    rec = cap.records[0]
    assert rec.provider == "openai"
    assert rec.model == "gpt-4o-mini"
    assert rec.input_tokens == 100 and rec.output_tokens == 50
    # Cost must match the shared CostCalculator for the bundled model.
    expected = CostCalculator().cost_usd(
        provider="openai", model="gpt-4o-mini", input_tokens=100, output_tokens=50
    )
    assert rec.cost_usd == expected
    assert rec.cumulative_cost_usd == expected


@pytest.mark.asyncio
async def test_cumulative_cost_accumulates() -> None:
    """Cumulative cost grows across successive calls."""
    _reset_pricing_cache_for_tests()
    cap = _CapturingRecorder()
    sub = UsageRecordingSubscriber(recorders=[cap], cost_calculator=CostCalculator())
    reg = EventRegistry(forward_to_global=False)
    reg.add_provider(sub)

    await reg.emit(_after())
    await reg.emit(_after())

    assert len(cap.records) == 2
    first, second = cap.records
    assert second.cumulative_cost_usd == pytest.approx(
        (first.cost_usd or 0) + (second.cost_usd or 0)
    )


@pytest.mark.asyncio
async def test_fan_out_isolates_failing_recorder() -> None:
    """A recorder raising does not prevent others from receiving the record."""
    _reset_pricing_cache_for_tests()
    cap = _CapturingRecorder()
    sub = UsageRecordingSubscriber(
        recorders=[_ExplodingRecorder(), cap], cost_calculator=None
    )
    reg = EventRegistry(forward_to_global=False)
    reg.add_provider(sub)

    await reg.emit(_after())

    assert len(cap.records) == 1
    assert cap.records[0].cost_usd is None  # no calculator → no cost


@pytest.mark.asyncio
async def test_no_calculator_means_no_cost() -> None:
    """Without a CostCalculator, cost fields stay None."""
    cap = _CapturingRecorder()
    sub = UsageRecordingSubscriber(recorders=[cap], cost_calculator=None)
    reg = EventRegistry(forward_to_global=False)
    reg.add_provider(sub)

    await reg.emit(_after())

    assert cap.records[0].cost_usd is None
    assert cap.records[0].cumulative_cost_usd is None
