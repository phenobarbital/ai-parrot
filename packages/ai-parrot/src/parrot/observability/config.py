"""ObservabilityConfig — single global configuration for parrot.observability.

FEAT-177 — OpenTelemetry + Cost Observability.
Spec §2 Data Models.
"""

from __future__ import annotations

import logging
import os
from typing import Literal, Optional

from pydantic import BaseModel, Field

UsageBackend = Literal["none", "logging", "prometheus", "otel", "traceloop"]


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
    enable_traceloop: bool = False

    # OpenLIT auto-instrumentation skip-list. OpenLIT tries to instrument every
    # supported library it detects; several bundled instrumentors break against
    # newer SDKs (openai 2.x restructured ``Videos`` → ``'Videos' has no
    # attribute 'edit'``; pymilvus→environs trips ``marshmallow.__version_info__``
    # on marshmallow 4.x) or fire even when the SDK is absent (``openai_agents``
    # raises ``DependencyConflict`` when ``openai-agents`` is not installed).
    # These three are non-fatal but log ERROR-level noise on every boot, and
    # AI-Parrot already traces LLM calls via its native GenAI subscriber, so the
    # openai instrumentor is redundant. Forwarded to ``openlit.init(
    # disabled_instrumentors=...)``. Override via ``OBSERVABILITY_OPENLIT_DISABLE``
    # (comma-separated); set to an empty string to disable nothing.
    openlit_disabled_instrumentors: list[str] = Field(
        default_factory=lambda: ["openai", "openai_agents", "milvus"]
    )

    # Sampling & PII
    sampling_ratio: float = Field(default=1.0, ge=0.0, le=1.0)
    capture_prompts: bool = False       # PII: default off
    capture_completions: bool = False   # PII: default off

    # Metric export tuning
    metric_export_interval_ms: int = 60_000
    histogram_buckets: Optional[list[float]] = None  # None → LLM-tuned defaults

    # Cost pricing override (mirrors PARROT_PRICING_PATH env var)
    pricing_override_path: Optional[str] = None

    # Pluggable usage/token/cost recording layer
    usage_backend: UsageBackend = "none"
    usage_log_level: int = logging.INFO
    usage_log_logger_name: str = "parrot.usage"
    prometheus_port: int = 9464
    prometheus_addr: str = "0.0.0.0"

    @classmethod
    def from_env(cls) -> "ObservabilityConfig":
        """Build an ``ObservabilityConfig`` from environment variables.

        Reads values via ``navconfig`` when importable, falling back to
        ``os.environ`` so the logging-only path carries no hard navconfig
        dependency. Absent variables use the model defaults.

        Recognised variables:

        ===========================  ==============================
        Env var                      Field
        ===========================  ==============================
        ``OBSERVABILITY_ENABLED``    ``enabled``
        ``OBSERVABILITY_BACKEND``    ``usage_backend``
        ``OBSERVABILITY_SERVICE_NAME``  ``service_name``
        ``OBSERVABILITY_COST``       ``enable_cost_tracking``
        ``OBSERVABILITY_LOG_LEVEL``  ``usage_log_level``
        ``OBSERVABILITY_SAMPLING``   ``sampling_ratio``
        ``OBSERVABILITY_OPENLIT``    ``enable_openlit``
        ``OBSERVABILITY_TRACELOOP``  ``enable_traceloop``
        ``OBSERVABILITY_CAPTURE_CONTENT``  ``capture_prompts`` + ``capture_completions``
        ``OTEL_EXPORTER_OTLP_ENDPOINT``  ``otlp_endpoint``
        ``OBSERVABILITY_PROM_PORT``  ``prometheus_port``
        ``OBSERVABILITY_PROM_ADDR``  ``prometheus_addr``
        ``PARROT_PRICING_PATH``      ``pricing_override_path``
        ===========================  ==============================

        Returns:
            A validated ``ObservabilityConfig``.
        """
        defaults = cls()
        get = _env_getter()

        values: dict = {
            "enabled": _as_bool(get("OBSERVABILITY_ENABLED"), defaults.enabled),
            "service_name": get("OBSERVABILITY_SERVICE_NAME") or defaults.service_name,
            "enable_cost_tracking": _as_bool(
                get("OBSERVABILITY_COST"), defaults.enable_cost_tracking
            ),
            "enable_openlit": _as_bool(
                get("OBSERVABILITY_OPENLIT"), defaults.enable_openlit
            ),
            "enable_traceloop": _as_bool(
                get("OBSERVABILITY_TRACELOOP"), defaults.enable_traceloop
            ),
            "sampling_ratio": _as_float(
                get("OBSERVABILITY_SAMPLING"), defaults.sampling_ratio
            ),
            "usage_log_level": _as_log_level(
                get("OBSERVABILITY_LOG_LEVEL"), defaults.usage_log_level
            ),
            "prometheus_port": _as_int(
                get("OBSERVABILITY_PROM_PORT"), defaults.prometheus_port
            ),
            "prometheus_addr": get("OBSERVABILITY_PROM_ADDR") or defaults.prometheus_addr,
        }

        backend = get("OBSERVABILITY_BACKEND")
        if backend:
            values["usage_backend"] = backend.strip().lower()

        # Single switch to enable prompt/completion capture (PII gate). Off by
        # default; flip on only in local/dev. Applies to every backend that
        # supports content capture (native span events, OpenLIT, Traceloop).
        capture = get("OBSERVABILITY_CAPTURE_CONTENT")
        if capture is not None:
            on = _as_bool(capture, False)
            values["capture_prompts"] = on
            values["capture_completions"] = on

        endpoint = get("OTEL_EXPORTER_OTLP_ENDPOINT")
        if endpoint:
            values["otlp_endpoint"] = endpoint

        # Comma-separated OpenLIT instrumentor skip-list. An explicitly empty
        # string means "disable nothing" (distinct from unset → use defaults).
        disable = get("OBSERVABILITY_OPENLIT_DISABLE")
        if disable is not None:
            values["openlit_disabled_instrumentors"] = [
                name.strip() for name in disable.split(",") if name.strip()
            ]

        pricing = get("PARROT_PRICING_PATH")
        if pricing:
            values["pricing_override_path"] = pricing

        return cls(**values)


def _env_getter():
    """Return a ``key -> Optional[str]`` getter backed by navconfig or os.environ."""
    try:
        from navconfig import config as nav_config  # noqa: PLC0415

        return lambda key: nav_config.get(key, fallback=os.environ.get(key))
    except Exception:  # noqa: BLE001 — navconfig optional; fall back to os.environ
        return os.environ.get


def _as_bool(raw: Optional[str], default: bool) -> bool:
    """Parse a truthy string (``true/1/yes/on``); fall back to *default*."""
    if raw is None:
        return default
    return str(raw).strip().lower() in {"true", "1", "yes", "on"}


def _as_float(raw: Optional[str], default: float) -> float:
    """Parse a float; fall back to *default* on error/None."""
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _as_int(raw: Optional[str], default: int) -> int:
    """Parse an int; fall back to *default* on error/None."""
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _as_log_level(raw: Optional[str], default: int) -> int:
    """Resolve a level name (``"DEBUG"``) or numeric string to a logging level int."""
    if raw is None or str(raw).strip() == "":
        return default
    token = str(raw).strip().upper()
    if token.isdigit():
        return int(token)
    resolved = logging.getLevelName(token)
    return resolved if isinstance(resolved, int) else default
