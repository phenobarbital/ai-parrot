"""OpenLitUsageRecorder — pushes UsageRecords as GenAI SemConv OTel spans.

FEAT-462 — Unified Telemetry Bus.

Replaces the ``openlit`` SDK's usage tracking (monkey-patching) without
requiring the SDK as a dependency: this recorder owns a *private*
``TracerProvider`` + OTLP span exporter, so it can push usage spans to a
different endpoint (typically an OpenLIT collector) than the main trace
pipeline, independent of whether the main pipeline is enabled at all.

Spec §3 Module 4.
"""

from __future__ import annotations

import logging

from parrot.observability.recorders.base import AbstractLogger
from parrot.observability.recorders.models import UsageRecord

logger = logging.getLogger(__name__)


class OpenLitUsageRecorder(AbstractLogger):
    """Push ``UsageRecord``s as GenAI SemConv OTel spans to an OTLP endpoint.

    Uses a private ``TracerProvider`` (never the global one) so the recorder
    can target a different endpoint (e.g. OpenLIT) than the main trace
    pipeline, and so it works standalone even when the full OTel trace
    pipeline is disabled.

    Never includes prompt/completion content — only the fields already
    present on ``UsageRecord`` (PII contract).

    Attributes:
        name: Recorder identifier used in logs/diagnostics.
    """

    name: str = "openlit"

    def __init__(
        self,
        *,
        endpoint: str,
        headers: dict[str, str] | None = None,
        service_name: str = "ai-parrot",
        protocol: str = "http/protobuf",
    ) -> None:
        """Build the recorder's private tracer provider + OTLP exporter.

        Args:
            endpoint: OTLP base URL to push usage spans to.
            headers: Optional extra headers forwarded to the OTLP endpoint.
            service_name: OTel ``service.name`` resource attribute.
            protocol: Transport protocol — ``"http/protobuf"`` (default) or
                ``"grpc"``.

        Raises:
            ImportError: When ``protocol="grpc"`` is requested but the gRPC
                exporter package is not installed.
        """
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        if protocol == "grpc":
            try:
                from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                    OTLPSpanExporter as GrpcSpanExporter,
                )
            except ImportError as exc:
                raise ImportError(
                    "gRPC OTLP exporter requires the 'observability' extra "
                    "with grpcio. Install with: pip install "
                    "'ai-parrot[observability]' grpcio"
                ) from exc
            exporter = GrpcSpanExporter(
                endpoint=endpoint,
                headers=tuple((headers or {}).items()) or None,
            )
        else:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )

            exporter = OTLPSpanExporter(
                endpoint=endpoint,
                headers=headers or None,
            )

        resource = Resource.create({"service.name": service_name})
        self._provider = TracerProvider(resource=resource)
        self._provider.add_span_processor(BatchSpanProcessor(exporter))
        self._tracer = self._provider.get_tracer("parrot.usage")

    async def record(self, record: UsageRecord) -> None:
        """Create a ``"parrot.usage"`` span with GenAI SemConv attributes.

        Args:
            record: The per-call ``UsageRecord`` to emit as a span. Only
                non-content fields are used — no prompt/completion text.
        """
        span = self._tracer.start_span("parrot.usage")
        try:
            span.set_attribute("gen_ai.provider.name", record.provider)
            span.set_attribute("gen_ai.request.model", record.model)
            span.set_attribute("gen_ai.operation.name", "chat")
            span.set_attribute("gen_ai.usage.input_tokens", record.input_tokens)
            span.set_attribute("gen_ai.usage.output_tokens", record.output_tokens)
            if record.cost_usd is not None:
                span.set_attribute("gen_ai.usage.cost", record.cost_usd)
                span.set_attribute("parrot.cost.usd", record.cost_usd)
            if record.trace_id:
                span.set_attribute("parrot.trace_id", record.trace_id)
            span.set_attribute("service.name", record.service_name)
        finally:
            span.end()

    async def aclose(self) -> None:
        """Flush pending spans and shut down the private provider.

        Resilient to double-call and provider errors — logs a warning
        instead of raising, matching the ``AbstractLogger`` shutdown
        contract (called from best-effort shutdown paths).
        """
        try:
            self._provider.force_flush()
            self._provider.shutdown()
        except Exception as exc:  # noqa: BLE001 — best-effort shutdown
            logger.warning("Error shutting down OpenLIT recorder: %s", exc)
