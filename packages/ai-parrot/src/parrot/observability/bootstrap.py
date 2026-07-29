"""ensure_observability_bootstrapped — env-driven, idempotent auto-boot.

Called once (lazily, from ``EventEmitterMixin._init_events``) the first time any
bot/client/tool is constructed. When ``OBSERVABILITY_ENABLED=true``, it activates
the usage-recording layer selected by ``OBSERVABILITY_BACKEND`` WITHOUT the user
writing any code:

- ``logging`` (default when enabled and backend unset): structured per-call cost
  logs — zero infra, no OTel SDK import.
- ``prometheus``: lazy ``prometheus_client`` exposition.
- ``otel``: delegates to ``setup_telemetry`` (full OTLP traces + metrics).

Idempotent and near-zero cost when disabled: the very first line is a boolean
check; after the first construction the env is never re-read.
"""

from __future__ import annotations

import atexit
import logging
import threading
from typing import Optional

logger = logging.getLogger("parrot.observability.bootstrap")

# Module-level state. threading.Lock (not asyncio) because this may run during
# synchronous bot/client construction before an event loop exists.
_BOOTSTRAPPED: bool = False
_LOCK = threading.Lock()
_SUBSCRIBER: Optional[object] = None
_SUBSCRIPTION_IDS: list[str] = []
# Guards the atexit flush hook so it is registered at most once per process.
_ATEXIT_REGISTERED: bool = False


def ensure_observability_bootstrapped() -> None:
    """Activate env-driven observability exactly once. Safe to call repeatedly.

    No-op (after recording the decision) when ``OBSERVABILITY_ENABLED`` is not
    truthy. Never raises: any failure is logged at DEBUG and swallowed so it can
    never break bot/client construction.
    """
    global _BOOTSTRAPPED  # noqa: PLW0603
    if _BOOTSTRAPPED:
        return
    with _LOCK:
        if _BOOTSTRAPPED:
            return
        try:
            _do_bootstrap()
        except Exception:  # noqa: BLE001 — observability must never break construction
            logger.debug("Observability auto-boot failed; continuing.", exc_info=True)
        finally:
            _BOOTSTRAPPED = True


def _do_bootstrap() -> None:
    """Read config from env and activate the selected backend."""
    global _SUBSCRIBER  # noqa: PLW0603
    from parrot.observability.config import ObservabilityConfig  # noqa: PLC0415

    config = ObservabilityConfig.from_env()
    if not config.enabled:
        logger.debug("Observability auto-boot: OBSERVABILITY_ENABLED is false.")
        return

    # Traceloop (OpenLLMetry) and OpenLIT are mutually exclusive — both
    # auto-instrument the LLM SDKs and would double-instrument together. Traceloop
    # wins when both are requested (it owns the whole trace pipeline).
    if config.enable_traceloop:
        if config.enable_openlit:
            logger.warning(
                "Both OBSERVABILITY_TRACELOOP and OBSERVABILITY_OPENLIT are set; "
                "using Traceloop and disabling OpenLIT (they are mutually exclusive)."
            )
            config = config.model_copy(update={"enable_openlit": False})
        if config.usage_backend != "traceloop":
            logger.info(
                "Observability auto-boot: enable_traceloop=true → forcing backend "
                "from %r to 'traceloop'.",
                config.usage_backend,
            )
            config = config.model_copy(update={"usage_backend": "traceloop"})
    # OpenLIT requires the global TracerProvider that only the "otel" path builds
    # (so its auto-spans inherit the provider and nest under the caller's span).
    # Escalate to "otel" when the user asked for OpenLIT but left the backend on a
    # lightweight path, so OBSERVABILITY_OPENLIT=true "just works".
    elif config.enable_openlit and config.usage_backend != "otel":
        logger.info(
            "Observability auto-boot: enable_openlit=true → escalating backend "
            "from %r to 'otel'.",
            config.usage_backend,
        )
        config = config.model_copy(update={"usage_backend": "otel"})

    # Resolve "none" → "logging" when explicitly enabled, so OBSERVABILITY_ENABLED
    # alone yields structured cost logs.
    backend = config.usage_backend
    if backend == "none":
        backend = "logging"
        config = config.model_copy(update={"usage_backend": backend})

    if backend == "traceloop":
        from parrot.observability.traceloop_integration import (  # noqa: PLC0415
            setup_traceloop,
        )

        setup_traceloop(config)
        _register_atexit_flush()
        logger.info("Observability auto-boot: Traceloop (OpenLLMetry) backend active.")
        return

    if backend == "otel":
        from parrot.observability.setup import setup_telemetry  # noqa: PLC0415

        setup_telemetry(config)
        _register_atexit_flush()
        logger.info("Observability auto-boot: OTel backend active.")
        return

    # Lightweight pluggable path (logging / prometheus) — no OTel SDK import.
    cost_calc = None
    if config.enable_cost_tracking:
        from parrot.observability.cost.calculator import CostCalculator  # noqa: PLC0415

        cost_calc = CostCalculator(override_path=config.pricing_override_path)

    from parrot.observability.recorders.factory import (  # noqa: PLC0415
        build_recorders_from_config,
    )
    from parrot.observability.recorders.subscriber import (  # noqa: PLC0415
        UsageRecordingSubscriber,
    )

    recorders = build_recorders_from_config(config)
    if not recorders:
        logger.debug(
            "Observability auto-boot: backend=%r produced no recorders.", backend
        )
        return

    subscriber = UsageRecordingSubscriber(
        recorders=recorders,
        cost_calculator=cost_calc,
        service_name=config.service_name,
    )
    from parrot.core.events.lifecycle import (  # noqa: PLC0415
        get_global_registry,
    )

    ids = get_global_registry().add_provider(subscriber)
    _SUBSCRIBER = subscriber
    _SUBSCRIPTION_IDS.extend(ids)
    _register_atexit_flush()
    logger.info(
        "Observability auto-boot: '%s' backend active (cost=%s, service=%s).",
        backend,
        config.enable_cost_tracking,
        config.service_name,
    )


