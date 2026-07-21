"""setup_telemetry() and shutdown_telemetry() — one-call observability boot helpers.

FEAT-177 TASK-1235.

``setup_telemetry(config)`` is the single public entrypoint that:

1. Builds an OTel ``Resource`` (service.name, service.version, service.instance.id,
   parrot.version).
2. Configures a ``TracerProvider`` with ``BatchSpanProcessor`` + ``TraceIdRatioBased``
   sampler and registers it globally.
3. Configures a ``MeterProvider`` with ``PeriodicExportingMetricReader`` + histogram
   ``View`` objects for LLM-optimised bucket boundaries, and registers it globally.
4. Optionally builds a ``CostCalculator`` (respects ``PARROT_PRICING_PATH`` env var).
5. Constructs ``GenAIOpenTelemetrySubscriber`` and/or ``MetricsSubscriber``.
6. Bundles them into ``ParrotTelemetryProvider`` and calls
   ``get_global_registry().add_provider(provider)``.
7. Optionally calls ``openlit.init`` via the TASK-1236 wrapper.

Idempotent: same ``config`` → same provider returned; different ``config`` →
``ConfigurationError``.  ``config.enabled=False`` → immediate ``None`` return with
zero OTel SDK imports.

Spec §3 Module 8, §2 Initialization flow.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import socket
import threading
import uuid
from typing import Optional

from parrot.observability.config import ObservabilityConfig
from parrot.observability.errors import ConfigurationError
from parrot.observability.provider import ParrotTelemetryProvider

logger = logging.getLogger("parrot.observability.setup")

# Module-level state: keyed by SHA-256 hex of the serialised config.
# At most one entry at a time — a different hash raises ConfigurationError.
_STATE: dict[str, ParrotTelemetryProvider] = {}
# Keep references to OTel providers for flush/shutdown.
_TRACER_PROVIDER: Optional[object] = None
_METER_PROVIDER: Optional[object] = None
_SUBSCRIPTION_IDS: list[str] = []

# threading.Lock (not asyncio) guards the idempotency check → construct → write
# sequence on _STATE/_TRACER_PROVIDER/_METER_PROVIDER/_SUBSCRIPTION_IDS.
# threading.Lock is used (not asyncio.Lock) because setup_telemetry may be called
# at import time or in synchronous boot code before an event loop exists.
_SETUP_LOCK = threading.Lock()

# Token-space bucket boundaries for gen_ai.client.token.usage histogram.
# These are NOT seconds; the latency buckets ([0.01..60.0]) are wrong for tokens.
_TOKEN_BUCKETS: list[int] = [
    10, 50, 100, 500, 1000, 2000, 5000, 10000, 50000, 100000
]


def setup_telemetry(
    config: ObservabilityConfig,
) -> Optional[ParrotTelemetryProvider]:
    """Configure OpenTelemetry + cost observability and wire to the global registry.

    Args:
        config: ``ObservabilityConfig`` controlling every aspect of the stack.

    Returns:
        The ``ParrotTelemetryProvider`` registered with the global event registry,
        or ``None`` when ``config.enabled is False``.

    Raises:
        ConfigurationError: When called a second time with a *different* config than
            the first call (hash mismatch). Also raised if a ``SimpleSpanProcessor``
            is detected in the constructed ``TracerProvider``'s processor chain.
        ImportError: When ``config.enable_openlit=True`` but the
            ``observability-openlit`` extra is not installed.
    """
    global _TRACER_PROVIDER, _METER_PROVIDER, _SUBSCRIPTION_IDS  # noqa: PLW0603

    if not config.enabled:
        logger.debug("setup_telemetry: config.enabled=False — returning None.")
        return None

    with _SETUP_LOCK:
        cfg_hash = _hash_config(config)
        if cfg_hash in _STATE:
            logger.debug("setup_telemetry: same config — returning cached provider.")
            return _STATE[cfg_hash]
        if _STATE:
            raise ConfigurationError(
                "setup_telemetry has already been configured with a different "
                "ObservabilityConfig. Call shutdown_telemetry() first to reconfigure."
            )

        # --- Lazy OTel SDK imports (only when enabled=True) ----------------------
        from opentelemetry import metrics as otel_metrics  # noqa: PLC0415
        from opentelemetry import trace as otel_trace  # noqa: PLC0415
        from opentelemetry.sdk.metrics import MeterProvider  # noqa: PLC0415
        from opentelemetry.sdk.metrics.export import (  # noqa: PLC0415
            PeriodicExportingMetricReader,
        )
        from opentelemetry.sdk.metrics.view import (  # noqa: PLC0415
            ExplicitBucketHistogramAggregation,
            View,
        )
        from opentelemetry.sdk.resources import Resource  # noqa: PLC0415
        from opentelemetry.sdk.trace import TracerProvider  # noqa: PLC0415
        from opentelemetry.sdk.trace.export import (  # noqa: PLC0415
            BatchSpanProcessor,
            SimpleSpanProcessor,
        )
        from opentelemetry.sdk.trace.sampling import TraceIdRatioBased  # noqa: PLC0415

        # --- 1. Resource ---------------------------------------------------------
        instance_id = config.service_instance_id or _resolve_instance_id()
        parrot_ver = _get_parrot_version()
        resource = Resource.create(
            {
                "service.name": config.service_name,
                "service.version": config.service_version or "unknown",
                "service.instance.id": instance_id,
                "parrot.version": parrot_ver,
            }
        )

        # --- 2. TracerProvider ---------------------------------------------------
        from parrot.observability.exporters import make_span_exporter  # noqa: PLC0415

        span_exporter = make_span_exporter(config)
        tracer_provider = TracerProvider(
            resource=resource,
            sampler=TraceIdRatioBased(config.sampling_ratio),
        )
        bsp = BatchSpanProcessor(span_exporter)
        tracer_provider.add_span_processor(bsp)
        # Defensive: verify NO SimpleSpanProcessor slipped in via monkey-patching.
        # NOTE: _active_span_processor._span_processors is a private attribute of
        # SynchronousMultiSpanProcessor from opentelemetry-sdk<2.0. This access is
        # intentional and version-pinned to opentelemetry-sdk>=1.25,<2.0 in
        # pyproject.toml. If the SDK renames this in a patch release, the guard
        # degrades gracefully: AttributeError is caught and logged at DEBUG level
        # rather than crashing.
        try:
            for proc in tracer_provider._active_span_processor._span_processors:  # type: ignore[attr-defined]
                if isinstance(proc, SimpleSpanProcessor):
                    raise ConfigurationError(
                        "SimpleSpanProcessor is forbidden in the observability stack "
                        "(spec §5). Use BatchSpanProcessor."
                    )
        except AttributeError:
            logger.debug(
                "setup_telemetry: _active_span_processor._span_processors not found "
                "(OTel SDK internals may have changed); SimpleSpanProcessor guard skipped."
            )
        otel_trace.set_tracer_provider(tracer_provider)
        _TRACER_PROVIDER = tracer_provider

        # --- 3. MeterProvider with histogram Views --------------------------------
        from parrot.observability.exporters import make_metric_exporter  # noqa: PLC0415

        buckets: list[float] = config.histogram_buckets or [
            0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 30.0, 60.0
        ]
        _latency_histogram_names = [
            "gen_ai.client.operation.duration",
            "parrot.tool.execution.duration",
            "parrot.agent.invoke.duration",
        ]
        views = [
            View(
                instrument_name=name,
                aggregation=ExplicitBucketHistogramAggregation(boundaries=buckets),
            )
            for name in _latency_histogram_names
        ]
        # Token usage histogram uses token-space bucket boundaries (not seconds).
        views.append(
            View(
                instrument_name="gen_ai.client.token.usage",
                aggregation=ExplicitBucketHistogramAggregation(
                    boundaries=_TOKEN_BUCKETS
                ),
            )
        )
        metric_exporter = make_metric_exporter(config)
        reader = PeriodicExportingMetricReader(
            metric_exporter,
            export_interval_millis=config.metric_export_interval_ms,
        )
        meter_provider = MeterProvider(
            resource=resource,
            metric_readers=[reader],
            views=views,
        )
        otel_metrics.set_meter_provider(meter_provider)
        _METER_PROVIDER = meter_provider

        # --- 4. CostCalculator (optional) -----------------------------------------
        cost_calc = None
        if config.enable_cost_tracking:
            from parrot.observability.cost.calculator import CostCalculator  # noqa: PLC0415

            override: Optional[str] = config.pricing_override_path
            if override is None:
                try:
                    from navconfig import config as nav_config  # noqa: PLC0415

                    override = nav_config.get("PARROT_PRICING_PATH", fallback=None)
                except ImportError:
                    logger.debug(
                        "navconfig not available; skipping PARROT_PRICING_PATH lookup."
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "navconfig raised an unexpected error during PARROT_PRICING_PATH "
                        "lookup: %s",
                        exc,
                    )
            cost_calc = CostCalculator(override_path=override)

        # --- 5. Subscribers -------------------------------------------------------
        from parrot.observability.subscribers.trace import (  # noqa: PLC0415
            GenAIOpenTelemetrySubscriber,
        )
        from parrot.observability.subscribers.metrics import MetricsSubscriber  # noqa: PLC0415

        trace_sub = (
            GenAIOpenTelemetrySubscriber(
                service_name=config.service_name,
                tracer_provider=tracer_provider,
                cost_calculator=cost_calc,
                capture_completions=config.capture_completions,
            )
            if config.enable_traces
            else None
        )
        metrics_sub = (
            MetricsSubscriber(
                meter_provider=meter_provider,
                service_name=config.service_name,
                histogram_buckets=buckets,
                cost_calculator=cost_calc,
            )
            if config.enable_metrics
            else None
        )

        # --- 6. Bundle + register -------------------------------------------------
        from parrot.core.events.lifecycle import (  # noqa: PLC0415
            get_global_registry,
        )

        provider = ParrotTelemetryProvider(
            trace_subscriber=trace_sub,
            metrics_subscriber=metrics_sub,
        )
        subscription_ids = get_global_registry().add_provider(provider)
        _SUBSCRIPTION_IDS.extend(subscription_ids)

        # --- 7. OpenLIT (lazy) ----------------------------------------------------
        if config.enable_openlit:
            from parrot.observability.openlit_integration import init_openlit  # noqa: PLC0415

            init_openlit(config)

        _STATE[cfg_hash] = provider
        logger.info(
            "setup_telemetry: observability active for '%s' (traces=%s, metrics=%s, "
            "cost=%s, openlit=%s) → %s",
            config.service_name,
            config.enable_traces,
            config.enable_metrics,
            config.enable_cost_tracking,
            config.enable_openlit,
            config.otlp_endpoint,
        )
        return provider


def shutdown_telemetry() -> None:
    """Flush all exporters and clear the setup state. Idempotent.

    Calls ``TracerProvider.shutdown()`` (which flushes ``BatchSpanProcessor``)
    and ``MeterProvider.shutdown()`` (which flushes
    ``PeriodicExportingMetricReader``). Then unregisters all subscriptions from
    the global event registry and clears the module-level cache so
    ``setup_telemetry`` can be called again.

    This function is safe to call when ``setup_telemetry`` was never called, or
    after a previous ``shutdown_telemetry`` — it is fully idempotent.

    Note:
        OpenLIT cannot be safely re-initialized after shutdown. If
        ``setup_telemetry(enable_openlit=True)`` is called again after
        ``shutdown_telemetry()``, the OpenLIT instrumentation will not be
        re-applied. Use ``openlit_integration._reset_for_tests()`` only in
        test contexts.
    """
    global _TRACER_PROVIDER, _METER_PROVIDER, _SUBSCRIPTION_IDS  # noqa: PLW0603

    if _TRACER_PROVIDER is not None:
        try:
            _TRACER_PROVIDER.shutdown()  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            logger.exception("Error shutting down TracerProvider.")
        _TRACER_PROVIDER = None

    if _METER_PROVIDER is not None:
        try:
            _METER_PROVIDER.shutdown()  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            logger.exception("Error shutting down MeterProvider.")
        _METER_PROVIDER = None

    if _SUBSCRIPTION_IDS:
        try:
            from parrot.core.events.lifecycle import (  # noqa: PLC0415
                get_global_registry,
            )

            registry = get_global_registry()
            for sub_id in _SUBSCRIPTION_IDS:
                try:
                    registry.unsubscribe(sub_id)
                except Exception:  # noqa: BLE001
                    logger.debug("Failed to unsubscribe %s (may already be gone).", sub_id)
        except Exception:  # noqa: BLE001
            logger.exception("Error unsubscribing from global registry.")
        _SUBSCRIPTION_IDS.clear()

    _STATE.clear()
    logger.debug("shutdown_telemetry: complete.")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_instance_id() -> str:
    """Return ``f"{hostname}-{pid}"`` or a UUID hex on error."""
    try:
        return f"{socket.gethostname()}-{os.getpid()}"
    except OSError:
        return uuid.uuid4().hex


def _get_parrot_version() -> str:
    """Return the installed ``ai-parrot`` package version, or ``"unknown"``."""
    try:
        from importlib.metadata import version  # noqa: PLC0415

        return version("ai-parrot")
    except Exception:  # noqa: BLE001
        return "unknown"


def _hash_config(config: ObservabilityConfig) -> str:
    """Return a stable SHA-256 hex digest of the serialised *config*."""
    return hashlib.sha256(
        json.dumps(config.model_dump(), sort_keys=True, default=str).encode()
    ).hexdigest()
