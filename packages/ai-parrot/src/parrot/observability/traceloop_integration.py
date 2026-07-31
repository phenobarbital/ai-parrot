"""OpenLLMetry (Traceloop) backend — simple, content-rich tracing for local/dev.

This is the sibling of ``openlit_integration``: a lazy, idempotent wrapper around
``traceloop.sdk.Traceloop.init`` plus a ``setup_traceloop`` helper that wires
AI-Parrot's native span/metric subscribers onto the global provider Traceloop
installs — so a single OTLP pipeline carries BOTH Traceloop's SDK-level spans
(with prompt/completion capture) AND AI-Parrot's agent/tool/client spans + usage
metrics, with no duplicated spans.

Why a separate owner (vs. OpenLIT, which layers on ``setup_telemetry``):
``Traceloop.init`` reuses an existing real ``TracerProvider`` if one is set, else
creates its own and registers it globally (see ``init_tracer_provider`` in
traceloop-sdk). We therefore let Traceloop own the pipeline and attach our
subscribers afterwards via the global provider — running ``setup_telemetry`` too
would add a second exporter and double-export every span.

OpenLIT and Traceloop are mutually exclusive at runtime (the auto-boot disables
OpenLIT when Traceloop is requested). Install with:
``pip install 'ai-parrot[observability,observability-traceloop]'``.
"""

from __future__ import annotations

import logging
import os

from parrot.observability.config import ObservabilityConfig

logger = logging.getLogger("parrot.observability.traceloop")

_INITIALIZED: bool = False
_SUBSCRIPTION_IDS: list[str] = []


def init_traceloop(config: ObservabilityConfig) -> None:
    """Initialize the Traceloop SDK (OpenLLMetry). Idempotent.

    Sets ``TRACELOOP_TRACE_CONTENT`` from the PII-gate flags BEFORE init (the
    instrumentations read it at import/instrument time), then lazy-imports
    ``traceloop.sdk`` and calls ``Traceloop.init`` pointing at ``otlp_endpoint``.
    Subsequent calls are no-ops.

    Args:
        config: ``ObservabilityConfig``. ``service_name`` → ``app_name``,
            ``otlp_endpoint`` → ``api_endpoint``; ``capture_prompts`` /
            ``capture_completions`` gate prompt/completion capture.

    Raises:
        ImportError: If ``traceloop-sdk`` is not installed. Install with:
            ``pip install 'ai-parrot[observability-traceloop]'``.
    """
    global _INITIALIZED  # noqa: PLW0603
    if _INITIALIZED:
        logger.debug("Traceloop already initialized; skipping.")
        return

    # PII gate: capture content only when explicitly enabled (local/dev).
    capture = bool(config.capture_prompts or config.capture_completions)
    os.environ["TRACELOOP_TRACE_CONTENT"] = "true" if capture else "false"
    # Don't let the SDK phone home its own anonymous usage telemetry.
    os.environ.setdefault("TRACELOOP_TELEMETRY", "false")

    try:
        from traceloop.sdk import Traceloop  # noqa: PLC0415
    except ImportError as exc:
        raise ImportError(
            "enable_traceloop=True requires the 'observability-traceloop' extra. "
            "Install with: pip install 'ai-parrot[observability-traceloop]'"
        ) from exc

    Traceloop.init(
        app_name=config.service_name,
        api_endpoint=config.otlp_endpoint,
        api_key=None,                 # local/OTLP collector — no Traceloop cloud key
        disable_batch=True,           # immediate export — best for local/dev
        telemetry_enabled=False,      # no SDK phone-home
        headers=dict(config.otlp_headers),
        resource_attributes={"parrot.observability.backend": "traceloop"},
    )
    _INITIALIZED = True
    logger.info(
        "Traceloop (OpenLLMetry) initialized for %s → %s (capture_content=%s)",
        config.service_name,
        config.otlp_endpoint,
        capture,
    )


