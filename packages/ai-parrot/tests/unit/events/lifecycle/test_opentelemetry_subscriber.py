"""Unit tests for OpenTelemetrySubscriber.

FEAT-176 — Lifecycle Events System (TASK-1191).

These tests require the otel extra (opentelemetry-sdk).  If the SDK is not
installed, all tests are skipped automatically via ``pytest.importorskip``.
"""
from __future__ import annotations

import pytest

# Skip the entire module if opentelemetry SDK is not available.
otel_sdk = pytest.importorskip("opentelemetry.sdk.trace")

from opentelemetry.sdk.trace import TracerProvider  # noqa: E402
from opentelemetry.sdk.trace.export import SimpleSpanProcessor  # noqa: E402
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter  # noqa: E402
from opentelemetry.trace import StatusCode  # noqa: E402

from parrot.core.events.lifecycle.events import (  # noqa: E402
    AfterClientCallEvent,
    AfterInvokeEvent,
    AfterToolCallEvent,
    BeforeClientCallEvent,
    BeforeInvokeEvent,
    BeforeToolCallEvent,
    ClientCallFailedEvent,
    InvokeFailedEvent,
    ToolCallFailedEvent,
)
from navigator_eventbus.lifecycle.provider import EventProvider  # noqa: E402
from navigator_eventbus.lifecycle.registry import EventRegistry  # noqa: E402
from parrot.core.events.lifecycle.subscribers.opentelemetry import (  # noqa: E402
    OpenTelemetrySubscriber,
)
from navigator_eventbus.lifecycle.trace import TraceContext  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def exporter_and_provider():
    """Create an isolated TracerProvider+InMemorySpanExporter per test.

    We do NOT call otel_trace.set_tracer_provider() because OTel only allows
    setting it once globally.  Instead, pass the provider directly to the
    OpenTelemetrySubscriber via the ``tracer_provider`` kwarg.
    """
    exp = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exp))
    yield exp, provider
    exp.clear()


@pytest.fixture
def registry() -> EventRegistry:
    return EventRegistry(forward_to_global=False)


def _sub(provider: TracerProvider, service_name: str = "test") -> OpenTelemetrySubscriber:
    """Helper: create a subscriber that uses the given provider."""
    return OpenTelemetrySubscriber(service_name=service_name, tracer_provider=provider)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestOpenTelemetrySubscriber:
    def test_protocol_conformance(self) -> None:
        """OpenTelemetrySubscriber conforms to EventProvider."""
        assert isinstance(OpenTelemetrySubscriber(), EventProvider)

    def test_add_provider_returns_nine_ids(self, registry: EventRegistry, exporter_and_provider) -> None:
        """OpenTelemetrySubscriber registers 9 subscriptions (3 triplets)."""
        _, provider = exporter_and_provider
        ids = registry.add_provider(_sub(provider))
        assert len(ids) == 9

    @pytest.mark.asyncio
    async def test_before_after_creates_span(
        self, registry: EventRegistry, exporter_and_provider
    ) -> None:
        """BeforeInvokeEvent opens a span; AfterInvokeEvent closes it with OK."""
        exporter, provider = exporter_and_provider
        registry.add_provider(_sub(provider))
        ctx = TraceContext.new_root()
        await registry.emit(BeforeInvokeEvent(trace_context=ctx, agent_name="a", method="ask"))
        await registry.emit(AfterInvokeEvent(trace_context=ctx, agent_name="a", method="ask"))
        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].status.status_code == StatusCode.OK

    @pytest.mark.asyncio
    async def test_failed_sets_error_status(
        self, registry: EventRegistry, exporter_and_provider
    ) -> None:
        """InvokeFailedEvent closes the span with ERROR status."""
        exporter, provider = exporter_and_provider
        registry.add_provider(_sub(provider))
        ctx = TraceContext.new_root()
        await registry.emit(BeforeInvokeEvent(trace_context=ctx, agent_name="a"))
        await registry.emit(
            InvokeFailedEvent(
                trace_context=ctx,
                agent_name="a",
                error_type="ValueError",
                error_message="bad",
            )
        )
        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].status.status_code == StatusCode.ERROR

    @pytest.mark.asyncio
    async def test_tool_span_lifecycle(
        self, registry: EventRegistry, exporter_and_provider
    ) -> None:
        """BeforeToolCallEvent opens a span; AfterToolCallEvent closes it with OK."""
        exporter, provider = exporter_and_provider
        registry.add_provider(_sub(provider))
        ctx = TraceContext.new_root()
        await registry.emit(BeforeToolCallEvent(trace_context=ctx, tool_name="calculator"))
        await registry.emit(AfterToolCallEvent(trace_context=ctx, tool_name="calculator"))
        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].status.status_code == StatusCode.OK

    @pytest.mark.asyncio
    async def test_tool_failed_sets_error(
        self, registry: EventRegistry, exporter_and_provider
    ) -> None:
        """ToolCallFailedEvent closes the span with ERROR status."""
        exporter, provider = exporter_and_provider
        registry.add_provider(_sub(provider))
        ctx = TraceContext.new_root()
        await registry.emit(BeforeToolCallEvent(trace_context=ctx, tool_name="tool1"))
        await registry.emit(
            ToolCallFailedEvent(
                trace_context=ctx,
                tool_name="tool1",
                error_type="RuntimeError",
                error_message="failed",
            )
        )
        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].status.status_code == StatusCode.ERROR

    @pytest.mark.asyncio
    async def test_client_span_lifecycle(
        self, registry: EventRegistry, exporter_and_provider
    ) -> None:
        """BeforeClientCallEvent opens a span; AfterClientCallEvent closes it."""
        exporter, provider = exporter_and_provider
        registry.add_provider(_sub(provider))
        ctx = TraceContext.new_root()
        await registry.emit(BeforeClientCallEvent(trace_context=ctx, client_name="anthropic"))
        await registry.emit(AfterClientCallEvent(trace_context=ctx, client_name="anthropic"))
        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].status.status_code == StatusCode.OK

    @pytest.mark.asyncio
    async def test_child_context_parent_span(
        self, registry: EventRegistry, exporter_and_provider
    ) -> None:
        """Events with parent_span_id set produce child spans in the export."""
        exporter, provider = exporter_and_provider
        registry.add_provider(_sub(provider))
        root_ctx = TraceContext.new_root()
        child_ctx = root_ctx.child()
        await registry.emit(BeforeInvokeEvent(trace_context=child_ctx, agent_name="sub"))
        await registry.emit(AfterInvokeEvent(trace_context=child_ctx, agent_name="sub"))
        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        # The span's parent should reference the root's span_id.
        assert spans[0].parent is not None

    def test_no_otel_raises_clear_importerror(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Constructing the subscriber without the extra raises ImportError."""
        import sys

        monkeypatch.setitem(sys.modules, "opentelemetry", None)
        with pytest.raises(ImportError, match="ai-parrot\\[otel\\]"):
            OpenTelemetrySubscriber()
