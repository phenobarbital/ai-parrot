"""Abstract base class for message broker hooks."""
import asyncio
from abc import abstractmethod
from typing import Any, Optional

from ..base import BaseHook
from ..models import BrokerHookConfig


class BaseBrokerHook(BaseHook):
    """Abstract base for message-queue / stream broker hooks.

    Subclasses implement ``connect()``, ``disconnect()``, and
    ``start_consuming()`` to integrate with a specific broker.
    """

    def __init__(self, config: BrokerHookConfig, **kwargs) -> None:
        super().__init__(
            name=config.name,
            enabled=config.enabled,
            target_type=config.target_type,
            target_id=config.target_id,
            metadata=config.metadata,
            **kwargs,
        )
        self._config = config
        self._consume_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        await self.connect()
        self._consume_task = asyncio.create_task(self._run_consumer())
        self.logger.info(f"BrokerHook '{self.name}' started")

    async def stop(self) -> None:
        if self._consume_task:
            self._consume_task.cancel()
            try:
                await self._consume_task
            except asyncio.CancelledError:
                pass
        await self.disconnect()
        self.logger.info(f"BrokerHook '{self.name}' stopped")

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to the broker."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Gracefully disconnect from the broker."""

    @abstractmethod
    async def start_consuming(self) -> None:
        """Start consuming messages (blocking coroutine)."""

    async def _run_consumer(self) -> None:
        try:
            await self.start_consuming()
        except asyncio.CancelledError:
            self.logger.debug("Consumer task cancelled")
        except Exception as exc:
            self.logger.error(f"Consumer error: {exc}")

    async def _on_message(
        self,
        message_id: Any,
        payload: Any,
        message: Any = None,
    ) -> None:
        """Standard callback for when a message arrives."""
        event = self._make_event(
            event_type="broker.message",
            payload={
                "message_id": str(message_id),
                "payload": payload if isinstance(payload, dict) else str(payload),
                "broker_type": self._config.broker_type,
            },
            task=f"Broker message received (ID: {message_id})",
        )
        await self.on_event(event)
