"""Unit tests for GenAIOpenTelemetrySubscriber.

FEAT-177 TASK-1230.
"""

from __future__ import annotations

import asyncio
from datetime import datetime

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from parrot.core.events.lifecycle.events import (
    AfterClientCallEvent,
    AfterInvokeEvent,
    BeforeClientCallEvent,
    BeforeInvokeEvent,
    ClientCallFailedEvent,
    ClientStreamChunkEvent,
    MessageAddedEvent,
)
from navigator_eventbus.lifecycle.registry import EventRegistry
from navigator_eventbus.lifecycle.trace import TraceContext
from parrot.observability.subscribers.trace import GenAIOpenTelemetrySubscriber


@pytest.fixture
def telemetry():
    """Return (registry, exporter, subscriber) wired with InMemorySpanExporter."""
    exporter = InMemorySpanExporter()
    tp = TracerProvider()
    tp.add_span_processor(SimpleSpanProcessor(exporter))
    sub = GenAIOpenTelemetrySubscriber(tracer_provider=tp)
    reg = EventRegistry(forward_to_global=False)
    reg.add_provider(sub)
    return reg, exporter, sub


@pytest.mark.asyncio
async def test_full_cycle_produces_parent_child(telemetry) -> None:
    """Invoke + client cycle produces 2 spans with correct GenAI SemConv attrs."""
    reg, exporter, _ = telemetry
    root = TraceContext.new_root()
    child = root.child()

    await reg.emit(BeforeInvokeEvent(
        trace_context=root, agent_name="bot", method="ask",
    ))
    await reg.emit(BeforeClientCallEvent(
        trace_context=child, client_name="openai", model="gpt-4o",
        temperature=0.7, has_tools=False,
    ))
    await reg.emit(AfterClientCallEvent(
        trace_context=child, client_name="openai", model="gpt-4o",
        duration_ms=1234.0, input_tokens=100, output_tokens=50,
        finish_reason="stop",
    ))
    await reg.emit(AfterInvokeEvent(
        trace_context=root, agent_name="bot", method="ask",
        duration_ms=2345.0,
    ))

    spans = exporter.get_finished_spans()
    assert len(spans) == 2
    client_span = next(s for s in spans if "client" in s.name)
    assert client_span.attributes["gen_ai.system"] == "openai"
    assert client_span.attributes["gen_ai.usage.input_tokens"] == 100
    assert client_span.attributes["gen_ai.usage.output_tokens"] == 50


@pytest.mark.asyncio
async def test_failed_client_sets_error_status(telemetry) -> None:
    """ClientCallFailedEvent ends span with ERROR status and error attrs."""
    reg, exporter, _ = telemetry
    tc = TraceContext.new_root()

    await reg.emit(BeforeClientCallEvent(
        trace_context=tc, client_name="openai", model="gpt-4o",
    ))
    await reg.emit(ClientCallFailedEvent(
        trace_context=tc, client_name="openai", model="gpt-4o",
        duration_ms=10.0, error_type="APIError", error_message="boom",
    ))

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.status.is_ok is False
    assert span.attributes["error.type"] == "APIError"


@pytest.mark.asyncio
async def test_chunk_default_skipped(telemetry) -> None:
    """ClientStreamChunkEvent with capture_completions=False adds no span event."""
    reg, exporter, _ = telemetry
    tc = TraceContext.new_root()

    await reg.emit(BeforeClientCallEvent(
        trace_context=tc, client_name="openai", model="gpt-4o",
    ))
    await reg.emit(ClientStreamChunkEvent(
        trace_context=tc, client_name="openai", model="gpt-4o",
        chunk_index=0, chunk_size_bytes=42,
    ))
    await reg.emit(AfterClientCallEvent(
        trace_context=tc, client_name="openai", model="gpt-4o",
        duration_ms=1.0, input_tokens=1, output_tokens=1,
    ))

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert all("chunk" not in e.name for e in span.events)


@pytest.mark.asyncio
async def test_chunk_opt_in_adds_span_event() -> None:
    """ClientStreamChunkEvent with capture_completions=True adds one span event."""
    exporter = InMemorySpanExporter()
    tp = TracerProvider()
    tp.add_span_processor(SimpleSpanProcessor(exporter))
    sub = GenAIOpenTelemetrySubscriber(tracer_provider=tp, capture_completions=True)
    reg = EventRegistry(forward_to_global=False)
    reg.add_provider(sub)

    tc = TraceContext.new_root()
    await reg.emit(BeforeClientCallEvent(
        trace_context=tc, client_name="openai", model="gpt-4o",
    ))
    await reg.emit(ClientStreamChunkEvent(
        trace_context=tc, client_name="openai", model="gpt-4o",
        chunk_index=0, chunk_size_bytes=42,
    ))
    await reg.emit(AfterClientCallEvent(
        trace_context=tc, client_name="openai", model="gpt-4o",
        duration_ms=1.0,
    ))

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert any("chunk" in e.name for e in span.events)


