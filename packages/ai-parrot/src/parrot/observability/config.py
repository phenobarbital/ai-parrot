"""ObservabilityConfig — single global configuration for parrot.observability.

FEAT-177 — OpenTelemetry + Cost Observability.
Spec §2 Data Models.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class ObservabilityConfig(BaseModel):
    """Single global configuration for the parrot.observability stack.

    All environment variable lookups are performed by ``setup_telemetry`` via
    navconfig; this model is the authoritative Pydantic-validated shape.

    Attributes:
        enabled: Master switch. When ``False``, ``setup_telemetry`` is a no-op
            and returns ``None`` immediately — no OTel SDK imports triggered.
        service_name: OTel ``service.name`` resource attribute.
        service_version: OTel ``service.version`` resource attribute.
            Defaults to the installed ``ai-parrot`` package version at boot.
        service_instance_id: OTel ``service.instance.id`` resource attribute.
            When ``None``, ``setup_telemetry`` uses ``f"{hostname}-{pid}"``.
        otlp_endpoint: Base URL of the OTLP collector.
            Default: ``http://localhost:4318`` (OpenLIT UI / OTel Collector).
        otlp_protocol: Transport protocol. ``"http/protobuf"`` (default) or
            ``"grpc"``. gRPC requires the ``observability`` extra.
        otlp_headers: Optional extra headers forwarded to the OTLP endpoint
            (e.g. ``{"Authorization": "Bearer <token>"}``.
        enable_traces: Subscribe ``GenAIOpenTelemetrySubscriber``.
        enable_metrics: Subscribe ``MetricsSubscriber``.
        enable_cost_tracking: Build a ``CostCalculator`` and pass it to
            both subscribers.
        enable_openlit: Call ``openlit.init()`` after setting up OTel providers.
            Requires the ``observability-openlit`` extra.
        sampling_ratio: ``TraceIdRatioBased`` sampler rate. Range [0.0, 1.0].
            Default ``1.0`` (sample everything).
        capture_prompts: When ``True``, raw system-prompt hash values are
            included in span attributes. Default ``False`` (PII guard).
        capture_completions: When ``True``, per-chunk span events are added
            by ``GenAIOpenTelemetrySubscriber`` for streaming calls. Default
            ``False`` (PII guard).
        metric_export_interval_ms: ``PeriodicExportingMetricReader`` interval
            in milliseconds. Default 60 000 ms (1 min).
        histogram_buckets: Override the default LLM-tuned histogram bucket
            boundaries (seconds). ``None`` → use ``[0.01, 0.05, 0.1, 0.5,
            1.0, 5.0, 30.0, 60.0]``.
        pricing_override_path: Path to a directory whose ``<provider>.json``
            files are deep-merged over bundled pricing. When ``None``,
            ``setup_telemetry`` reads the ``PARROT_PRICING_PATH`` env var.
    """

    enabled: bool = False
    service_name: str = "ai-parrot"
    service_version: Optional[str] = None
    service_instance_id: Optional[str] = None  # default: hostname-pid

    # Exporter
    otlp_endpoint: str = "http://localhost:4318"
    otlp_protocol: Literal["http/protobuf", "grpc"] = "http/protobuf"
    otlp_headers: dict[str, str] = Field(default_factory=dict)

    # Subscribers
    enable_traces: bool = True
    enable_metrics: bool = True
    enable_cost_tracking: bool = True
    enable_openlit: bool = False

    # Sampling & PII
    sampling_ratio: float = Field(default=1.0, ge=0.0, le=1.0)
    capture_prompts: bool = False       # PII: default off
    capture_completions: bool = False   # PII: default off

    # Metric export tuning
    metric_export_interval_ms: int = 60_000
    histogram_buckets: Optional[list[float]] = None  # None → LLM-tuned defaults

    # Cost pricing override (mirrors PARROT_PRICING_PATH env var)
    pricing_override_path: Optional[str] = None
