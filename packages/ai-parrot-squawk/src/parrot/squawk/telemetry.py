"""Served-side telemetry: one CapabilityCallEvent + one recorder call per capability call (FEAT-746 M12, D13)."""

from __future__ import annotations

import logging
from typing import Literal

from parrot.core.events.lifecycle import (
    EventRegistry,
    TraceContext,
    get_global_registry,
)  # verified: core/events/lifecycle/__init__.py:21-22
from parrot.core.events.lifecycle.events import CapabilityCallEvent
from parrot.interagent import CallCost, SquawkCapability
from parrot.observability.recorders import AbstractLogger, CapabilityCallRecord


def record_from_call(
    *,
    side: Literal["served", "received"],
    agent: str,
    peer: str,
    cap: SquawkCapability,
    status: str,
    cost: CallCost,
    trace_id: str,
    correlation_id: str | None = None,
    policy_applied: tuple[str, ...] = (),
) -> CapabilityCallRecord:
    """Tokens only for llm_backed capabilities; never provider/model fields."""
    llm = cap.backing == "llm_backed"
    return CapabilityCallRecord(
        side=side,
        agent=agent,
        peer_agent=peer,
        cap_id=cap.cap_id,
        category=cap.category,
        backing=cap.backing,
        status=status,
        duration_ms=float(cost.duration_ms),
        rows=cost.rows,
        bytes=cost.bytes,
        tokens_in=cost.tokens_in if llm else 0,
        tokens_out=cost.tokens_out if llm else 0,
        cost_usd=cost.cost_usd,
        policy_applied=policy_applied,
        trace_id=trace_id,
        correlation_id=correlation_id,
    )


class ServedTelemetry:
    def __init__(self, *, registry: EventRegistry | None = None, recorder: AbstractLogger | None = None) -> None:
        self._registry = registry
        self._recorder = recorder
        self.logger = logging.getLogger(__name__)

    async def emit(self, record: CapabilityCallRecord) -> None:
        """Publish the event and record it; failures are logged, never raised into the call path."""
        try:
            registry = self._registry or get_global_registry()
            # Create a trace context using the record's trace_id
            trace_context = TraceContext(trace_id=record.trace_id, span_id="0000000000000001")
            await registry.emit(CapabilityCallEvent(trace_context=trace_context, record=record))
        except Exception:  # noqa: BLE001
            self.logger.exception("ServedTelemetry: event publish failed")
        if self._recorder is not None:
            try:
                await self._recorder.record_capability(record)
            except Exception:  # noqa: BLE001
                self.logger.exception("ServedTelemetry: recorder failed")
