"""UsageRecordingSubscriber — turns LLM-call events into UsageRecords + fan-out.

This is the bridge between the FEAT-176 lifecycle event system and the pluggable
recorder backends. It subscribes to ``AfterClientCallEvent`` on the global
registry (the same surface the OTel ``MetricsSubscriber`` uses), computes cost
via the shared ``CostCalculator``, builds a normalized ``UsageRecord``, and
fans it out to every configured ``AbstractLogger``.

It implements the ``EventProvider`` protocol (synchronous ``register``).
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Optional

from parrot.core.events.lifecycle.events import AfterClientCallEvent
from parrot.observability.attributes import resolve_gen_ai_system
from parrot.observability.recorders.models import UsageRecord

if TYPE_CHECKING:
    from parrot.core.events.lifecycle import EventRegistry
    from parrot.observability.cost.calculator import CostCalculator
    from parrot.observability.recorders.base import AbstractLogger

logger = logging.getLogger(__name__)


class UsageRecordingSubscriber:
    """Build ``UsageRecord``s from LLM-call events and fan out to recorders.

    Args:
        recorders: The pluggable backends to forward each record to.
        cost_calculator: Optional ``CostCalculator``; when provided, the per-call
            and cumulative USD cost are computed.
        service_name: ``service.name`` stamped on each record.
    """

    def __init__(
        self,
        *,
        recorders: "list[AbstractLogger]",
        cost_calculator: "Optional[CostCalculator]" = None,
        service_name: str = "ai-parrot",
    ) -> None:
        self._recorders = list(recorders)
        self._cost = cost_calculator
        self._service_name = service_name
        self._cumulative_cost_usd: float = 0.0
        self._has_cost: bool = False
        self._lock = threading.Lock()

    @property
    def recorders(self) -> "list[AbstractLogger]":
        """The configured recorder backends."""
        return self._recorders

    # ------------------------------------------------------------------
    # EventProvider Protocol
    # ------------------------------------------------------------------

    def register(self, registry: "EventRegistry") -> None:
        """Subscribe the usage handler to *registry*.

        Args:
            registry: The ``EventRegistry`` (typically the global registry) to
                attach to.
        """
        registry.subscribe(AfterClientCallEvent, self._on_client_after)

    # ------------------------------------------------------------------
    # Handler
    # ------------------------------------------------------------------

    async def _on_client_after(self, event: AfterClientCallEvent) -> None:
        """Build a ``UsageRecord`` for a successful call and fan it out."""
        provider = resolve_gen_ai_system(event.client_name)
        input_tokens = event.input_tokens or 0
        output_tokens = event.output_tokens or 0

        cost_usd: Optional[float] = None
        cumulative: Optional[float] = None
        if self._cost is not None:
            cost_usd = self._cost.cost_usd(
                provider=provider,
                model=event.model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
            with self._lock:
                if cost_usd is not None:
                    self._cumulative_cost_usd += cost_usd
                    self._has_cost = True
                cumulative = self._cumulative_cost_usd if self._has_cost else None

        trace_id = (
            event.trace_context.trace_id if event.trace_context else None
        )
        record = UsageRecord(
            provider=provider,
            client_name=event.client_name,
            model=event.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            cumulative_cost_usd=cumulative,
            duration_ms=event.duration_ms,
            finish_reason=event.finish_reason,
            trace_id=trace_id,
            service_name=self._service_name,
        )

        for recorder in self._recorders:
            try:
                await recorder.record(record)
            except Exception:  # noqa: BLE001 — one bad backend must not break others
                logger.exception(
                    "Usage recorder %r failed on record; continuing.",
                    getattr(recorder, "name", type(recorder).__name__),
                )

    async def aclose(self) -> None:
        """Close all recorders (flush stateful backends)."""
        for recorder in self._recorders:
            try:
                await recorder.aclose()
            except Exception:  # noqa: BLE001
                logger.exception(
                    "Usage recorder %r failed on aclose.",
                    getattr(recorder, "name", type(recorder).__name__),
                )
