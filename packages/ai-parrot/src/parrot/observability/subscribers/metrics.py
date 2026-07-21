"""MetricsSubscriber — OTel counters and histograms for LLM calls.

FEAT-177 TASK-1231. Separate subscriber from ``GenAIOpenTelemetrySubscriber``
so Prometheus-only deployments can receive metrics without span overhead.

Spec §2 Event → Metric mapping and §3 Module 4.

Cardinality whitelist: ONLY the attributes documented per metric may appear in
metric labels. ``user_id``, ``session_id``, prompt/completion content NEVER
appear in metric labels.

Default histogram bucket boundaries (D6): ``[0.01, 0.05, 0.1, 0.5, 1.0,
5.0, 30.0, 60.0]`` seconds — LLM-tuned. Overridable via constructor.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Optional

from parrot.core.events.lifecycle.events import (
    AfterClientCallEvent,
    AfterInvokeEvent,
    AfterToolCallEvent,
    BeforeClientCallEvent,
    ClientCallFailedEvent,
    InvokeFailedEvent,
    ToolCallFailedEvent,
)
from parrot.observability.attributes import resolve_gen_ai_system

if TYPE_CHECKING:
    from parrot.core.events.lifecycle import EventRegistry
    from parrot.observability.cost.calculator import CostCalculator

logger = logging.getLogger(__name__)

# LLM-tuned default histogram bucket boundaries (seconds) per D6 resolution.
_DEFAULT_BUCKETS: list[float] = [0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 30.0, 60.0]

# Token-space bucket boundaries for gen_ai.client.token.usage histogram.
# These are in tokens (not seconds) — latency buckets are inappropriate here.
# OTel View wiring is done in setup_telemetry() using these same boundaries.
_TOKEN_BUCKETS: list[int] = [
    10, 50, 100, 500, 1000, 2000, 5000, 10000, 50000, 100000
]


class MetricsSubscriber:
    """OTel counter and histogram subscriber for LLM / tool / invoke events.

    Implements ``EventProvider`` Protocol: ``register(registry)`` is
    synchronous per provider.py:45.

    ``ClientStreamChunkEvent`` is NEVER subscribed — chunks must not update
    metrics (fire-and-forget streaming path; cardinality guard).

    Args:
        meter_provider: Optional pre-built OTel ``MeterProvider``. When
            ``None``, the global provider is used.
        service_name: Used as the OTel meter name / ``service.name``.
        histogram_buckets: Override the default LLM-tuned bucket boundaries
            (seconds). When ``None``, uses ``_DEFAULT_BUCKETS``.
        cost_calculator: Optional ``CostCalculator`` for ``gen_ai.client.cost.total``.
    """

    def __init__(
        self,
        *,
        meter_provider: Optional[Any] = None,
        service_name: str = "ai-parrot",
        histogram_buckets: Optional[list[float]] = None,
        cost_calculator: Optional["CostCalculator"] = None,
    ) -> None:
        try:
            from opentelemetry import metrics  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "MetricsSubscriber requires the 'observability' extra. "
                "Install with: pip install 'ai-parrot[observability]'"
            ) from exc

        from opentelemetry import metrics as otel_metrics
        meter = (
            meter_provider.get_meter(service_name)
            if meter_provider is not None
            else otel_metrics.get_meter_provider().get_meter(service_name)
        )
        self._cost = cost_calculator
        self._buckets: list[float] = histogram_buckets or list(_DEFAULT_BUCKETS)

        # ------------------------------------------------------------------
        # Counters
        # ------------------------------------------------------------------
        self._client_request_count = meter.create_counter(
            "gen_ai.client.request.count",
            description="Number of LLM API requests.",
        )
        self._client_error_count = meter.create_counter(
            "gen_ai.client.error.count",
            description="Number of LLM API errors.",
        )
        self._client_cost_total = meter.create_counter(
            "gen_ai.client.cost.total",
            unit="USD",
            description="Total estimated cost of LLM API calls in USD.",
        )
        self._tool_failure_count = meter.create_counter(
            "parrot.tool.failure.count",
            description="Number of tool execution failures.",
        )
        self._invoke_failure_count = meter.create_counter(
            "parrot.agent.invoke.failure.count",
            description="Number of agent invoke failures.",
        )

        # ------------------------------------------------------------------
        # Histograms
        # Bucket configuration is done via OTel Views in setup_telemetry
        # (TASK-1235); self._buckets exposed for that wiring.
        # ------------------------------------------------------------------
        self._client_op_duration = meter.create_histogram(
            "gen_ai.client.operation.duration",
            unit="s",
            description="Duration of LLM API call in seconds.",
        )
        self._client_token_usage = meter.create_histogram(
            "gen_ai.client.token.usage",
            unit="tokens",
            description="Token usage per LLM API call (recorded twice: input + output).",
        )
        self._tool_exec_duration = meter.create_histogram(
            "parrot.tool.execution.duration",
            unit="s",
            description="Duration of tool execution in seconds.",
        )
        self._invoke_duration = meter.create_histogram(
            "parrot.agent.invoke.duration",
            unit="s",
            description="Duration of agent invoke in seconds.",
        )

    @property
    def buckets(self) -> list[float]:
        """Return the histogram bucket boundaries (seconds).

        Exposed so ``setup_telemetry`` can wire OTel ``View`` objects.
        """
        return self._buckets

    # ------------------------------------------------------------------
    # EventProvider Protocol
    # ------------------------------------------------------------------

    def register(self, registry: "EventRegistry") -> None:
        """Subscribe all metric handlers to *registry*.

        Args:
            registry: The ``EventRegistry`` to attach to.
        """
        registry.subscribe(BeforeClientCallEvent, self._on_client_before)
        registry.subscribe(AfterClientCallEvent, self._on_client_after)
        registry.subscribe(ClientCallFailedEvent, self._on_client_fail)
        registry.subscribe(AfterToolCallEvent, self._on_tool_after)
        registry.subscribe(ToolCallFailedEvent, self._on_tool_fail)
        registry.subscribe(AfterInvokeEvent, self._on_invoke_after)
        registry.subscribe(InvokeFailedEvent, self._on_invoke_fail)
        # NOTE: ClientStreamChunkEvent is NEVER subscribed.

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    async def _on_client_before(self, event: BeforeClientCallEvent) -> None:
        """Count outgoing LLM API request."""
        system = resolve_gen_ai_system(event.client_name)
        # FEAT-228: metrics must always carry a string value for parrot.agent.name
        # (OTel label sets must be stable per series); spans omit the attribute when
        # agent_name is None instead — see attributes.py for the span-side handling.
        self._client_request_count.add(
            1,
            attributes={
                "gen_ai.system": system,
                "gen_ai.provider.name": system,  # new SemConv key — current OpenLIT reads this
                "gen_ai.request.model": event.model,
                "parrot.agent.name": event.agent_name or "unknown",  # FEAT-228
            },
        )

    async def _on_client_after(self, event: AfterClientCallEvent) -> None:
        """Record operation duration, token usage, and optional cost."""
        system = resolve_gen_ai_system(event.client_name)
        # FEAT-228: metrics must always carry a string value for parrot.agent.name
        # (OTel label sets must be stable per series); spans omit the attribute when
        # agent_name is None instead — see attributes.py for the span-side handling.
        base = {
            "gen_ai.system": system,
            "gen_ai.provider.name": system,  # new SemConv key — current OpenLIT reads this
            "gen_ai.response.model": event.model,
            "parrot.agent.name": event.agent_name or "unknown",  # FEAT-228
        }

        # Operation duration histogram
        self._client_op_duration.record(
            event.duration_ms / 1000.0,
            attributes={**base, "gen_ai.operation.name": "chat"},
        )

        # Token usage histogram — recorded TWICE (input + output)
        if event.input_tokens is not None:
            self._client_token_usage.record(
                event.input_tokens,
                attributes={**base, "gen_ai.token.type": "input"},
            )
        if event.output_tokens is not None:
            self._client_token_usage.record(
                event.output_tokens,
                attributes={**base, "gen_ai.token.type": "output"},
            )

        # Cost counter — only when calculator provides a value
        if self._cost is not None:
            cost = self._cost.cost_usd(
                provider=system,
                model=event.model,
                input_tokens=event.input_tokens or 0,
                output_tokens=event.output_tokens or 0,
            )
            if cost is not None:
                self._client_cost_total.add(cost, attributes=base)

    async def _on_client_fail(self, event: ClientCallFailedEvent) -> None:
        """Count LLM API errors by error type."""
        system = resolve_gen_ai_system(event.client_name)
        # FEAT-228: metrics must always carry a string value for parrot.agent.name
        # (OTel label sets must be stable per series); spans omit the attribute when
        # agent_name is None instead — see attributes.py for the span-side handling.
        self._client_error_count.add(
            1,
            attributes={
                "gen_ai.system": system,
                "gen_ai.provider.name": system,  # new SemConv key — current OpenLIT reads this
                "error.type": event.error_type,
                "parrot.agent.name": event.agent_name or "unknown",  # FEAT-228
            },
        )

    async def _on_tool_after(self, event: AfterToolCallEvent) -> None:
        """Record tool execution duration."""
        self._tool_exec_duration.record(
            event.duration_ms / 1000.0,
            attributes={"parrot.tool.name": event.tool_name},
        )

    async def _on_tool_fail(self, event: ToolCallFailedEvent) -> None:
        """Count tool failures by tool name and error type."""
        self._tool_failure_count.add(
            1,
            attributes={
                "parrot.tool.name": event.tool_name,
                "error.type": event.error_type,
            },
        )

    async def _on_invoke_after(self, event: AfterInvokeEvent) -> None:
        """Record agent invoke duration."""
        self._invoke_duration.record(
            event.duration_ms / 1000.0,
            attributes={
                "parrot.agent.name": event.agent_name,
                "parrot.invoke.method": event.method,
            },
        )

    async def _on_invoke_fail(self, event: InvokeFailedEvent) -> None:
        """Count agent invoke failures."""
        self._invoke_failure_count.add(
            1,
            attributes={
                "parrot.agent.name": event.agent_name,
                "error.type": event.error_type,
            },
        )
