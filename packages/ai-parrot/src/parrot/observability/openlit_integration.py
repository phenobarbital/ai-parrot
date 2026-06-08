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
            (``openai``, ``openai_agents``, ``milvus``) so boot logs stay clean.

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

    openlit.init(
        otlp_endpoint=config.otlp_endpoint,
        application_name=config.service_name,
        disabled_instrumentors=config.openlit_disabled_instrumentors or None,
    )
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
