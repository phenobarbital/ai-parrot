"""ensure_observability_bootstrapped — env-driven, idempotent auto-boot.

Invoked on every ``EventEmitterMixin._init_events()`` — i.e. on each bot/client/
tool construction — through the injectable bootstrap hook that
``parrot.core.events.lifecycle`` installs via
``navigator_eventbus.lifecycle.mixin.set_bootstrap_hook`` (FEAT-725). This
function is idempotent, which that hook contract requires: the first call does
the work, every later call returns on the ``_BOOTSTRAPPED`` check.

When ``OBSERVABILITY_ENABLED=true``, it activates
the usage-recording layer selected by ``OBSERVABILITY_BACKEND`` WITHOUT the user
writing any code:

- ``logging`` (default when enabled and backend unset): structured per-call cost
  logs — zero infra, no OTel SDK import.
- ``prometheus``: lazy ``prometheus_client`` exposition.
- ``otel``: delegates to ``setup_telemetry`` (full OTLP traces + metrics).

FEAT-462: ``OBSERVABILITY_OPENLIT_RECORDER=true`` additively enables
``OpenLitUsageRecorder`` on top of the ``logging``/``prometheus`` path (via
``build_recorders_from_config``) — pushing usage as GenAI SemConv OTel spans
to an OpenLIT endpoint without requiring the ``otel`` backend.

Idempotent and near-zero cost when disabled: the very first line is a boolean
check; after the first construction the env is never re-read.
"""

from __future__ import annotations

import atexit
import logging
import os
import threading
from typing import Optional

logger = logging.getLogger("parrot.observability.bootstrap")

# Module-level state. threading.Lock (not asyncio) because this may run during
# synchronous bot/client construction before an event loop exists.
_BOOTSTRAPPED: bool = False
_LOCK = threading.Lock()
_SUBSCRIBER: Optional[object] = None
_SUBSCRIPTION_IDS: list[str] = []
_SHUTDOWN_TASKS: set = set()  # strong refs so a scheduled fan-out close is not garbage-collected
# Guards the atexit flush hook so it is registered at most once per process.
_ATEXIT_REGISTERED: bool = False


def ensure_observability_bootstrapped() -> None:
    """Activate env-driven observability exactly once. Safe to call repeatedly.

    No-op (after recording the decision) when ``OBSERVABILITY_ENABLED`` is not
    truthy. A failure of the local observability layer is logged at ERROR and
    swallowed, so it can never break bot/client construction.

    Raises:
        Exception: whatever ``setup_event_fanout()`` raises. Invalid durable
            fan-out configuration is deliberately a startup error, so it is
            logged at ERROR and re-raised; ``_BOOTSTRAPPED`` stays ``False``
            and the next construction retries. The ERROR record matters
            because the ``EventEmitterMixin`` hook site that calls this
            swallows a raising hook at DEBUG.
    """
    global _BOOTSTRAPPED  # noqa: PLW0603
    if _BOOTSTRAPPED:
        return
    with _LOCK:
        if _BOOTSTRAPPED:
            return
        if _event_fanout_enabled():
            from parrot.observability.fanout import setup_event_fanout  # noqa: PLC0415

            # Invalid durable fan-out configuration is a startup error. This is
            # deliberately outside the best-effort local-observability guard —
            # but logged at error first (FEAT-725): the EventEmitterMixin hook
            # site swallows a raising hook at DEBUG, so without this the
            # misconfiguration would be completely silent in production.
            try:
                setup_event_fanout()
            except Exception:
                logger.error(
                    "Durable event fan-out setup failed; PARROT_EVENT_FANOUT_ENABLED "
                    "is set but no lifecycle event will reach the bus.",
                    exc_info=True,
                )
                raise
        try:
            _do_bootstrap()
        except Exception:  # noqa: BLE001 — observability must never break construction
            logger.error("Observability auto-boot failed; continuing.", exc_info=True)
        finally:
            _BOOTSTRAPPED = True


