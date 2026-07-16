"""TransportBackend protocol — pluggable bus transports (FEAT-310, Module 3).

A transport backend fans envelopes out to (and consumes them from) an
external medium. Shipping backends:

- :class:`~parrot.core.events.bus.backends.memory.MemoryBackend` — default,
  in-process loopback, at-most-once.
- :class:`~parrot.core.events.bus.backends.redis_pubsub.RedisPubSubBackend`
  — legacy Redis pub/sub port, fan-out only, at-most-once, unpersisted.
- ``RedisStreamsBackend`` (TASK-1789) — durable at-least-once.

The protocol deliberately allows future RabbitMQ/NATS drop-ins (spec §1
non-goals): three async methods, one wire format
(``EventEnvelope.to_dict()`` JSON).
"""
from typing import Awaitable, Callable, Protocol, runtime_checkable

from parrot.core.events.bus.envelope import EventEnvelope

# Callback a backend consumer invokes for each envelope arriving off the wire.
OnEnvelope = Callable[[EventEnvelope], Awaitable[None]]


@runtime_checkable
class TransportBackend(Protocol):
    """Pluggable transport for bus envelopes.

    Implementations own their connections (each backend owns its client —
    same as the legacy ``EventBus`` today) and MUST keep ``publish`` /
    consumer failures isolated: a broken transport degrades to local-only
    dispatch, it never crashes the bus (spec §7 "Redis down").
    """

    async def publish(self, envelope: EventEnvelope) -> None:
        """Fan *envelope* out to the transport medium."""
        ...

    async def start_consumer(self, on_envelope: OnEnvelope) -> None:
        """Start consuming envelopes, invoking *on_envelope* for each one."""
        ...

    async def close(self) -> None:
        """Stop consuming and release transport resources."""
        ...
