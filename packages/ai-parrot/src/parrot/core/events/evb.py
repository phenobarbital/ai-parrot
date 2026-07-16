# parrot/core/events/evb.py
"""EventBus facade over the FEAT-310 BusCore (queued dispatch).

The public API of the legacy in-line EventBus is preserved VERBATIM
(``emit`` / ``subscribe`` / ``on`` / ``publish`` / ``unsubscribe`` /
``connect`` / ``close``); internally every event is converted to a frozen
``EventEnvelope`` and dispatched through ``BusCore``'s per-priority queues
and worker pool.

Semantic shift (documented): ``publish()``/``emit()`` still return an
``int``, but it is now the number of subscribers MATCHED AT ENQUEUE TIME —
delivery happens asynchronously on the worker pool, so the emitter never
waits for handlers (goal G2, FEAT-310).

New ADDITIVE-ONLY kwargs: ``severity=`` on ``publish``/``emit`` and
``min_severity=`` on ``subscribe``/``on`` (see
``parrot.core.events.bus.envelope.Severity``).

``[bus]`` TOML configuration (navconfig, flattened keys — all optional):

- ``BUS_WORKERS`` (default 4)
- ``BUS_QUEUE_SIZE`` (default 1024)
- ``BUS_HANDLER_TIMEOUT`` (default 30.0 s)
- ``BUS_RETRY_ATTEMPTS`` (default 3)
- ``BUS_RETRY_BASE_DELAY`` (default 0.1 s)
- ``BUS_DEFAULT_BACKPRESSURE`` (default ``block``)
- ``BUS_DRAIN_TIMEOUT`` (default 5.0 s)
"""
import asyncio
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional

from navconfig import config as nav_config
from navconfig.logging import logging

if TYPE_CHECKING:  # imported lazily at runtime to avoid a circular import
    from parrot.core.events.bus.core import BusCore
    from parrot.core.events.bus.envelope import EventEnvelope, Severity


class EventPriority(Enum):
    """Priority levels for events in the event bus."""
    LOW = 0
    NORMAL = 5
    HIGH = 10
    CRITICAL = 15


@dataclass
class Event:
    """Representa un evento en el bus."""
    event_type: str                              # "order.created", "agent.completed"
    payload: Dict[str, Any]
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    source: Optional[str] = None                 # Quién emitió el evento
    priority: EventPriority = EventPriority.NORMAL
    correlation_id: Optional[str] = None         # Para tracking de cadenas
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "payload": self.payload,
            "timestamp": self.timestamp.isoformat(),
            "source": self.source,
            "priority": self.priority.value,
            "correlation_id": self.correlation_id,
            "metadata": self.metadata
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Event":
        return cls(
            event_id=data.get("event_id", str(uuid.uuid4())),
            event_type=data["event_type"],
            payload=data.get("payload", {}),
            timestamp=(
                datetime.fromisoformat(data["timestamp"])
                if data.get("timestamp")
                else datetime.now(timezone.utc)
            ),
            source=data.get("source"),
            priority=EventPriority(data.get("priority", 5)),
            correlation_id=data.get("correlation_id"),
            metadata=data.get("metadata", {})
        )


@dataclass
class EventSubscription:
    """Subscripción a un patrón de eventos."""
    pattern: str                                 # "order.*", "agent.completed"
    handler: Callable[[Event], Any]
    subscriber_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    priority: int = 0                            # Orden de ejecución
    filter_fn: Optional[Callable[[Event], bool]] = None
    async_handler: bool = True


