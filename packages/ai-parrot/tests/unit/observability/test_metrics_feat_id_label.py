"""FEAT-783 AC-15 — parrot.feat_id label + policy-applied cost on metrics."""

from __future__ import annotations

import pytest

from parrot.core.events.lifecycle import TraceContext
from parrot.core.events.lifecycle.events import AfterClientCallEvent, ClientCallFailedEvent
from parrot.observability.attribution import UsageAttribution
from parrot.observability.context import usage_attribution
from parrot.observability.subscribers.metrics import MetricsSubscriber

FORBIDDEN = {"attempt_uid", "execution_id", "task_id", "parrot.attempt_uid", "parrot.execution_id", "parrot.task_id"}


class _Instrument:
    """Capture metric API calls."""

    def __init__(self) -> None:
        self.calls: list[tuple[object, dict[str, object]]] = []

    def add(self, value: object, *, attributes: dict[str, object]) -> None:
        """Capture counter call."""
        self.calls.append((value, attributes))

    def record(self, value: object, *, attributes: dict[str, object]) -> None:
        """Capture histogram call."""
        self.calls.append((value, attributes))


def _wired() -> tuple[MetricsSubscriber, _Instrument, _Instrument, _Instrument, _Instrument]:
    sub = MetricsSubscriber()
    dur, tok, cost, err = _Instrument(), _Instrument(), _Instrument(), _Instrument()
    sub._client_op_duration = dur
    sub._client_token_usage = tok
    sub._client_cost_total = cost
    sub._client_error_count = err
    return sub, dur, tok, cost, err


def _after(**kw: object) -> AfterClientCallEvent:
    return AfterClientCallEvent(
        trace_context=TraceContext.new_root(), client_name="openai", model="gpt-4o-mini",
        duration_ms=10.0, input_tokens=11, output_tokens=7, cost_usd=0.5, **kw,
    )


@pytest.mark.asyncio
async def test_after_call_metrics_carry_feat_id() -> None:
    """Attributed events label token/cost/duration with the feature; unattributed use 'none'."""
    sub, dur, tok, cost, _ = _wired()
    with usage_attribution("run", "development", UsageAttribution(feat_id="FEAT-1", task_id="TASK-1")):
        attributed = _after()
    await sub._on_client_after(attributed)
    for inst in (dur, tok, cost):
        assert inst.calls
        assert all(a["parrot.feat_id"] == "FEAT-1" for _, a in inst.calls)

    sub, dur, tok, cost, _ = _wired()
    await sub._on_client_after(_after())
    for inst in (dur, tok, cost):
        assert inst.calls
        assert all(a["parrot.feat_id"] == "none" for _, a in inst.calls)


@pytest.mark.asyncio
async def test_failure_metric_carries_feat_id() -> None:
    """The error counter is labelled with the feature too."""
    sub, _, _, _, err = _wired()
    with usage_attribution("run", "development", UsageAttribution(feat_id="FEAT-2")):
        event = ClientCallFailedEvent(
            trace_context=TraceContext.new_root(), client_name="openai", model="m",
            duration_ms=1.0, error_type="APIError", error_message="boom",
        )
    await sub._on_client_fail(event)
    assert err.calls[0][1]["parrot.feat_id"] == "FEAT-2"


@pytest.mark.asyncio
async def test_no_task_or_attempt_labels() -> None:
    """AC-9: only feat_id is added; task/attempt/execution ids are never labels."""
    sub, dur, tok, cost, _ = _wired()
    attribution = UsageAttribution(feat_id="FEAT-1", task_id="TASK-1", attempt_uid="a", execution_id="e")
    with usage_attribution("run", "development", attribution):
        event = _after()
    await sub._on_client_after(event)
    for inst in (dur, tok, cost):
        assert all(not (set(a) & FORBIDDEN) for _, a in inst.calls)


@pytest.mark.asyncio
async def test_subscription_cost_counter_adds_zero() -> None:
    """Subscription seats add 0.0 to the cost counter; billed seats add the real cost."""
    sub, _, _, cost, _ = _wired()
    await sub._on_client_after(_after(pricing_policy="subscription"))
    assert [v for v, _ in cost.calls] == [0.0]

    sub, _, _, cost, _ = _wired()
    await sub._on_client_after(_after())
    assert [v for v, _ in cost.calls] == [0.5]
