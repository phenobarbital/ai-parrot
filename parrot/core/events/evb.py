# parrot/autonomy/event_bus.py
import asyncio
import fnmatch
import json
from typing import Dict, List, Callable, Any, Optional, Set
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import uuid

import redis.asyncio as aioredis
from navconfig.logging import logging


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
    timestamp: datetime = field(default_factory=datetime.now)
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
            timestamp=datetime.fromisoformat(data["timestamp"]) if data.get("timestamp") else datetime.now(),
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


class EventBus:
    """
    Bus de eventos con soporte para patrones glob y Redis como backend.

    Permite:
    - Publicar eventos con tipos jerárquicos (order.created, order.updated)
    - Subscribirse con patrones glob (order.*, *.created)
    - Filtros personalizados por subscriber
    - Backend en memoria o Redis para distribución
    """

    CHANNEL_PREFIX = "parrot:events:"

    def __init__(
        self,
        redis_url: Optional[str] = None,
        use_redis: bool = False
    ):
        self.use_redis = use_redis and redis_url is not None
        self.redis_url = redis_url

        self._redis: Optional[aioredis.Redis] = None
        self._pubsub = None

        # Subscripciones locales
        self._subscriptions: Dict[str, List[EventSubscription]] = {}
        self._pattern_subscriptions: List[EventSubscription] = []  # Para patrones con *

        # Event history (opcional, para replay)
        self._event_history: List[Event] = []
        self._max_history = 1000

        self.logger = logging.getLogger("parrot.autonomy.event_bus")
        self._running = False

    async def connect(self):
        """Conecta al backend Redis si está configurado."""
        if self.use_redis:
            self._redis = await aioredis.from_url(
                self.redis_url,
                decode_responses=True
            )
            self._pubsub = self._redis.pubsub()
            self.logger.info("EventBus connected to Redis")

    async def close(self):
        """Cierra conexiones."""
        self._running = False
        if self._pubsub:
            await self._pubsub.unsubscribe()
            await self._pubsub.close()
        if self._redis:
            await self._redis.close()

    def subscribe(
        self,
        pattern: str,
        handler: Callable[[Event], Any],
        *,
        priority: int = 0,
        filter_fn: Optional[Callable[[Event], bool]] = None
    ) -> str:
        """
        Subscribe a eventos que coincidan con el patrón.

        Args:
            pattern: Patrón de eventos ("order.created", "order.*", "*")
            handler: Función a llamar cuando llega un evento
            priority: Orden de ejecución (mayor = primero)
            filter_fn: Filtro adicional opcional

        Returns:
            subscriber_id para poder hacer unsubscribe
        """
        subscription = EventSubscription(
            pattern=pattern,
            handler=handler,
            priority=priority,
            filter_fn=filter_fn,
            async_handler=asyncio.iscoroutinefunction(handler)
        )

        if "*" in pattern or "?" in pattern:
            # Patrón con wildcards
            self._pattern_subscriptions.append(subscription)
            self._pattern_subscriptions.sort(key=lambda s: -s.priority)
        else:
            # Patrón exacto
            if pattern not in self._subscriptions:
                self._subscriptions[pattern] = []
            self._subscriptions[pattern].append(subscription)
            self._subscriptions[pattern].sort(key=lambda s: -s.priority)

        self.logger.debug(f"Subscribed to '{pattern}' with id {subscription.subscriber_id}")
        return subscription.subscriber_id

    def unsubscribe(self, subscriber_id: str) -> bool:
        """Elimina una subscripción."""
        # Buscar en exactas
        for pattern, subs in self._subscriptions.items():
            for sub in subs:
                if sub.subscriber_id == subscriber_id:
                    subs.remove(sub)
                    return True

        # Buscar en patrones
        for sub in self._pattern_subscriptions:
            if sub.subscriber_id == subscriber_id:
                self._pattern_subscriptions.remove(sub)
                return True

        return False

    async def publish(self, event: Event) -> int:
        """
        Publica un evento al bus.

        Returns:
            Número de handlers que procesaron el evento
        """
        # Guardar en history
        self._event_history.append(event)
        if len(self._event_history) > self._max_history:
            self._event_history = self._event_history[-self._max_history:]

        handlers_called = 0

        # Obtener subscriptores que coinciden
        matching_subs = self._get_matching_subscriptions(event.event_type)

        for sub in matching_subs:
            # Aplicar filtro si existe
            if sub.filter_fn and not sub.filter_fn(event):
                continue

            try:
                if sub.async_handler:
                    await sub.handler(event)
                else:
                    sub.handler(event)
                handlers_called += 1
            except Exception as e:
                self.logger.error(
                    f"Handler error for event {event.event_type}: {e}"
                )

        # Si Redis está habilitado, también publicar ahí
        if self.use_redis and self._redis:
            await self._redis.publish(
                f"{self.CHANNEL_PREFIX}{event.event_type}",
                json.dumps(event.to_dict())
            )

        self.logger.debug(
            f"Published event {event.event_type}, "
            f"{handlers_called} handlers called"
        )

        return handlers_called

    def _get_matching_subscriptions(
        self,
        event_type: str
    ) -> List[EventSubscription]:
        """Encuentra todas las subscripciones que coinciden."""
        matching = []

        # Exactas
        if event_type in self._subscriptions:
            matching.extend(self._subscriptions[event_type])

        # Patrones
        matching.extend(
            sub
            for sub in self._pattern_subscriptions
            if fnmatch.fnmatch(event_type, sub.pattern)
        )

        # Ordenar por prioridad
        matching.sort(key=lambda s: -s.priority)
        return matching

    async def start_redis_listener(self):
        """Inicia listener de Redis para eventos distribuidos."""
        if not self.use_redis:
            return

        self._running = True
        await self._pubsub.psubscribe(f"{self.CHANNEL_PREFIX}*")

        self.logger.info("Started Redis event listener")

        async for message in self._pubsub.listen():
            if not self._running:
                break

            if message["type"] == "pmessage":
                try:
                    event_data = json.loads(message["data"])
                    event = Event.from_dict(event_data)

                    # Procesar localmente (sin re-publicar a Redis)
                    matching_subs = self._get_matching_subscriptions(event.event_type)
                    for sub in matching_subs:
                        if sub.filter_fn and not sub.filter_fn(event):
                            continue
                        try:
                            if sub.async_handler:
                                await sub.handler(event)
                            else:
                                sub.handler(event)
                        except Exception as e:
                            self.logger.error(f"Handler error: {e}")

                except Exception as e:
                    self.logger.error(f"Error processing Redis event: {e}")

    # === Convenience methods ===

    async def emit(
        self,
        event_type: str,
        payload: Dict[str, Any],
        **kwargs
    ) -> int:
        """Shortcut para publicar eventos."""
        event = Event(
            event_type=event_type,
            payload=payload,
            **kwargs
        )
        return await self.publish(event)

    def on(self, pattern: str, **kwargs):
        """Decorator para subscribirse a eventos."""
        def decorator(fn):
            self.subscribe(pattern, fn, **kwargs)
            return fn
        return decorator
