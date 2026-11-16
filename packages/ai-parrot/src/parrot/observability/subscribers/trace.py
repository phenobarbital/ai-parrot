"""GenAIOpenTelemetrySubscriber — rich GenAI SemConv span subscriber.

FEAT-177 TASK-1230. Maps 12 of FEAT-176's lifecycle events to OTel spans with
full GenAI Semantic Conventions attributes. Coexists with FEAT-176's stub
``OpenTelemetrySubscriber`` via a distinct class name.

Design points:
- Each span is keyed by ``event.trace_context.span_id`` in ``_active_spans``.
- ``asyncio.Lock`` guards concurrent access to ``_active_spans``.
- An end event that arrives before its start event is buffered in
  ``_pending_ends`` (FIFO-capped) and applied when the start arrives. The
  client forwards ``BeforeClientCallEvent`` to the global registry
  fire-and-forget but awaits the after/failed forward, so a call that never
  yields to the event loop delivers its end first.
- ``MessageAddedEvent`` and ``AgentStatusChangedEvent`` attach *span events*
  (not spans) to the currently-active span.
- ``ClientStreamChunkEvent`` is a no-op unless ``capture_completions=True``.
- Never import ``opentelemetry`` at module top-level — lazy import on
  construction so users without the SDK are not forced to install it.
"""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, NamedTuple, Optional

from parrot.core.events.lifecycle import LifecycleEvent
from parrot.core.events.lifecycle.events import (
    AfterClientCallEvent,
    AfterInvokeEvent,
    AfterToolCallEvent,
    AgentStatusChangedEvent,
    BeforeClientCallEvent,
    BeforeInvokeEvent,
    BeforeToolCallEvent,
    ClientCallFailedEvent,
    ClientStreamChunkEvent,
    InvokeFailedEvent,
    MessageAddedEvent,
    ToolCallFailedEvent,
)
from parrot.observability.attributes import (
    build_after_client_attrs,
    build_after_invoke_attrs,
    build_after_tool_attrs,
    build_before_client_attrs,
    build_before_invoke_attrs,
    build_before_tool_attrs,
    build_client_failed_attrs,
    build_invoke_failed_attrs,
    build_message_event_attrs,
    build_tool_failed_attrs,
    resolve_gen_ai_system,
)

if TYPE_CHECKING:
    from parrot.core.events.lifecycle import EventRegistry
    from parrot.observability.cost.calculator import CostCalculator

logger = logging.getLogger(__name__)

_MAX_PENDING_ENDS = 1024
"""Cap on buffered span ends whose start event has not been processed yet."""


class _PendingEnd(NamedTuple):
    """A span end that arrived before its span start.

    Attributes:
        ok: ``True`` for an OK close, ``False`` for an ERROR close.
        attrs: Final attributes to set on the span before closing it.
        end_time_ns: Creation time of the end event in epoch nanoseconds, or
            ``None`` when the event carries no timezone-aware timestamp.
    """

    ok: bool
    attrs: Dict[str, Any]
    end_time_ns: Optional[int]


