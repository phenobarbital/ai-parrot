"""FEAT-783 TASK-4986 — cache counters + source_cost_usd carriage (AC-3, AC-5)."""

import pytest
from navigator_eventbus.lifecycle.trace import TraceContext

from parrot.core.events.lifecycle.events import AfterClientCallEvent
from parrot.flows.dev_loop.dispatchers.claude import ClaudeCodeDispatcher
from parrot.flows.dev_loop.models import ClaudeCodeDispatchProfile
from parrot.observability.recorders.models import UsageRecord
from parrot.observability.recorders.subscriber import UsageRecordingSubscriber


class _CapturingRecorder:
    """Capture usage records emitted by the subscriber."""

    name = "capture"

    def __init__(self) -> None:
        self.records: list[UsageRecord] = []

    async def record(self, record: UsageRecord) -> None:
        """Save one record for assertion."""
        self.records.append(record)

    async def aclose(self) -> None:
        """Provide the recorder protocol close hook."""


class _CapturingRegistry:
    """Capture dispatcher events without forwarding them globally."""

    def __init__(self) -> None:
        self.events: list[AfterClientCallEvent] = []

    async def emit(self, event: AfterClientCallEvent) -> None:
        """Save a locally emitted lifecycle event."""
        self.events.append(event)

    def forward_to_global(self, event: AfterClientCallEvent) -> None:
        """Match the dispatcher registry protocol without global effects."""


@pytest.mark.asyncio
async def test_subscriber_copies_counters_to_record() -> None:
    """Subscriber preserves cache and reasoning counters on UsageRecord."""
    recorder = _CapturingRecorder()
    subscriber = UsageRecordingSubscriber(recorders=[recorder], cost_calculator=None)
    event = AfterClientCallEvent(
        trace_context=TraceContext.new_root(),
        client_name="claude-code",
        model="claude-opus-5",
        cache_read_tokens=34,
        cache_creation_tokens=21,
        reasoning_output_tokens=13,
        source_cost_usd=9.99,
    )

    await subscriber._on_client_after(event)

    (record,) = recorder.records
    assert record.cache_read_tokens == 34
    assert record.cache_creation_tokens == 21
    assert record.reasoning_output_tokens == 13
    assert record.source_cost_usd == 9.99


@pytest.mark.asyncio
async def test_source_cost_never_becomes_cost_usd() -> None:
    """Provider-reported cost is reconciliation data, not reported cost."""
    recorder = _CapturingRecorder()
    subscriber = UsageRecordingSubscriber(recorders=[recorder], cost_calculator=None)
    event = AfterClientCallEvent(
        trace_context=TraceContext.new_root(),
        client_name="unknown-provider",
        model="unpriced-model",
        source_cost_usd=9.99,
    )

    await subscriber._on_client_after(event)

    (record,) = recorder.records
    assert record.source_cost_usd == 9.99
    assert record.cost_usd is None


@pytest.mark.asyncio
async def test_claude_emit_forwards_cache_and_cost() -> None:
    """Claude dispatcher forwards harvested cache counters and source cost."""
    dispatcher = ClaudeCodeDispatcher(
        max_concurrent=1,
        redis_url="redis://localhost:6379/0",
        stream_ttl_seconds=60,
    )
    registry = _CapturingRegistry()
    dispatcher.set_event_registry_resolver(lambda run_id: registry if run_id == "run-1" else None)

    await dispatcher._emit_usage_event(
        {
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_read_input_tokens": 25,
            "cache_creation_input_tokens": 15,
            "total_cost_usd": 1.5,
        },
        run_id="run-1",
        node_id="development",
        profile=ClaudeCodeDispatchProfile(model="claude-opus-5"),
    )

    (event,) = registry.events
    assert event.cache_read_tokens == 25
    assert event.cache_creation_tokens == 15
    assert event.source_cost_usd == 1.5