def setup_traceloop(config: ObservabilityConfig) -> None:
    """Activate the full ``traceloop`` backend. Idempotent.

    1. ``init_traceloop`` — Traceloop owns the OTLP trace pipeline + LLM SDK
       auto-instrumentation (content per the PII gate).
    2. Register AI-Parrot's native subscribers (``GenAIOpenTelemetrySubscriber``
       and, when ``enable_metrics``, ``MetricsSubscriber``) on the GLOBAL provider
       Traceloop installed, so agent/tool/client spans and usage/cost metrics flow
       through the same single pipeline — no duplicate export.

    Args:
        config: ``ObservabilityConfig`` with ``usage_backend == "traceloop"``.
    """
    if config.usage_backend != "traceloop":
        logger.debug("setup_traceloop called with backend=%r — skipping.", config.usage_backend)
        return

    init_traceloop(config)

    # Native subscribers attach to the global providers (tracer/meter) that
    # Traceloop set up. Passing provider=None makes them resolve the globals.
    cost_calc = None
    if config.enable_cost_tracking:
        from parrot.observability.cost.calculator import CostCalculator  # noqa: PLC0415

        cost_calc = CostCalculator(override_path=config.pricing_override_path)

    from parrot.observability.provider import ParrotTelemetryProvider  # noqa: PLC0415

    trace_sub = None
    if config.enable_traces:
        from parrot.observability.subscribers.trace import (  # noqa: PLC0415
            GenAIOpenTelemetrySubscriber,
        )

        trace_sub = GenAIOpenTelemetrySubscriber(
            service_name=config.service_name,
            tracer_provider=None,  # global (Traceloop's)
            cost_calculator=cost_calc,
            capture_completions=config.capture_completions,
        )

    metrics_sub = None
    if config.enable_metrics:
        from parrot.observability.subscribers.metrics import (  # noqa: PLC0415
            MetricsSubscriber,
        )

        metrics_sub = MetricsSubscriber(
            meter_provider=None,  # global (Traceloop's)
            service_name=config.service_name,
            cost_calculator=cost_calc,
        )

    if trace_sub is None and metrics_sub is None:
        logger.debug("setup_traceloop: no native subscribers enabled.")
        return

    from parrot.core.events.lifecycle import (  # noqa: PLC0415
        get_global_registry,
    )

    provider = ParrotTelemetryProvider(
        trace_subscriber=trace_sub,
        metrics_subscriber=metrics_sub,
    )
    ids = get_global_registry().add_provider(provider)
    _SUBSCRIPTION_IDS.extend(ids)
    logger.info(
        "Traceloop backend active: native subscribers wired (traces=%s, metrics=%s).",
        config.enable_traces,
        config.enable_metrics,
    )


def shutdown_traceloop() -> None:
    """Flush Traceloop and unregister native subscribers. Idempotent + defensive.

    With ``disable_batch=True`` spans export eagerly and Traceloop also registers
    its own atexit flush, so this is a best-effort belt-and-braces teardown.
    """
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
                    logger.debug("Failed to unsubscribe %s.", sub_id)
        except Exception:  # noqa: BLE001
            logger.debug("Error unsubscribing Traceloop native subscribers.", exc_info=True)
        _SUBSCRIPTION_IDS.clear()

    try:
        from traceloop.sdk.tracing.tracing import TracerWrapper  # noqa: PLC0415

        if getattr(TracerWrapper, "instance", None) is not None:
            TracerWrapper().flush()
    except Exception:  # noqa: BLE001 — flush is best-effort; never raise on shutdown
        logger.debug("Traceloop flush skipped.", exc_info=True)


def _reset_for_tests() -> None:
    """Test-only: reset module state so init can be exercised repeatedly.

    Warning:
        NEVER call in production. Does not un-initialize Traceloop's own global
        SDK state; it only resets this wrapper's sentinel.
    """
    global _INITIALIZED  # noqa: PLW0603
    _INITIALIZED = False
    _SUBSCRIPTION_IDS.clear()
