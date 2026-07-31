"""OpenTelemetrySubscriber — maps LifecycleEvents to OTel spans.

FEAT-176 — Lifecycle Events System.

Maps ``Before*`` / ``After*`` / ``*Failed`` lifecycle events to OpenTelemetry
spans using the W3C ``TraceContext`` carried on every event.  Requires the
``otel`` extra::

    pip install 'ai-parrot[otel]'

The subscriber is lazy about OTel imports: ``import`` at module top-level is
safe; the OTel SDK is only loaded inside the constructor and callbacks.  If
the extra is not installed, constructing the subscriber raises ``ImportError``
with a clear action message.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Dict, Optional

from navigator_eventbus.lifecycle.base import LifecycleEvent
from parrot.core.events.lifecycle.events import (
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

if TYPE_CHECKING:
    from navigator_eventbus.lifecycle.registry import EventRegistry


class OpenTelemetrySubscriber:
    """EventProvider that maps lifecycle events to OpenTelemetry spans.

    Each ``Before*`` event opens a span; the matching ``After*`` or ``*Failed``
    event closes it.  The ``TraceContext.parent_span_id`` is used to set the
    parent span context so spans nest correctly in distributed traces.

    Requires the ``otel`` extra:  ``pip install 'ai-parrot[otel]'``

    Note:
        This subscriber should be registered on only one registry per process
        to avoid concurrent access across event loops.  The internal
        ``_active_spans`` dict is protected by an ``asyncio.Lock``; however,
        sharing the same instance across multiple independently-running event
        loops is not supported.

    Args:
        service_name: Name used to identify the tracer (default ``"parrot"``).
        endpoint: Optional OTel collector endpoint.  When ``None``, the
            currently configured ``TracerProvider`` is used (falls back to the
            no-op provider if none is configured).
        tracer_provider: Optional ``TracerProvider`` instance.  Pass this in
            tests to avoid global-state conflicts from ``set_tracer_provider()``.
            When ``None`` (default), the global provider is used.
    """

    def __init__(
        self,
        *,
        service_name: str = "parrot",
        endpoint: Optional[str] = None,
        tracer_provider: Optional[Any] = None,
    ) -> None:
        try:
            from opentelemetry import trace  # noqa: F401
            from opentelemetry.trace import Status, StatusCode, Tracer  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "OpenTelemetrySubscriber requires the 'otel' extra. "
                "Install with: pip install 'ai-parrot[otel]'"
            ) from exc

        self._service_name = service_name
        self._endpoint = endpoint

        # Use the passed-in provider if given, else the global provider.
        if tracer_provider is not None:
            self._tracer = tracer_provider.get_tracer(service_name)
        else:
            from opentelemetry import trace as otel_trace
            self._tracer = otel_trace.get_tracer(service_name)

        # Map span_id (hex string) → live span, for cleanup symmetry.
        # Protected by _lock to guard concurrent async access.
        self._active_spans: Dict[str, Any] = {}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # EventProvider
    # ------------------------------------------------------------------

    def register(self, registry: "EventRegistry") -> None:
        """Register all Before/After/Failed subscribers with *registry*.

        Args:
            registry: The ``EventRegistry`` to subscribe to.
        """
        registry.subscribe(BeforeInvokeEvent, self._on_invoke_start)
        registry.subscribe(AfterInvokeEvent, self._on_invoke_end)
        registry.subscribe(InvokeFailedEvent, self._on_invoke_fail)
        registry.subscribe(BeforeClientCallEvent, self._on_client_start)
        registry.subscribe(AfterClientCallEvent, self._on_client_end)
        registry.subscribe(ClientCallFailedEvent, self._on_client_fail)
        registry.subscribe(BeforeToolCallEvent, self._on_tool_start)
        registry.subscribe(AfterToolCallEvent, self._on_tool_end)
        registry.subscribe(ToolCallFailedEvent, self._on_tool_fail)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _otel_parent_context(self, tc: Any) -> Any:
        """Build an OTel context from a ``TraceContext`` parent span ID.

        Returns ``None`` for root spans (``parent_span_id is None``).

        Args:
            tc: The ``TraceContext`` from the lifecycle event.

        Returns:
            An OTel context object or ``None``.
        """
        if tc is None or tc.parent_span_id is None:
            return None
        from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags
        from opentelemetry.trace import set_span_in_context

        parent_sc = SpanContext(
            trace_id=int(tc.trace_id, 16),
            span_id=int(tc.parent_span_id, 16),
            is_remote=False,
            trace_flags=TraceFlags(tc.trace_flags),
        )
        return set_span_in_context(NonRecordingSpan(parent_sc))

    async def _start_span(self, name: str, event: LifecycleEvent, **attrs: Any) -> None:
        """Open a span and store it in ``_active_spans`` keyed by span_id.

        Protected by ``_lock`` to guard concurrent async access to
        ``_active_spans``.

        Args:
            name: OTel span name.
            event: The lifecycle event that triggered span creation.
            **attrs: Additional span attributes.
        """
        ctx = self._otel_parent_context(event.trace_context)
        span = self._tracer.start_span(name, context=ctx)
        for k, v in attrs.items():
            if v is not None:
                span.set_attribute(k, str(v))
        span_key = event.trace_context.span_id if event.trace_context else None
        if span_key:
            async with self._lock:
                self._active_spans[span_key] = span

    async def _end_span_ok(self, event: LifecycleEvent) -> None:
        """Close the matching span with OK status.

        Protected by ``_lock`` to guard concurrent async access to
        ``_active_spans``.

        Args:
            event: The lifecycle event whose span_id identifies the span.
        """
        from opentelemetry.trace import Status, StatusCode
        span_key = event.trace_context.span_id if event.trace_context else None
        if not span_key:
            return
        async with self._lock:
            span = self._active_spans.pop(span_key, None)
        if span is None:
            return
        span.set_status(Status(StatusCode.OK))
        span.end()

    async def _end_span_error(
        self, event: LifecycleEvent, error_type: str, error_message: str
    ) -> None:
        """Close the matching span with ERROR status.

        Protected by ``_lock`` to guard concurrent async access to
        ``_active_spans``.

        Args:
            event: The lifecycle event whose span_id identifies the span.
            error_type: Exception class name.
            error_message: Human-readable error description.
        """
        from opentelemetry.trace import Status, StatusCode
        span_key = event.trace_context.span_id if event.trace_context else None
        if not span_key:
            return
        async with self._lock:
            span = self._active_spans.pop(span_key, None)
        if span is None:
            return
        span.set_attribute("error.type", error_type)
        span.set_attribute("error.message", error_message)
        span.set_status(Status(StatusCode.ERROR, error_message))
        span.end()

    # ------------------------------------------------------------------
    # Invoke
    # ------------------------------------------------------------------

    async def _on_invoke_start(self, event: BeforeInvokeEvent) -> None:
        await self._start_span(
            f"agent.{event.agent_name or 'unknown'}.{event.method or 'invoke'}",
            event,
            agent_name=event.agent_name,
            method=event.method,
        )

    async def _on_invoke_end(self, event: AfterInvokeEvent) -> None:
        await self._end_span_ok(event)

    async def _on_invoke_fail(self, event: InvokeFailedEvent) -> None:
        await self._end_span_error(event, event.error_type, event.error_message)

    # ------------------------------------------------------------------
    # Client call
    # ------------------------------------------------------------------

    async def _on_client_start(self, event: BeforeClientCallEvent) -> None:
        await self._start_span(
            "client.call",
            event,
            source_name=event.source_name,
        )

    async def _on_client_end(self, event: AfterClientCallEvent) -> None:
        await self._end_span_ok(event)

    async def _on_client_fail(self, event: ClientCallFailedEvent) -> None:
        await self._end_span_error(event, event.error_type, event.error_message)

    # ------------------------------------------------------------------
    # Tool call
    # ------------------------------------------------------------------

    async def _on_tool_start(self, event: BeforeToolCallEvent) -> None:
        await self._start_span(
            f"tool.{event.tool_name or 'unknown'}.execute",
            event,
            tool_name=event.tool_name,
        )

    async def _on_tool_end(self, event: AfterToolCallEvent) -> None:
        await self._end_span_ok(event)

    async def _on_tool_fail(self, event: ToolCallFailedEvent) -> None:
        await self._end_span_error(event, event.error_type, event.error_message)
