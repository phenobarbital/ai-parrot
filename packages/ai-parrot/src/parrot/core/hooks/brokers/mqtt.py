"""MQTT broker hook."""
import asyncio
from typing import Any

from ..models import BrokerHookConfig, HookType
from .base import BaseBrokerHook


class MQTTBrokerHook(BaseBrokerHook):
    """Subscribes to MQTT topics using gmqtt."""

    hook_type = HookType.BROKER_MQTT

    def __init__(self, config: BrokerHookConfig, **kwargs) -> None:
        super().__init__(config, **kwargs)
        self._topics = config.topics
        self._broker_url = config.broker_url or "localhost"
        self._client = None

    async def connect(self) -> None:
        try:
            from gmqtt import Client as MQTTClient
        except ImportError as exc:
            raise ImportError(
                "gmqtt is required for MQTTBrokerHook. "
                "Install with: uv pip install gmqtt"
            ) from exc

        self._client = MQTTClient(client_id=f"parrot_{self.hook_id}")
        self._client.on_message = self._on_mqtt_message
        self._client.on_connect = self._on_mqtt_connect
        await self._client.connect(self._broker_url)
        self.logger.info(f"MQTT connected to {self._broker_url}")

    async def disconnect(self) -> None:
        if self._client:
            await self._client.disconnect()
            self.logger.info("MQTT disconnected")

    async def start_consuming(self) -> None:
        """Keep alive — gmqtt handles messages via callbacks."""
        try:
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            pass

    def _on_mqtt_connect(self, client: Any, flags: Any, rc: int, properties: Any = None) -> None:
        """Subscribe to configured topics on connect/reconnect."""
        for topic in self._topics:
            client.subscribe(topic)
            self.logger.info(f"Subscribed to MQTT topic: {topic}")

    def _on_mqtt_message(self, client: Any, topic: str, payload: bytes, qos: int, properties: Any = None) -> None:
        """Handle incoming MQTT message — schedule async callback."""
        decoded = payload.decode("utf-8", errors="replace")
        self.logger.debug(f"MQTT msg on '{topic}': {decoded[:200]}")
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(self._on_message(
                message_id=f"{topic}:{id(payload)}",
                payload={"topic": topic, "message": decoded},
            ))
