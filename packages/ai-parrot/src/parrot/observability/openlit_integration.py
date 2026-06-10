"""OpenLIT auto-instrumentation wrapper.

FEAT-177 TASK-1236.

Provides a lazy, idempotent wrapper around ``openlit.init()``. The module-level
sentinel ``_INITIALIZED`` ensures ``openlit.init`` is called at most once per
process even when ``setup_telemetry`` is invoked multiple times.

OpenLIT is lazy-imported inside ``init_openlit`` so users without the
``observability-openlit`` extra are not broken when they disable OpenLIT (the
default: ``config.enable_openlit=False``).

Parent-span contract: because ``setup_telemetry`` installs the global
``TracerProvider`` *before* calling ``init_openlit``, OpenLIT auto-spans
inherit that provider and are automatically children of the caller's active
span — no extra wiring needed.

Spec §3 Module 9.
"""

from __future__ import annotations

import logging

from parrot.observability.config import ObservabilityConfig

logger = logging.getLogger("parrot.observability.openlit")

_INITIALIZED: bool = False


def init_openlit(config: ObservabilityConfig) -> None:
    """Initialize OpenLIT auto-instrumentation. Idempotent.

    On the first call, lazy-imports ``openlit`` and calls ``openlit.init`` with
    the OTLP endpoint and application name from *config*. Subsequent calls are
    no-ops (the sentinel prevents double-init).

    Args:
        config: ``ObservabilityConfig`` instance. ``otlp_endpoint``,
            ``service_name`` and ``openlit_disabled_instrumentors`` are
            forwarded to ``openlit.init``. The skip-list defaults to the
            instrumentors known to break against the installed SDK versions
            (``openai``, ``openai_agents``, ``milvus``, ``fastapi``,
            ``starlette``, ``tornado``) so boot logs stay clean.

    Raises:
        ImportError: If ``openlit`` is not installed. Install with:
            ``pip install 'ai-parrot[observability-openlit]'``.
    """
    global _INITIALIZED  # noqa: PLW0603
    if _INITIALIZED:
        logger.debug("OpenLIT already initialized; skipping.")
        return

    try:
        import openlit  # noqa: PLC0415
    except ImportError as exc:
        raise ImportError(
            "enable_openlit=True requires the 'observability-openlit' extra. "
            "Install with: pip install 'ai-parrot[observability-openlit]'"
        ) from exc

    # Quiet OpenLIT's boot chatter: it logs one INFO line per supported library
    # it scans (most are "not found, skipping") plus provider-reuse lines. Raise
    # the whole ``openlit`` logger family to the configured level (WARNING by
    # default) BEFORE init() so the catalogue scan stays silent. Child loggers
    # (``openlit.otel.*``) with NOTSET level inherit this effective level.
    logging.getLogger("openlit").setLevel(config.openlit_log_level)

    # OpenLIT re-instruments libraries that an existing TracerProvider /
    # instrumentor already covered (it logs "Detected existing TracerProvider,
    # reusing it"), which makes OTel's BaseInstrumentor emit a benign
    # "Attempting to instrument while already instrumented" WARNING from the
    # ``opentelemetry.instrumentation.instrumentor`` logger. Our _INITIALIZED
    # sentinel already prevents double init_openlit(), so this is pure boot
    # noise. Suppress it ONLY for the duration of openlit.init() — never
    # permanently — so genuine double-instrumentation later still surfaces.
    instrumentor_logger = logging.getLogger(
        "opentelemetry.instrumentation.instrumentor"
    )
    previous_level = instrumentor_logger.level
    instrumentor_logger.setLevel(max(config.openlit_log_level, logging.ERROR))
    try:
        openlit.init(
            otlp_endpoint=config.otlp_endpoint,
            application_name=config.service_name,
            disabled_instrumentors=config.openlit_disabled_instrumentors or None,
            # Let our native MetricsSubscriber own the GenAI metrics; OpenLIT
            # reusing our MeterProvider would otherwise register duplicate
            # same-named instruments and trigger OTel "conflicting metrics
            # identities" warnings on every export.
            disable_metrics=config.openlit_disable_metrics,
        )
    finally:
        instrumentor_logger.setLevel(previous_level)
    _INITIALIZED = True
    logger.info(
        "OpenLIT initialized for %s → %s (disabled instrumentors: %s)",
        config.service_name,
        config.otlp_endpoint,
        config.openlit_disabled_instrumentors or "none",
    )


def _reset_for_tests() -> None:
    """Test-only: reset the module-level sentinel.

    Allows unit tests to exercise the initialization path multiple times
    in the same process without process restart.

    Warning:
        NEVER call this in production code. The sentinel mirrors OpenLIT's
        own internal global state; resetting it does not un-initialize OpenLIT.
    """
    global _INITIALIZED  # noqa: PLW0603
    _INITIALIZED = False