class GenAIOpenTelemetrySubscriber:
    """Rich OTel span subscriber implementing GenAI Semantic Conventions.

    Subscribes to 12 FEAT-176 lifecycle event classes and maps them to OTel
    spans. Use ``register(registry)`` to attach to an ``EventRegistry``.

    This class is distinct from FEAT-176's ``OpenTelemetrySubscriber`` stub,
    which it coexists with. Never rename it to ``OpenTelemetrySubscriber``.

    Args:
        service_name: Used as the OTel tracer name / ``service.name``.
        tracer_provider: Optional pre-built OTel ``TracerProvider``. When
            ``None``, the global provider is used.
        cost_calculator: Optional ``CostCalculator`` for attaching USD cost
            to ``AfterClientCallEvent`` spans and span attributes.
        capture_completions: When ``True``, each ``ClientStreamChunkEvent``
            adds a span *event* to the active span. Default ``False`` (PII).
    """

    def __init__(
        self,
        *,
        service_name: str = "ai-parrot",
        tracer_provider: Optional[Any] = None,
        cost_calculator: Optional["CostCalculator"] = None,
        capture_completions: bool = False,
    ) -> None:
        try:
            from opentelemetry import trace as otel_trace  # noqa: PLC0415
        except ImportError as exc:
            raise ImportError(
                "GenAIOpenTelemetrySubscriber requires the 'observability' extra. "
                "Install with: pip install 'ai-parrot[observability]'"
            ) from exc
        self._tracer = (
            tracer_provider.get_tracer(service_name)
            if tracer_provider is not None
            else otel_trace.get_tracer(service_name)
        )
        self._cost = cost_calculator
        self._capture_completions = capture_completions
        self._active_spans: Dict[str, Any] = {}
        self._pending_ends: OrderedDict[str, _PendingEnd] = OrderedDict()
        self._max_pending_ends = _MAX_PENDING_ENDS
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # EventProvider Protocol — synchronous registration
    # ------------------------------------------------------------------

    def register(self, registry: "EventRegistry") -> None:
        """Subscribe all handlers to *registry*.

        Args:
            registry: The ``EventRegistry`` to attach to. Call is synchronous
                per ``EventProvider`` Protocol (provider.py:45).
        """
        registry.subscribe(BeforeInvokeEvent, self._on_invoke_start)
        registry.subscribe(AfterInvokeEvent, self._on_invoke_end)
        registry.subscribe(InvokeFailedEvent, self._on_invoke_fail)
        registry.subscribe(BeforeClientCallEvent, self._on_client_start)
        registry.subscribe(AfterClientCallEvent, self._on_client_end)
        registry.subscribe(ClientCallFailedEvent, self._on_client_fail)
        registry.subscribe(ClientStreamChunkEvent, self._on_chunk)
        registry.subscribe(BeforeToolCallEvent, self._on_tool_start)
        registry.subscribe(AfterToolCallEvent, self._on_tool_end)
        registry.subscribe(ToolCallFailedEvent, self._on_tool_fail)
        registry.subscribe(MessageAddedEvent, self._on_message)
        registry.subscribe(AgentStatusChangedEvent, self._on_status_changed)

    # ------------------------------------------------------------------
    # Private OTel helpers
    # ------------------------------------------------------------------

    def _otel_parent_context(self, tc: Any) -> Any:
        """Build an OTel context from a ``TraceContext`` parent span ID.

        Mirrors the FEAT-176 stub pattern at subscribers/opentelemetry.py:120-142.

        Args:
            tc: ``TraceContext`` from the lifecycle event, or ``None``.

        Returns:
            An OTel context object or ``None`` for root spans.
        """
        if tc is None or tc.parent_span_id is None:
            return None
        from opentelemetry.trace import (  # lazy import
            NonRecordingSpan,
            SpanContext,
            TraceFlags,
            set_span_in_context,
        )
        parent_sc = SpanContext(
            trace_id=int(tc.trace_id, 16),
            span_id=int(tc.parent_span_id, 16),
            is_remote=False,
            trace_flags=TraceFlags(tc.trace_flags),
        )
        return set_span_in_context(NonRecordingSpan(parent_sc))

    async def _start_span(
        self,
        name: str,
        event: LifecycleEvent,
        attrs: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Open an OTel span and store it keyed by ``event.trace_context.span_id``.

        When the matching end event was processed first (see
        :meth:`_buffer_pending_end`), the span is not stored: it is opened at
        the start event's creation time and closed at once at the end event's
        creation time, with the buffered status and attributes.

        Args:
            name: Span name.
            event: The triggering lifecycle event (provides trace context).
            attrs: Attribute dict to set on the span immediately.
        """
        ctx = self._otel_parent_context(event.trace_context)
        span_key = event.trace_context.span_id if event.trace_context else None
        start_time_ns: Optional[int] = None
        end_time_ns: Optional[int] = None
        async with self._lock:
            pending = self._pending_ends.pop(span_key, None) if span_key else None
            if pending is None:
                span = self._tracer.start_span(name, context=ctx)
            else:
                start_time_ns = self._event_time_ns(event)
                end_time_ns = pending.end_time_ns
                if start_time_ns is None or end_time_ns is None:
                    start_time_ns = end_time_ns = None
                else:
                    end_time_ns = max(end_time_ns, start_time_ns)
                span = self._tracer.start_span(name, context=ctx, start_time=start_time_ns)
            if attrs:
                for k, v in attrs.items():
                    if v is not None:
                        span.set_attribute(k, v)
            if pending is None and span_key:
                self._active_spans[span_key] = span
        if pending is not None:
            self._close_span(span, ok=pending.ok, attrs=pending.attrs, end_time_ns=end_time_ns)

    async def _end_span_ok(
        self,
        event: LifecycleEvent,
        extra_attrs: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Close the matching span with OK status, optionally setting final attrs.

        If the span has not started yet, the end is buffered for
        :meth:`_start_span` instead of being dropped.

        Args:
            event: Lifecycle event whose ``span_id`` identifies the span.
            extra_attrs: Additional attributes to set before closing.
        """
        span_key = event.trace_context.span_id if event.trace_context else None
        if not span_key:
            return
        async with self._lock:
            span = self._active_spans.pop(span_key, None)
            if span is None:
                self._buffer_pending_end(
                    span_key,
                    _PendingEnd(ok=True, attrs=dict(extra_attrs or {}), end_time_ns=self._event_time_ns(event)),
                )
        if span is not None:
            self._close_span(span, ok=True, attrs=extra_attrs)

    async def _end_span_error(
        self,
        event: LifecycleEvent,
        error_attrs: Dict[str, Any],
    ) -> None:
        """Close the matching span with ERROR status.

        If the span has not started yet, the end is buffered for
        :meth:`_start_span` instead of being dropped.

        Args:
            event: Lifecycle event whose ``span_id`` identifies the span.
            error_attrs: Attribute dict including ``error.type`` / ``error.message``.
        """
        span_key = event.trace_context.span_id if event.trace_context else None
        if not span_key:
            return
        async with self._lock:
            span = self._active_spans.pop(span_key, None)
            if span is None:
                self._buffer_pending_end(
                    span_key,
                    _PendingEnd(ok=False, attrs=dict(error_attrs), end_time_ns=self._event_time_ns(event)),
                )
        if span is not None:
            self._close_span(span, ok=False, attrs=error_attrs)

    def _close_span(
        self,
        span: Any,
        *,
        ok: bool,
        attrs: Optional[Dict[str, Any]],
        end_time_ns: Optional[int] = None,
    ) -> None:
        """Set final attributes and status on *span*, then end it.

        Args:
            span: The OTel span to close.
            ok: ``True`` for OK status; ``False`` for ERROR status described by
                ``attrs["error.message"]``.
            attrs: Final attributes; ``None`` values are skipped.
            end_time_ns: End time in epoch nanoseconds, or ``None`` to end now.
        """
        from opentelemetry.trace import Status, StatusCode  # lazy import

        attrs = attrs or {}
        for k, v in attrs.items():
            if v is not None:
                span.set_attribute(k, v)
        if ok:
            span.set_status(Status(StatusCode.OK))
        else:
            span.set_status(Status(StatusCode.ERROR, str(attrs.get("error.message", ""))))
        if end_time_ns is None:
            span.end()
        else:
            span.end(end_time=end_time_ns)

    def _buffer_pending_end(self, span_key: str, pending: _PendingEnd) -> None:
        """Remember an end whose span has not started yet. Caller holds ``_lock``.

        ``AbstractClient`` forwards ``BeforeClientCallEvent`` to the global
        registry fire-and-forget but awaits the after/failed forward, so a call
        that completes without yielding to the event loop (a stub, a cache hit)
        reaches this subscriber end-first. :meth:`_start_span` consumes the
        entry. The buffer is FIFO-capped at ``_max_pending_ends`` so ends whose
        start never arrives cannot grow it without bound.

        Args:
            span_key: The ``span_id`` of the span being closed.
            pending: Status, attributes and end time to apply on start.
        """
        self._pending_ends[span_key] = pending
        self._pending_ends.move_to_end(span_key)
        while len(self._pending_ends) > self._max_pending_ends:
            dropped, _ = self._pending_ends.popitem(last=False)
            logger.debug("Dropped unmatched span end %s: pending-end buffer is full", dropped)

    @staticmethod
    def _event_time_ns(event: LifecycleEvent) -> Optional[int]:
        """Return the event's creation time in epoch nanoseconds.

        Args:
            event: Lifecycle event carrying a ``timestamp`` datetime.

        Returns:
            Epoch nanoseconds, or ``None`` when the event has no timezone-aware
            ``timestamp``.
        """
        ts = getattr(event, "timestamp", None)
        if not isinstance(ts, datetime) or ts.tzinfo is None:
            return None
        return round(ts.timestamp() * 1_000_000) * 1_000

    async def _get_active_span(self, span_key: Optional[str]) -> Optional[Any]:
        """Return the active span for *span_key* without removing it.

        Args:
            span_key: The ``span_id`` to look up.

        Returns:
            The active span, or ``None`` if not found.
        """
        if not span_key:
            return None
        async with self._lock:
            return self._active_spans.get(span_key)

    # ------------------------------------------------------------------
    # Invoke handlers
    # ------------------------------------------------------------------

    async def _on_invoke_start(self, event: BeforeInvokeEvent) -> None:
        attrs = build_before_invoke_attrs(event)
        await self._start_span("parrot.agent.invoke", event, attrs=attrs)

    async def _on_invoke_end(self, event: AfterInvokeEvent) -> None:
        extra = build_after_invoke_attrs(event)
        await self._end_span_ok(event, extra_attrs=extra)

    async def _on_invoke_fail(self, event: InvokeFailedEvent) -> None:
        error_attrs = build_invoke_failed_attrs(event)
        await self._end_span_error(event, error_attrs=error_attrs)

    # ------------------------------------------------------------------
    # Client (LLM) handlers
    # ------------------------------------------------------------------

    async def _on_client_start(self, event: BeforeClientCallEvent) -> None:
        system = resolve_gen_ai_system(event.client_name)
        span_name = f"parrot.client.{system}.chat"
        attrs = build_before_client_attrs(event)
        await self._start_span(span_name, event, attrs=attrs)

    async def _on_client_end(self, event: AfterClientCallEvent) -> None:
        from parrot.observability.cost import resolve_event_cost

        cost: Optional[float] = resolve_event_cost(event, self._cost)
        extra = build_after_client_attrs(event, cost_usd=cost)
        await self._end_span_ok(event, extra_attrs=extra)

    async def _on_client_fail(self, event: ClientCallFailedEvent) -> None:
        error_attrs = build_client_failed_attrs(event)
        await self._end_span_error(event, error_attrs=error_attrs)

    async def _on_chunk(self, event: ClientStreamChunkEvent) -> None:
        """Handle streaming chunk — no-op unless ``capture_completions=True``."""
        if not self._capture_completions:
            return
        span_key = event.trace_context.span_id if event.trace_context else None
        span = await self._get_active_span(span_key)
        if span is None:
            return
        # Attach chunk metadata only — never chunk content (PII).
        span.add_event(
            "parrot.stream_chunk",
            attributes={
                "parrot.chunk.index": event.chunk_index,
                "parrot.chunk.size_bytes": event.chunk_size_bytes,
            },
        )

    # ------------------------------------------------------------------
    # Tool handlers
    # ------------------------------------------------------------------

    async def _on_tool_start(self, event: BeforeToolCallEvent) -> None:
        span_name = f"parrot.tool.{event.tool_name or 'unknown'}"
        attrs = build_before_tool_attrs(event)
        await self._start_span(span_name, event, attrs=attrs)

    async def _on_tool_end(self, event: AfterToolCallEvent) -> None:
        extra = build_after_tool_attrs(event)
        await self._end_span_ok(event, extra_attrs=extra)

    async def _on_tool_fail(self, event: ToolCallFailedEvent) -> None:
        error_attrs = build_tool_failed_attrs(event)
        await self._end_span_error(event, error_attrs=error_attrs)

    # ------------------------------------------------------------------
    # Span-event handlers (no new spans — attach to active span)
    # ------------------------------------------------------------------

    async def _on_message(self, event: MessageAddedEvent) -> None:
        """Attach a span event to the active invoke span."""
        # Relies on the emitter (AbstractBot / Agent) copying the invoke-level
        # trace_context into MessageAddedEvent. If a new root context is used,
        # the lookup will miss and the span event will be silently dropped.
        span_key = event.trace_context.span_id if event.trace_context else None
        span = await self._get_active_span(span_key)
        if span is None:
            return
        attrs = build_message_event_attrs(event)
        span.add_event("parrot.message_added", attributes=attrs)

    async def _on_status_changed(self, event: AgentStatusChangedEvent) -> None:
        """Attach a span event for agent status transitions."""
        span_key = event.trace_context.span_id if event.trace_context else None
        span = await self._get_active_span(span_key)
        if span is None:
            return
        span.add_event(
            "parrot.agent_status_changed",
            attributes={
                "parrot.agent.name": event.agent_name,
                "parrot.agent.old_status": event.old_status,
                "parrot.agent.new_status": event.new_status,
            },
        )
