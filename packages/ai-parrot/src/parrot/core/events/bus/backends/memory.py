"""MemoryBackend — default in-process transport (FEAT-310, Module 3)."""
from typing import Optional

from navconfig.logging import logging

from parrot.core.events.bus.backends.base import OnEnvelope
from parrot.core.events.bus.envelope import EventEnvelope


class MemoryBackend:
    """In-process loopback transport with at-most-once semantics.

    ``publish`` feeds the registered consumer callback directly —
    ``BusCore``'s per-priority queues provide the buffering, so this
    backend holds no queue of its own. If no consumer is registered,
    published envelopes are dropped (at-most-once by design).
    """

    def __init__(self) -> None:
        self._on_envelope: Optional[OnEnvelope] = None
        self.logger = logging.getLogger("parrot.core.events.bus.memory")

    async def publish(self, envelope: EventEnvelope) -> None:
        """Deliver *envelope* directly to the registered consumer.

        Args:
            envelope: The envelope to deliver.
        """
        if self._on_envelope is None:
            self.logger.debug(
                "MemoryBackend dropped %s: no consumer registered",
                envelope.topic,
            )
            return
        await self._on_envelope(envelope)

    async def start_consumer(self, on_envelope: OnEnvelope) -> None:
        """Register the consumer callback.

        Args:
            on_envelope: Awaited for each published envelope.
        """
        self._on_envelope = on_envelope

    async def close(self) -> None:
        """Unregister the consumer."""
        self._on_envelope = None