def _bus_config() -> Dict[str, Any]:
    """Read ``[bus]`` options from navconfig (flattened ``BUS_*`` keys).

    Returns:
        BusCore constructor kwargs with documented defaults.
    """
    def _get(key: str, fallback: Any, cast: Callable[[Any], Any]) -> Any:
        value = nav_config.get(key, fallback=fallback)
        try:
            return cast(value)
        except (TypeError, ValueError):
            return fallback

    return {
        "workers": _get("BUS_WORKERS", 4, int),
        "queue_size": _get("BUS_QUEUE_SIZE", 1024, int),
        "handler_timeout": _get("BUS_HANDLER_TIMEOUT", 30.0, float),
        "retry_attempts": _get("BUS_RETRY_ATTEMPTS", 3, int),
        "retry_base_delay": _get("BUS_RETRY_BASE_DELAY", 0.1, float),
        "default_backpressure": _get("BUS_DEFAULT_BACKPRESSURE", "block", str),
        "drain_timeout": _get("BUS_DRAIN_TIMEOUT", 5.0, float),
    }


class EventBus:
    """
    Bus de eventos con soporte para patrones glob y Redis como backend.

    Facade over :class:`~parrot.core.events.bus.core.BusCore` (FEAT-310):

    - Publicar eventos con tipos jerárquicos (order.created, order.updated)
    - Subscribirse con patrones glob (order.*, *.created)
    - Filtros personalizados por subscriber
    - Backend en memoria o Redis para distribución
    - ``publish()``/``emit()`` are O(1) enqueue — handlers run on a bounded
      worker pool, never on the emitter's await path.

    Args:
        redis_url: Optional Redis URL for distributed fan-out.
        use_redis: Enable the Redis pub/sub backend (requires *redis_url*).
        **bus_options: Additive BusCore overrides (``workers=``,
            ``queue_size=``, ``retry_attempts=``, ...) taking precedence
            over the navconfig ``BUS_*`` defaults.
    """

    CHANNEL_PREFIX = "parrot:events:"

    def __init__(
        self,
        redis_url: Optional[str] = None,
        use_redis: bool = False,
        **bus_options: Any,
    ):
        # Lazy imports — envelope/converters import THIS module for
        # EventPriority/Event, so bus modules cannot be imported at the
        # top of evb.py without a circular-import failure.
        from parrot.core.events.bus.core import BusCore
        from parrot.core.events.bus.backends.memory import MemoryBackend
        from parrot.core.events.bus.backends.redis_pubsub import (
            RedisPubSubBackend,
        )

        self.use_redis = use_redis and redis_url is not None
        self.redis_url = redis_url

        backend = (
            RedisPubSubBackend(redis_url)
            if self.use_redis
            else MemoryBackend()
        )
        core_opts = _bus_config()
        core_opts.update(bus_options)
        self._core: "BusCore" = BusCore(backend=backend, **core_opts)

        # Event history (opcional, para replay) — compat shim, bounded.
        self._max_history = 1000
        self._event_history: deque = deque(maxlen=self._max_history)

        self.logger = logging.getLogger("parrot.autonomy.event_bus")
        self._started = False
        self._closed = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self):
        """Start the dispatcher (and the Redis consumer when configured)."""
        await self._ensure_started()
        if self.use_redis:
            self.logger.info("EventBus connected to Redis")

    async def close(self):
        """Gracefully drain and shut down the bus."""
        self._closed = True
        await self._core.close()

    async def _ensure_started(self) -> None:
        """Auto-start BusCore so legacy call sites need no changes."""
        if self._closed:
            from parrot.core.events.bus.core import BusClosedError
            raise BusClosedError("EventBus is closed")
        if not self._started:
            self._started = True
            await self._core.start()

    async def start_redis_listener(self):
        """Deprecated alias — the Redis consumer now starts with the bus.

        Kept for legacy call sites (e.g. ``AutonomousOrchestrator``); the
        ``RedisPubSubBackend`` consumer loop is started by
        ``BusCore.start()``, so this only ensures the bus is running.
        """
        self.logger.warning(
            "start_redis_listener() is deprecated — the Redis consumer "
            "starts automatically with the bus (FEAT-310)."
        )
        await self._ensure_started()

    # ------------------------------------------------------------------
    # Subscribe / unsubscribe
    # ------------------------------------------------------------------

    def subscribe(
        self,
        pattern: str,
        handler: Callable[[Event], Any],
        *,
        priority: int = 0,
        filter_fn: Optional[Callable[[Event], bool]] = None,
        min_severity: "Optional[Severity]" = None,
    ) -> str:
        """
        Subscribe a eventos que coincidan con el patrón.

        Args:
            pattern: Patrón de eventos ("order.created", "order.*", "*")
            handler: Función a llamar cuando llega un evento (recibe ``Event``)
            priority: Orden de ejecución (mayor = primero)
            filter_fn: Filtro adicional opcional (recibe ``Event``)
            min_severity: ADDITIVE (FEAT-310) — deliver only envelopes at or
                above this :class:`Severity`; never affects scheduling.

        Returns:
            subscriber_id para poder hacer unsubscribe
        """
        wrapped_filter: Optional[Callable[["EventEnvelope"], bool]] = None
        if filter_fn is not None:
            def _filter(envelope: "EventEnvelope") -> bool:
                return bool(filter_fn(_envelope_to_event(envelope)))
            wrapped_filter = _filter

        if asyncio.iscoroutinefunction(handler):
            async def wrapped_handler(envelope: "EventEnvelope") -> None:
                await handler(_envelope_to_event(envelope))
        else:
            def wrapped_handler(envelope: "EventEnvelope") -> None:
                handler(_envelope_to_event(envelope))

        return self._core.subscribe(
            pattern,
            wrapped_handler,
            priority=priority,
            filter_fn=wrapped_filter,
            min_severity=min_severity,
        )

    def unsubscribe(self, subscriber_id: str) -> bool:
        """Elimina una subscripción."""
        return self._core.unsubscribe(subscriber_id)

    # ------------------------------------------------------------------
    # Publish
    # ------------------------------------------------------------------

    async def publish(
        self,
        event: Event,
        *,
        severity: "Optional[Severity]" = None,
    ) -> int:
        """
        Publica un evento al bus — O(1) enqueue, nunca espera handlers.

        Args:
            event: Legacy ``Event`` to publish.
            severity: ADDITIVE (FEAT-310) — severity stamped on the internal
                envelope (default ``Severity.INFO``).

        Returns:
            Número de subscribers que COINCIDEN en el momento del enqueue
            (semantic shift: delivery is asynchronous on the worker pool).
        """
        from parrot.core.events.bus.converters import from_legacy_event
        from parrot.core.events.bus.envelope import Severity as _Severity

        await self._ensure_started()

        # Guardar en history (bounded deque compat shim)
        self._event_history.append(event)

        envelope = from_legacy_event(
            event, severity=severity if severity is not None else _Severity.INFO
        )
        matches = len(self._core._matching_subscriptions(event.event_type))
        await self._core.publish(envelope)

        self.logger.debug(
            f"Published event {event.event_type}, "
            f"{matches} subscribers matched"
        )
        return matches

    # === Convenience methods ===

    async def emit(
        self,
        event_type: str,
        payload: Dict[str, Any],
        **kwargs
    ) -> int:
        """Shortcut para publicar eventos.

        Accepts every legacy ``Event`` kwarg (``source=``, ``priority=``,
        ``correlation_id=``, ``metadata=``, ...) plus the ADDITIVE
        ``severity=`` kwarg (FEAT-310).
        """
        severity = kwargs.pop("severity", None)
        event = Event(
            event_type=event_type,
            payload=payload,
            **kwargs
        )
        return await self.publish(event, severity=severity)

    def on(self, pattern: str, **kwargs):
        """Decorator para subscribirse a eventos."""
        def decorator(fn):
            self.subscribe(pattern, fn, **kwargs)
            return fn
        return decorator


def _envelope_to_event(envelope: "EventEnvelope") -> Event:
    """Convert an internal ``EventEnvelope`` back to a legacy ``Event``.

    Handlers registered through the facade keep receiving ``Event``
    instances, exactly as before FEAT-310.
    """
    return Event(
        event_type=envelope.topic,
        payload=envelope.payload,
        event_id=envelope.event_id,
        timestamp=envelope.timestamp,
        source=envelope.source,
        priority=envelope.priority,
        correlation_id=envelope.correlation_id,
        metadata=envelope.metadata,
    )
