"""Unit tests for FEAT-479 Module 4a — UsageRecord flow attribution +
recording failed calls.

Extends the EXISTING usage-recording pipeline
(``AfterClientCallEvent`` -> ``UsageRecordingSubscriber`` -> ``UsageRecord``
-> fan-out to ``AbstractLogger`` sinks) rather than replacing it: this
module never constructs a new subscriber or a new ``UsageRecord`` type.
"""

from __future__ import annotations

import pytest
from navigator_eventbus.lifecycle.registry import EventRegistry
from navigator_eventbus.lifecycle.trace import TraceContext
from parrot.core.events.lifecycle.events import (
    AfterClientCallEvent,
    ClientCallFailedEvent,
)
from parrot.observability.context import usage_attribution
from parrot.observability.recorders.models import UsageRecord
from parrot.observability.recorders.subscriber import UsageRecordingSubscriber


class _CapturingSink:
    """Minimal AbstractLogger double."""

    def __init__(self):
        self.records: list[UsageRecord] = []

    async def record(self, record):
        self.records.append(record)

    async def aclose(self):
        pass


@pytest.fixture
def isolated_registry() -> EventRegistry:
    """Registry with forward_to_global=False so tests never touch the
    process-wide singleton (registry.py:98-101 documents this switch)."""
    return EventRegistry(forward_to_global=False)


def _after_call_event(*, input_tokens: int | None, output_tokens: int | None) -> AfterClientCallEvent:
    return AfterClientCallEvent(
        trace_context=TraceContext.new_root(),
        client_name="openai",
        model="gpt-4o",
        duration_ms=100.0,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def _failed_call_event(*, error_type: str) -> ClientCallFailedEvent:
    return ClientCallFailedEvent(
        trace_context=TraceContext.new_root(),
        client_name="openai",
        model="gpt-4o",
        duration_ms=50.0,
        error_type=error_type,
        error_message="a message that must never reach UsageRecord",
    )


def test_usagerecord_backcompat_minimal_construction():
    """Back-compat guard: none of the new fields are required."""
    r = UsageRecord(provider="openai")
    assert r.run_id is None and r.seat is None and r.cycle is None
    assert r.status == "completed"
    assert r.usage_reported is True
    assert r.total_tokens == 0


async def test_attribution_from_contextvars(isolated_registry):
    sink = _CapturingSink()
    isolated_registry.add_provider(UsageRecordingSubscriber(recorders=[sink], cost_calculator=None))
    with usage_attribution("run-1", "development.w1"):
        await isolated_registry.emit(_after_call_event(input_tokens=10, output_tokens=5))
    (rec,) = sink.records
    assert rec.run_id == "run-1"
    assert rec.seat == "development.w1"
    assert rec.node_id == "development"  # rolled up
    assert rec.usage_reported is True


async def test_unattributed_call_has_none_attribution(isolated_registry):
    """Outside any usage_attribution() block, attribution stays None."""
    sink = _CapturingSink()
    isolated_registry.add_provider(UsageRecordingSubscriber(recorders=[sink], cost_calculator=None))
    await isolated_registry.emit(_after_call_event(input_tokens=10, output_tokens=5))
    (rec,) = sink.records
    assert rec.run_id is None
    assert rec.seat is None
    assert rec.node_id is None


async def test_usage_reported_false_when_provider_reported_nothing(isolated_registry):
    """The 0-coercion stays for Prometheus/OpenLit; the flag preserves truth."""
    sink = _CapturingSink()
    isolated_registry.add_provider(UsageRecordingSubscriber(recorders=[sink], cost_calculator=None))
    await isolated_registry.emit(_after_call_event(input_tokens=None, output_tokens=None))
    (rec,) = sink.records
    assert rec.usage_reported is False
    assert rec.input_tokens == 0  # coerced, but flagged as unreported


async def test_failed_call_recorded(isolated_registry):
    sink = _CapturingSink()
    isolated_registry.add_provider(UsageRecordingSubscriber(recorders=[sink], cost_calculator=None))
    await isolated_registry.emit(_failed_call_event(error_type="TimeoutError"))
    (rec,) = sink.records
    assert rec.status == "failed"
    assert rec.error_type == "TimeoutError"
    assert rec.usage_reported is False


async def test_failed_call_carries_attribution(isolated_registry):
    sink = _CapturingSink()
    isolated_registry.add_provider(UsageRecordingSubscriber(recorders=[sink], cost_calculator=None))
    with usage_attribution("run-2", "qa"):
        await isolated_registry.emit(_failed_call_event(error_type="ValueError"))
    (rec,) = sink.records
    assert rec.run_id == "run-2"
    assert rec.seat == "qa"
    assert rec.node_id == "qa"


def test_no_error_message_field_on_record():
    """Privacy contract (models.py:8-11): no content on this record."""
    assert "error_message" not in UsageRecord.model_fields


async def test_register_subscribes_after_and_failed_never_stream_chunk(
    isolated_registry,
):
    """register() subscribes both AfterClientCallEvent and
    ClientCallFailedEvent, and never ClientStreamChunkEvent."""
    from parrot.core.events.lifecycle.events import ClientStreamChunkEvent

    sink = _CapturingSink()
    UsageRecordingSubscriber(recorders=[sink], cost_calculator=None).register(isolated_registry)
    assert isolated_registry.has_subscribers(AfterClientCallEvent) is True
    assert isolated_registry.has_subscribers(ClientCallFailedEvent) is True
    assert isolated_registry.has_subscribers(ClientStreamChunkEvent) is False


async def test_existing_recorders_unaffected(isolated_registry):
    """Back-compat guard: Logging/OpenLit/Prometheus recorders still accept
    a UsageRecord built with none of the new fields set."""
    from parrot.observability.recorders.logging_recorder import (
        LoggingUsageRecorder,
    )

    recorder = LoggingUsageRecorder()
    isolated_registry.add_provider(UsageRecordingSubscriber(recorders=[recorder], cost_calculator=None))
    # Must not raise.
    await isolated_registry.emit(_after_call_event(input_tokens=10, output_tokens=5))