@pytest.mark.asyncio
async def test_message_added_creates_span_event_not_span(telemetry) -> None:
    """MessageAddedEvent adds a span event — does NOT create a new span."""
    reg, exporter, _ = telemetry
    root = TraceContext.new_root()

    await reg.emit(BeforeInvokeEvent(
        trace_context=root, agent_name="bot", method="ask",
    ))
    await reg.emit(MessageAddedEvent(
        trace_context=root, agent_name="bot",
        role="user", content_length=42, has_tool_calls=False,
    ))
    await reg.emit(AfterInvokeEvent(
        trace_context=root, agent_name="bot", method="ask", duration_ms=100.0,
    ))

    spans = exporter.get_finished_spans()
    assert len(spans) == 1   # only the invoke span; no new span for message
    invoke_span = spans[0]
    msg_events = [e for e in invoke_span.events if "message" in e.name]
    assert len(msg_events) == 1


@pytest.mark.asyncio
async def test_cost_absent_when_no_calculator(telemetry) -> None:
    """parrot.cost.usd must not appear in attrs when cost_calculator is None."""
    reg, exporter, _ = telemetry
    tc = TraceContext.new_root()

    await reg.emit(BeforeClientCallEvent(
        trace_context=tc, client_name="openai", model="gpt-4o",
    ))
    await reg.emit(AfterClientCallEvent(
        trace_context=tc, client_name="openai", model="gpt-4o",
        duration_ms=100.0, input_tokens=10, output_tokens=5,
    ))

    spans = exporter.get_finished_spans()
    assert "parrot.cost.usd" not in spans[0].attributes


def _ns(ts: datetime) -> int:
    """Epoch nanoseconds of an aware datetime, at microsecond precision."""
    return round(ts.timestamp() * 1_000_000) * 1_000


@pytest.mark.asyncio
async def test_client_end_before_start_still_exports_span(telemetry) -> None:
    """An after-event processed before its before-event still ends and exports the span.

    Regression for issue:a694582dbb67: the end used to be dropped and the
    late-started span leaked in ``_active_spans``.
    """
    reg, exporter, sub = telemetry
    tc = TraceContext.new_root()
    before = BeforeClientCallEvent(trace_context=tc, client_name="openai", model="gpt-4o")
    after = AfterClientCallEvent(
        trace_context=tc, client_name="openai", model="gpt-4o",
        duration_ms=1.0, input_tokens=7, output_tokens=3,
    )

    await reg.emit(after)
    assert exporter.get_finished_spans() == ()
    await reg.emit(before)

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.status.is_ok is True
    assert span.attributes["gen_ai.system"] == "openai"
    assert span.attributes["gen_ai.usage.input_tokens"] == 7
    assert span.start_time == _ns(before.timestamp)
    assert span.end_time == _ns(after.timestamp)
    assert sub._active_spans == {}
    assert len(sub._pending_ends) == 0


@pytest.mark.asyncio
async def test_client_fail_before_start_sets_error_status(telemetry) -> None:
    """A failed-event processed before its before-event ends the span with ERROR."""
    reg, exporter, sub = telemetry
    tc = TraceContext.new_root()
    before = BeforeClientCallEvent(trace_context=tc, client_name="openai", model="gpt-4o")
    failed = ClientCallFailedEvent(
        trace_context=tc, client_name="openai", model="gpt-4o",
        duration_ms=1.0, error_type="APIError", error_message="boom",
    )

    await reg.emit(failed)
    await reg.emit(before)

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].status.is_ok is False
    assert spans[0].status.description == "boom"
    assert spans[0].attributes["error.type"] == "APIError"
    assert sub._active_spans == {}
    assert len(sub._pending_ends) == 0


@pytest.mark.asyncio
async def test_fire_and_forget_start_after_awaited_end(telemetry) -> None:
    """Mirror AbstractClient: start scheduled as a task, end awaited without yielding."""
    reg, exporter, sub = telemetry
    tc = TraceContext.new_root()

    start_task = asyncio.create_task(
        reg.emit(BeforeClientCallEvent(trace_context=tc, client_name="openai", model="gpt-4o"))
    )
    await reg.emit(AfterClientCallEvent(
        trace_context=tc, client_name="openai", model="gpt-4o", duration_ms=0.0,
    ))
    await start_task

    assert len(exporter.get_finished_spans()) == 1
    assert sub._active_spans == {}
    assert len(sub._pending_ends) == 0


@pytest.mark.asyncio
async def test_pending_end_buffer_is_capped(telemetry) -> None:
    """Ends whose start never arrives are evicted oldest-first past the cap."""
    reg, exporter, sub = telemetry
    sub._max_pending_ends = 2
    contexts = [TraceContext.new_root() for _ in range(3)]

    for tc in contexts:
        await reg.emit(AfterClientCallEvent(
            trace_context=tc, client_name="openai", model="gpt-4o", duration_ms=1.0,
        ))

    assert list(sub._pending_ends) == [contexts[1].span_id, contexts[2].span_id]
    assert exporter.get_finished_spans() == ()
