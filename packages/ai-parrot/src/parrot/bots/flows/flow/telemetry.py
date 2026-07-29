"""FlowLifecycleAdapter — bridge AgentsFlow scheduler events to FEAT-176.

FEAT-176 Phase 1.5. Translates the scheduler's node-event channel
(``AgentsFlow(on_node_event=...)`` / ``add_node_event_listener``) into
typed :class:`LifecycleEvent` instances emitted on an
:class:`EventRegistry` — by default the process-wide global registry, so
every already-registered subscriber (OpenTelemetry, logging, webhook,
usage recorders) observes flow/node spans with zero extra wiring.

Trace identity:

- The run's root :class:`TraceContext` lives on ``FlowContext.trace_context``
  (created lazily here when the caller didn't seed one). Flow-level events
  carry the root span.
- Each node gets ONE child span, shared by its started/completed/failed
  events, so OTel subscribers can reconstruct the span tree
  (flow → node → client/tool calls made inside the node, which can read
  ``ctx.trace_context`` to parent their own spans).

Usage::

    flow = AgentsFlow("my-flow")
    flow.add_node_event_listener(FlowLifecycleAdapter())
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from navconfig.logging import logging

# FEAT-317: LifecycleEvent/EventRegistry/TraceContext moved to
# navigator_eventbus.lifecycle; imported here via the parrot.core.events.lifecycle
# re-export facade. Flow typed events STAY local.
from parrot.core.events.lifecycle import EventRegistry, LifecycleEvent, TraceContext
from parrot.core.events.lifecycle.events.flow import (
    FlowCompletedEvent,
    FlowStartedEvent,
    NodeCompletedEvent,
    NodeFailedEvent,
    NodeSkippedEvent,
    NodeStartedEvent,
)

logger = logging.getLogger("parrot.flow.telemetry")


class FlowLifecycleAdapter:
    """Node-event listener that emits typed FEAT-176 lifecycle events.

    Attach to an ``AgentsFlow`` via the constructor's ``on_node_event``
    parameter or :meth:`AgentsFlow.add_node_event_listener`. The adapter is
    synchronous (events are scheduled with ``EventRegistry.emit_nowait``)
    and never raises — the engine additionally shields listeners.

    Args:
        registry: Target ``EventRegistry``. ``None`` (default) resolves the
            process-wide global registry lazily on first event, matching the
            ``EventEmitterMixin`` default behaviour.
    """

    def __init__(self, *, registry: Optional[EventRegistry] = None) -> None:
        self._registry = registry
        # (id(ctx), node_id) → per-node child span, shared across that
        # node's started/completed/failed events.
        self._node_spans: Dict[Tuple[int, str], TraceContext] = {}

    # ------------------------------------------------------------------
    # Listener entry point
    # ------------------------------------------------------------------

    def __call__(self, event: str, node_id: str, info: Dict[str, Any]) -> None:
        """Translate one scheduler event into a LifecycleEvent and emit it.

        Args:
            event: Scheduler event name (``flow_started`` | ``node_started``
                | ``node_completed`` | ``node_failed`` | ``node_skipped``
                | ``flow_completed``). Unknown names are ignored.
            node_id: Node the event refers to (empty for flow-level events).
            info: Scheduler payload (``flow``, ``context``, ``duration_ms``,
                ``error``/``error_type``, ``status``, counts…).
        """
        try:
            lifecycle_event = self._build_event(event, node_id, info)
        except Exception:  # noqa: BLE001 - telemetry must never break runs
            logger.warning(
                "FlowLifecycleAdapter failed to build %s for %r",
                event, node_id, exc_info=True,
            )
            return
        if lifecycle_event is None:
            return
        self._resolve_registry().emit_nowait(lifecycle_event)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _resolve_registry(self) -> EventRegistry:
        """Return the target registry, defaulting to the global singleton."""
        if self._registry is None:
            from parrot.core.events.lifecycle import (  # noqa: PLC0415
                get_global_registry,
            )
            self._registry = get_global_registry()
        return self._registry

    @staticmethod
    def _run_identity(info: Dict[str, Any]) -> Tuple[Any, TraceContext, str]:
        """Resolve ``(ctx, root_trace, run_id)`` for the event's run.

        Lazily creates and pins a root ``TraceContext`` on the FlowContext
        when the caller didn't seed one, so every event of the run — and any
        node code reading ``ctx.trace_context`` — shares trace identity.
        """
        ctx = info.get("context")
        trace = getattr(ctx, "trace_context", None)
        if trace is None:
            trace = TraceContext.new_root()
            if ctx is not None:
                try:
                    ctx.trace_context = trace
                except Exception:  # noqa: BLE001 - exotic ctx objects
                    pass
        run_id = ""
        shared = getattr(ctx, "shared_data", None)
        if isinstance(shared, dict):
            run_id = str(shared.get("run_id", "") or "")
        return ctx, trace, run_id

    def _node_span(self, ctx: Any, node_id: str, root: TraceContext) -> TraceContext:
        """Return the per-node child span, creating it on first use."""
        key = (id(ctx), node_id)
        span = self._node_spans.get(key)
        if span is None:
            span = root.child()
            self._node_spans[key] = span
        return span

    def _drop_node_span(self, ctx: Any, node_id: str) -> None:
        """Forget a node's span once it reached a terminal event."""
        self._node_spans.pop((id(ctx), node_id), None)

    def _drop_run_spans(self, ctx: Any) -> None:
        """Forget every span belonging to a finished run."""
        ctx_key = id(ctx)
        for key in [k for k in self._node_spans if k[0] == ctx_key]:
            self._node_spans.pop(key, None)

    def _build_event(
        self, event: str, node_id: str, info: Dict[str, Any]
    ) -> Optional[LifecycleEvent]:
        """Map a scheduler event to its typed LifecycleEvent (or None)."""
        ctx, root, run_id = self._run_identity(info)
        flow_name = str(info.get("flow", "") or "")

        if event == "flow_started":
            return FlowStartedEvent(
                trace_context=root,
                source_type="flow",
                source_name=flow_name,
                flow_name=flow_name,
                run_id=run_id,
                node_count=int(info.get("node_count", 0) or 0),
            )

        if event == "flow_completed":
            self._drop_run_spans(ctx)
            return FlowCompletedEvent(
                trace_context=root,
                source_type="flow",
                source_name=flow_name,
                flow_name=flow_name,
                run_id=run_id,
                status=str(info.get("status", "") or ""),
                duration_ms=float(info.get("duration_ms", 0.0) or 0.0),
                completed_count=int(info.get("completed_count", 0) or 0),
                failed_count=int(info.get("failed_count", 0) or 0),
                skipped_count=int(info.get("skipped_count", 0) or 0),
            )

        common = {
            "source_type": "node",
            "source_name": node_id,
            "flow_name": flow_name,
            "node_id": node_id,
            "run_id": run_id,
        }

        if event == "node_started":
            return NodeStartedEvent(
                trace_context=self._node_span(ctx, node_id, root), **common
            )

        if event == "node_completed":
            span = self._node_span(ctx, node_id, root)
            self._drop_node_span(ctx, node_id)
            return NodeCompletedEvent(
                trace_context=span,
                duration_ms=float(info.get("duration_ms", 0.0) or 0.0),
                **common,
            )

        if event == "node_failed":
            span = self._node_span(ctx, node_id, root)
            self._drop_node_span(ctx, node_id)
            return NodeFailedEvent(
                trace_context=span,
                duration_ms=float(info.get("duration_ms", 0.0) or 0.0),
                error_type=str(info.get("error_type", "") or ""),
                error_message=str(info.get("error", "") or ""),
                **common,
            )

        if event == "node_skipped":
            # Skipped nodes never started: a fresh child span, not pooled.
            return NodeSkippedEvent(trace_context=root.child(), **common)

        return None


__all__ = ["FlowLifecycleAdapter"]