def _event_fanout_enabled() -> bool:
    """Return whether durable event fan-out is explicitly enabled."""
    try:
        from navconfig import config as nav_config  # noqa: PLC0415

        value = nav_config.get(
            "PARROT_EVENT_FANOUT_ENABLED",
            fallback=os.environ.get("PARROT_EVENT_FANOUT_ENABLED"),
        )
    except Exception:  # noqa: BLE001 — navconfig is optional on lightweight paths
        value = os.environ.get("PARROT_EVENT_FANOUT_ENABLED")
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _do_bootstrap() -> None:
    """Read config from env and activate the selected backend."""
    global _SUBSCRIBER  # noqa: PLW0603
    from parrot.observability.config import ObservabilityConfig  # noqa: PLC0415

    config = ObservabilityConfig.from_env()
    if not config.enabled:
        logger.debug("Observability auto-boot: OBSERVABILITY_ENABLED is false.")
        return

    # FEAT-462: the enable_traceloop/enable_openlit mutual-exclusivity and
    # backend-escalation branching that used to live here is removed —
    # OpenLIT and Traceloop are deprecated, no-op flags now (see
    # ObservabilityConfig._warn_deprecated_flags). usage_backend="traceloop"
    # is already remapped to "otel" (with a deprecation log) by that same
    # model_validator, so no local escalation logic is needed.

    # Resolve "none" → "logging" when explicitly enabled, so OBSERVABILITY_ENABLED
    # alone yields structured cost logs.
    backend = config.usage_backend
    if backend == "none":
        backend = "logging"
        config = config.model_copy(update={"usage_backend": backend})

    if backend == "otel":
        from parrot.observability.setup import setup_telemetry  # noqa: PLC0415

        setup_telemetry(config)
        _register_atexit_flush()
        logger.info("Observability auto-boot: OTel backend active.")
        if config.openlit_recorder_endpoint:
            # FEAT-462: the OpenLitUsageRecorder fan-out only wires in on
            # the lightweight (logging/prometheus) path below — the otel
            # backend returns here before reaching it. The OTel trace
            # pipeline already carries cost/usage data as span attributes,
            # so this is intentional, not a bug; log it so a user who set
            # OBSERVABILITY_OPENLIT_RECORDER expecting the separate usage-
            # span fan-out isn't left silently guessing why it never fires.
            logger.debug(
                "Observability auto-boot: openlit_recorder_endpoint=%r is "
                "set but ignored on the 'otel' backend path — "
                "OpenLitUsageRecorder only activates on the lightweight "
                "(logging/prometheus) path. The otel TracerProvider "
                "already carries usage/cost data as span attributes.",
                config.openlit_recorder_endpoint,
            )
        return

    # Lightweight pluggable path (logging / prometheus) — no OTel SDK import.
    cost_calc = None
    if config.enable_cost_tracking:
        from parrot.observability.cost.calculator import CostCalculator  # noqa: PLC0415

        cost_calc = CostCalculator(override_path=config.pricing_override_path)
        from parrot.observability.cost import set_shared_cost_calculator  # noqa: PLC0415

        set_shared_cost_calculator(cost_calc)

    from parrot.observability.recorders.factory import (  # noqa: PLC0415
        build_recorders_from_config,
    )
    from parrot.observability.recorders.subscriber import (  # noqa: PLC0415
        UsageRecordingSubscriber,
    )

    recorders = build_recorders_from_config(config)
    if not recorders:
        logger.debug("Observability auto-boot: backend=%r produced no recorders.", backend)
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
    active: the OTel path (``shutdown_telemetry``) and the lightweight
    logging/prometheus/openlit-recorder path (``shutdown_usage_recording``).
    Safe to call when observability was never started; never raises.
    """
    try:
        from parrot.observability.setup import shutdown_telemetry  # noqa: PLC0415

        shutdown_telemetry()
    except Exception:  # noqa: BLE001 — shutdown must never raise
        logger.debug("shutdown_observability: OTel teardown failed.", exc_info=True)

    try:
        shutdown_usage_recording()
    except Exception:  # noqa: BLE001
        logger.debug("shutdown_observability: usage-recording teardown failed.", exc_info=True)


def shutdown_usage_recording() -> None:
    """Unsubscribe the usage subscriber and close recorders. Idempotent.

    Only affects the lightweight (logging/prometheus) path. The OTel path is
    torn down via ``shutdown_telemetry``.
    """
    global _SUBSCRIBER  # noqa: PLW0603
    try:
        from parrot.observability.fanout import shutdown_event_fanout  # noqa: PLC0415

        import asyncio  # noqa: PLC0415

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(shutdown_event_fanout())
        else:
            _task = asyncio.ensure_future(shutdown_event_fanout())
            _SHUTDOWN_TASKS.add(_task)
            _task.add_done_callback(_SHUTDOWN_TASKS.discard)
    except Exception:  # noqa: BLE001 — shutdown must never raise
        logger.debug("Error closing event fan-out bus.", exc_info=True)

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

    from parrot.observability.cost import set_shared_cost_calculator  # noqa: PLC0415

    set_shared_cost_calculator(None)
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
