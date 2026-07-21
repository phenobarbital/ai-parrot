"""Unit tests for GenAIOpenTelemetrySubscriber.

FEAT-177 TASK-1230.
"""

from __future__ import annotations

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
