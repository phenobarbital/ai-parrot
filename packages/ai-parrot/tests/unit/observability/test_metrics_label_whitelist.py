"""FEAT-783 AC-9 — SDD ids never become metric labels."""

from __future__ import annotations

import pytest

from parrot.core.events.lifecycle import TraceContext
from parrot.core.events.lifecycle.events import AfterClientCallEvent
from parrot.observability.attribution import UsageAttribution
from parrot.observability.context import usage_attribution
from parrot.observability.subscribers.metrics import MetricsSubscriber

# feat_id is allowed as the bounded ``parrot.feat_id`` label (TASK-4996).
FORBIDDEN = {"attempt_uid", "execution_id", "task_id", "parrot.attempt_uid", "parrot.execution_id", "parrot.task_id"}


class _Instrument:
    """Capture metric API calls without exporting an OTel data point."""

    def __init__(self) -> None:
        self.attributes: list[dict[str, object]] = []

    def add(self, value: object, *, attributes: dict[str, object]) -> None:
        """Capture counter attributes."""
        self.attributes.append(attributes)

    def record(self, value: object, *, attributes: dict[str, object]) -> None:
        """Capture histogram attributes."""
        self.attributes.append(attributes)


@pytest.mark.asyncio
async def test_attributed_event_adds_no_unbounded_labels() -> None:
    """AC-9: attributed calls do not expose per-task/attempt metric labels."""
    subscriber = MetricsSubscriber()
    duration = _Instrument()
    tokens = _Instrument()
    cost = _Instrument()
    subscriber._client_op_duration = duration
    subscriber._client_token_usage = tokens
    subscriber._client_cost_total = cost

    attribution = UsageAttribution(
        feat_id="FEAT-783",
        task_id="TASK-4985",
        attempt_uid="attempt-unique-per-dispatch",
        execution_id="execution-unique-per-attempt",
    )
    with usage_attribution("run-783", "development", attribution):
        event = AfterClientCallEvent(
            trace_context=TraceContext.new_root(),
            client_name="openai",
            model="gpt-4o-mini",
            duration_ms=10.0,
            input_tokens=11,
            output_tokens=7,
        )

    await subscriber._on_client_after(event)

    attributes = [attrs for instrument in (duration, tokens, cost) for attrs in instrument.attributes]
    assert attributes
    assert all(not (set(attrs) & FORBIDDEN) for attrs in attributes)
