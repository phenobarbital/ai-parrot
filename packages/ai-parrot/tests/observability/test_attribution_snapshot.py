"""FEAT-783 TASK-4983 — UsageAttribution + event snapshot."""

import pytest
from pydantic import ValidationError

from parrot.core.events.lifecycle import TraceContext
from parrot.core.events.lifecycle.events import AfterClientCallEvent, ClientCallFailedEvent
from parrot.observability.attribution import UsageAttribution
from parrot.observability.context import current_usage_attribution, usage_attribution


def test_attribution_is_frozen_and_rejects_extras() -> None:
    """The attribution model accepts its optional schema only and is immutable."""
    attribution = UsageAttribution()

    with pytest.raises(ValidationError):
        attribution.feat_id = "FEAT-783"
    with pytest.raises(ValidationError):
        UsageAttribution(bogus=1)


def test_event_snapshots_attribution_at_construction() -> None:
    """Successful events retain the attribution bound at construction time."""
    attribution = UsageAttribution(feat_id="FEAT-783", task_id="TASK-4983")

    with usage_attribution("run-1", attribution=attribution):
        event = AfterClientCallEvent(trace_context=TraceContext.new_root())

    assert event.attribution == attribution
    assert current_usage_attribution.get() is None


def test_inner_block_without_attribution_keeps_outer() -> None:
    """Nested run/seat bindings do not erase an outer SDD attribution."""
    attribution = UsageAttribution(feat_id="FEAT-783", accounting_seat="development.w1")

    with usage_attribution("outer", attribution=attribution):
        with usage_attribution("inner", seat="development.w1"):
            assert current_usage_attribution.get() == attribution


def test_failed_event_carries_attribution_and_default_is_none() -> None:
    """Failed events snapshot bindings and use ``None`` outside an attribution scope."""
    attribution = UsageAttribution(feat_id="FEAT-783", task_id="TASK-4983")

    with usage_attribution("run-1", attribution=attribution):
        event = ClientCallFailedEvent(trace_context=TraceContext.new_root())

    unbound_event = ClientCallFailedEvent(trace_context=TraceContext.new_root())

    assert event.attribution == attribution
    assert unbound_event.attribution is None
