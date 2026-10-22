"""FEAT-710 — fan-out of the four usage lifecycle events to a durable EventBus.

Native ``forward_to_bus`` on top of navigator-eventbus FEAT-711. ai-parrot only
publishes; the consumer (NVP-505) lives outside this package.
"""

from __future__ import annotations

import logging
import os
import socket
from pathlib import Path
from typing import Any, Optional

from navigator_eventbus import EventBus

from parrot.core.events.lifecycle import get_global_registry
from parrot.core.events.lifecycle.events import (
    AfterClientCallEvent,
    AfterInvokeEvent,
    ClientCallFailedEvent,
    InvokeFailedEvent,
)
from parrot.observability.cost import ensure_shared_cost_calculator

logger = logging.getLogger(__name__)

FORWARD_DENYLIST: frozenset[str] = frozenset({"error_message"})
FORWARDED_EVENTS: tuple[type, ...] = (
    AfterInvokeEvent,
    InvokeFailedEvent,
    AfterClientCallEvent,
    ClientCallFailedEvent,
)

_BUS: Any = None
_SUB_IDS: list[str] = []


def redact_usage_event(event: Any) -> Optional[dict[str, Any]]:
    """Return a safe bus payload for usage events, or ``None`` for other events."""
    if not isinstance(event, FORWARDED_EVENTS):
        return None
    return {key: value for key, value in event.to_dict().items() if key not in FORWARD_DENYLIST}


async def _noop(_event: Any) -> None:
    """Receive a lifecycle event while registry-native forwarding publishes it."""


def _config_value(name: str, fallback: Optional[str] = None) -> Optional[str]:
    """Read a fan-out setting through navconfig with an environment fallback."""
    try:
        from navconfig import config as nav_config  # noqa: PLC0415

        value = nav_config.get(name, fallback=os.environ.get(name, fallback))
    except Exception:  # noqa: BLE001 — environment remains the dependency-free fallback
        value = os.environ.get(name, fallback)
    return str(value) if value is not None else None


def _outbox_path() -> Path:
    """Return the process outbox path after validating its configured directory."""
    configured = _config_value("PARROT_EVENT_FANOUT_OUTBOX_DIR")
    if not configured:
        raise RuntimeError("PARROT_EVENT_FANOUT_OUTBOX_DIR is required when event fan-out is enabled")

    directory = Path(configured).expanduser()
    if not directory.is_dir() or not os.access(directory, os.W_OK):
        raise RuntimeError(f"PARROT_EVENT_FANOUT_OUTBOX_DIR is not a writable directory: {directory}")
    return directory / f"{socket.gethostname()}-{os.getpid()}.db"


def _validate_bus(bus: Any) -> None:
    """Require a Streams transport configured in publish-only mode."""
    core = getattr(bus, "_core", None)
    backend = getattr(core, "_backend", None)
    transport = getattr(bus, "transport", None)
    if transport is None and backend is not None:
        transport = "streams" if type(backend).__name__ == "RedisStreamsBackend" else None

    publish_only = getattr(bus, "publish_only", None)
    if publish_only is None and core is not None:
        publish_only = getattr(core, "_publish_only", None)

    if transport != "streams" or publish_only is not True:
        raise RuntimeError("Event fan-out bus must use transport='streams' and publish_only=True")


def setup_event_fanout(bus: Any = None) -> None:
    """Attach a dedicated Streams/publish-only bus and subscribe usage events."""
    global _BUS  # noqa: PLW0603
    if _BUS is not None:
        return

    if bus is None:
        bus = EventBus(
            redis_url=_config_value("PARROT_EVENT_FANOUT_REDIS_URL"),
            transport="streams",
            publish_only=True,
            channel_prefix=_config_value("PARROT_EVENT_FANOUT_CHANNEL_PREFIX", "parrot:events:"),
            outbox=_outbox_path(),
        )
    _validate_bus(bus)
    ensure_shared_cost_calculator()

    registry = get_global_registry()
    registry.attach_bus(bus, serializer=redact_usage_event)
    try:
        for event_cls in FORWARDED_EVENTS:
            _SUB_IDS.append(registry.subscribe(event_cls, _noop, forward_to_bus=True))
    except Exception:
        for subscription_id in _SUB_IDS:
            registry.unsubscribe(subscription_id)
        _SUB_IDS.clear()
        registry.detach_bus()
        raise

    _BUS = bus
    logger.info("Event fan-out enabled (%d events)", len(FORWARDED_EVENTS))


async def shutdown_event_fanout() -> None:
    """Unsubscribe, detach the bus, and close it while preserving its outbox."""
    global _BUS  # noqa: PLW0603
    bus = _BUS
    if bus is None:
        return

    registry = get_global_registry()
    try:
        for subscription_id in _SUB_IDS:
            try:
                registry.unsubscribe(subscription_id)
            except Exception:  # noqa: BLE001 — continue deterministic teardown
                logger.debug("Failed to unsubscribe fan-out subscription %s", subscription_id, exc_info=True)
        _SUB_IDS.clear()
        try:
            registry.detach_bus()
        except Exception:  # noqa: BLE001 — bus close must still be attempted
            logger.debug("Failed to detach event fan-out bus", exc_info=True)
        try:
            await bus.close()
        except Exception:  # noqa: BLE001 — shutdown must remain defensive
            logger.debug("Failed to close event fan-out bus", exc_info=True)
    finally:
        _BUS = None
