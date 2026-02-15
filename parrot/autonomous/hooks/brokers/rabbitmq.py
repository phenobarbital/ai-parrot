"""RabbitMQ broker hook."""
from typing import Any

from ..models import BrokerHookConfig, HookType
from .base import BaseBrokerHook


class RabbitMQBrokerHook(BaseBrokerHook):
    """Consumes messages from a RabbitMQ queue."""

    hook_type = HookType.BROKER_RABBITMQ

    def __init__(self, config: BrokerHookConfig, **kwargs) -> None:
        super().__init__(config, **kwargs)
        self._queue_name = config.queue_name or "default_queue"
        self._routing_key = config.routing_key
        self._exchange_name = config.exchange_name
        self._exchange_type = config.exchange_type
        self._prefetch_count = config.prefetch_count
        self._connection = None

    async def connect(self) -> None:
        from navigator.brokers.rabbitmq import RabbitMQConnection
        self._connection = RabbitMQConnection(credentials=self._config.credentials)
        await self._connection.connect()
        self.logger.info("RabbitMQ connection established")
        # Ensure exchange and queue exist
        await self._connection.ensure_exchange(
            exchange_name=self._exchange_name or self._queue_name,
            exchange_type=self._exchange_type,
        )
        await self._connection.ensure_queue(
            queue_name=self._queue_name,
            exchange_name=self._exchange_name or self._queue_name,
            routing_key=self._routing_key,
        )

    async def disconnect(self) -> None:
        if self._connection:
            await self._connection.disconnect()
            self.logger.info("RabbitMQ connection closed")

    async def start_consuming(self) -> None:
        await self._connection.consume_messages(
            queue_name=self._queue_name,
            callback=self._consumer_callback,
            prefetch_count=self._prefetch_count,
        )

    async def _consumer_callback(self, message: Any, body: Any) -> None:
        message_id = getattr(message, "delivery_tag", str(message))
        self.logger.debug(f"RabbitMQ msg {message_id}: {body}")
        try:
            await self._on_message(
                message_id=message_id, payload=body, message=message
            )
        except Exception as exc:
            self.logger.error(f"RabbitMQ callback error: {exc}")
            if self._connection:
                await self._connection.reject_message(message, requeue=False)
