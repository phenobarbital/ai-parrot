---
type: Wiki Entity
title: ObservabilityConfig
id: class:parrot.observability.config.ObservabilityConfig
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Single global configuration for the parrot.observability stack.
---

# ObservabilityConfig

Defined in [`parrot.observability.config`](../summaries/mod:parrot.observability.config.md).

```python
class ObservabilityConfig(BaseModel)
```

Single global configuration for the parrot.observability stack.

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
        Requires the ``observability-openlit`` extra. Intended as the
        production telemetry backend. Mutually exclusive with
        ``enable_traceloop`` (Traceloop wins; OpenLIT is disabled with a
        warning when both are requested).
    enable_traceloop: Activate the OpenLLMetry (Traceloop) backend — a
        simple, content-rich tracing path aimed at local/dev. Requires the
        ``observability-traceloop`` extra. When ``True`` the usage backend is
        forced to ``"traceloop"``: Traceloop owns the OTLP trace pipeline and
        auto-instruments the LLM SDKs (with prompt/completion capture gated by
        ``capture_prompts``/``capture_completions``), while AI-Parrot's native
        span/metric subscribers ride the same global provider — one pipeline,
        no duplicate spans.
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
    usage_backend: Selects the pluggable usage/token/cost recording path.
        ``"none"`` (default) records nothing. ``"logging"`` emits one
        structured log line per LLM call (zero infra). ``"prometheus"``
        exposes counters/histograms on an HTTP endpoint. ``"otel"`` delegates
        to ``setup_telemetry`` (full OTLP traces + metrics). The auto-boot
        (``ensure_observability_bootstrapped``) resolves ``"none"`` to
        ``"logging"`` when ``enabled`` is ``True``.
    usage_log_level: Logging level for the ``logging`` backend's per-call
        line. Default ``logging.INFO``.
    usage_log_logger_name: Logger name for the ``logging`` backend. Default
        ``"parrot.usage"`` (kept distinct from ``parrot.lifecycle`` so the
        cost line is independently filterable).
    prometheus_port: TCP port for the ``prometheus`` backend's exposition
        HTTP server. Default ``9464``.
    prometheus_addr: Bind address for the ``prometheus`` backend's HTTP
        server. Default ``"0.0.0.0"``.

## Methods

- `def from_env(cls) -> 'ObservabilityConfig'` — Build an ``ObservabilityConfig`` from environment variables.