def _register_atexit_flush() -> None:
    """Register a process-exit hook that flushes telemetry. Idempotent.

    Ensures the final ``BatchSpanProcessor`` / ``PeriodicExportingMetricReader``
    batch is exported on graceful shutdown regardless of the entrypoint (gunicorn
    worker, CLI, script). Deterministic flush points (e.g. the autonomous
    orchestrator's ``stop()``) complement — they don't replace — this safety net.
    """
    global _ATEXIT_REGISTERED  # noqa: PLW0603
    if _ATEXIT_REGISTERED:
        return
    atexit.register(shutdown_observability)
    _ATEXIT_REGISTERED = True


def shutdown_observability() -> None:
    """Flush and tear down every active observability path. Idempotent + defensive.

    Aggregates every shutdown surface so callers need not know which backend is
    active: the OTel path (``shutdown_telemetry``), the Traceloop path
    (``shutdown_traceloop``), and the lightweight logging/prometheus path
    (``shutdown_usage_recording``). Safe to call when observability was never
    started; never raises.
    """
    try:
        from parrot.observability.setup import shutdown_telemetry  # noqa: PLC0415

        shutdown_telemetry()
    except Exception:  # noqa: BLE001 — shutdown must never raise
        logger.debug("shutdown_observability: OTel teardown failed.", exc_info=True)

    try:
        from parrot.observability.traceloop_integration import (  # noqa: PLC0415
            shutdown_traceloop,
        )

        shutdown_traceloop()
    except Exception:  # noqa: BLE001
        logger.debug("shutdown_observability: Traceloop teardown failed.", exc_info=True)

    try:
        shutdown_usage_recording()
    except Exception:  # noqa: BLE001
        logger.debug(
            "shutdown_observability: usage-recording teardown failed.", exc_info=True
        )


def shutdown_usage_recording() -> None:
    """Unsubscribe the usage subscriber and close recorders. Idempotent.

    Only affects the lightweight (logging/prometheus) path. The OTel path is
    torn down via ``shutdown_telemetry``.
    """
    global _SUBSCRIBER  # noqa: PLW0603
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
            logger.exception("Error unsubscribing usage recorder.")
        _SUBSCRIPTION_IDS.clear()

    if _SUBSCRIBER is not None:
        aclose = getattr(_SUBSCRIBER, "aclose", None)
        if aclose is not None:
            try:
                import asyncio  # noqa: PLC0415

                try:
                    asyncio.get_running_loop()
                except RuntimeError:
                    asyncio.run(aclose())
                else:
                    # Inside a running loop: schedule fire-and-forget close.
                    asyncio.ensure_future(aclose())  # noqa: RUF006
            except Exception:  # noqa: BLE001
                logger.debug("Error closing usage subscriber.", exc_info=True)
        _SUBSCRIBER = None


def reset_bootstrap_for_tests() -> None:
    """Test-only: reset module state so a fresh bootstrap can run."""
    global _BOOTSTRAPPED, _SUBSCRIBER, _ATEXIT_REGISTERED  # noqa: PLW0603
    shutdown_usage_recording()
    if _ATEXIT_REGISTERED:
        try:
            atexit.unregister(shutdown_observability)
        except Exception:  # noqa: BLE001
            logger.debug("Failed to unregister atexit flush hook.", exc_info=True)
    _BOOTSTRAPPED = False
    _SUBSCRIBER = None
    _ATEXIT_REGISTERED = False
