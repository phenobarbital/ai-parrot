"""navigator-eventbus carrier on a dedicated instance (FEAT-747 M9)."""

from __future__ import annotations

import base64
import logging
import os
from collections import OrderedDict
from typing import TYPE_CHECKING, Any, Mapping, Optional, Sequence

from ..codec import EnvelopeCodec, JsonEnvelopeCodec
from ..messages import AgentAddress, RoostMessage
from ..performatives import CarrierKind
from .base import Carrier, Inbound, Undeliverable

if TYPE_CHECKING:
    from navigator_eventbus import EventBus
    from navigator_eventbus.evb import Event


class EventBusCarrier(Carrier):
    """Carry Roost messages over a dedicated navigator-eventbus instance."""

    kind = CarrierKind.NETWORK

    def __init__(
        self,
        bus: "EventBus",
        *,
        topic_prefix: str = "roost",
        dlq_topic: str = "roost.dlq",
        codec: Optional[EnvelopeCodec] = None,
        dedup_size: int = 10_000,
    ) -> None:
        """Create a carrier over a bus that supports both publish and subscribe."""
        self.logger = logging.getLogger(__name__)
        core = getattr(bus, "_core", None)
        publish_only = getattr(bus, "publish_only", None)
        if publish_only is None and core is not None:
            publish_only = getattr(core, "_publish_only", None)
        if publish_only is True:
            raise ValueError("Roost EventBus must support subscriptions; publish_only=True is invalid")

        self._bus, self._prefix, self._dlq = bus, topic_prefix.rstrip("."), dlq_topic
        self._codec = codec or JsonEnvelopeCodec()
        self._codecs: dict[str, EnvelopeCodec] = {self._codec.content_type: self._codec}
        self._seen: "OrderedDict[str, None]" = OrderedDict()
        self._dedup_size = dedup_size
        self._subscriptions: dict[str, list[str]] = {}

    async def send(self, msg: RoostMessage) -> None:
        """Publish *msg* to each receiver or its capability category."""
        topics = [f"{self._prefix}.{receiver.name}" for receiver in msg.receivers]
        if not topics and msg.capability_filter:
            topics = [f"{self._prefix}.cap.{self._capability_category(msg.capability_filter)}"]
        if not topics:
            raise Undeliverable("message has neither receivers nor a capability filter")

        for topic in dict.fromkeys(topics):
            event = self.to_event(msg, codec=self._codec, prefix=self._prefix)
            event.event_type = topic
            await self._bus.publish(event)

    async def subscribe(
        self,
        address: AgentAddress,
        inbound: Inbound,
        *,
        capabilities: Sequence[str] = (),
    ) -> str:
        """Subscribe an inbound callback to its addressed and capability topics."""
        topics = [f"{self._prefix}.{address.name}"]
        topics.extend(f"{self._prefix}.cap.{self._capability_category(value)}" for value in capabilities)
        subscriber_ids: list[str] = []

        async def handler(event: "Event") -> None:
            idempotency_key = str(event.metadata.get("idempotency_key") or event.event_id)
            if idempotency_key in self._seen:
                self._seen.move_to_end(idempotency_key)
                return
            self._seen[idempotency_key] = None
            while len(self._seen) > self._dedup_size:
                self._seen.popitem(last=False)
            try:
                message = self.from_event(event, codecs=self._codecs)
                await inbound(message)
            except Exception as exc:  # noqa: BLE001 — malformed and undeliverable events belong on the DLQ
                self.logger.warning("Routing Roost event %s to the DLQ: %s", event.event_id, exc)
                await self._publish_dlq(event, exc)

        try:
            for topic in dict.fromkeys(topics):
                subscriber_ids.append(self._bus.subscribe(topic, handler))
        except Exception:
            for subscriber_id in subscriber_ids:
                self._bus.unsubscribe(subscriber_id)
            raise

        subscription_id = subscriber_ids[0]
        self._subscriptions[subscription_id] = subscriber_ids
        return subscription_id

    async def unsubscribe(self, subscription_id: str) -> bool:
        """Remove every bus subscription represented by *subscription_id*."""
        subscriber_ids = self._subscriptions.pop(subscription_id, None)
        if subscriber_ids is None:
            return False
        removed = False
        for subscriber_id in subscriber_ids:
            removed = self._bus.unsubscribe(subscriber_id) or removed
        return removed

    async def close(self) -> None:
        """Unsubscribe carrier handlers without closing the caller-owned bus."""
        for subscription_id in list(self._subscriptions):
            await self.unsubscribe(subscription_id)

    @staticmethod
    def to_event(msg: RoostMessage, *, codec: EnvelopeCodec, prefix: str) -> "Event":
        """Map a Roost message to a navigator event."""
        from navigator_eventbus.evb import Event  # noqa: PLC0415

        envelope = msg.envelope
        idempotency_key = envelope.idempotency_key or msg.message_id
        if msg.receivers:
            topic = f"{prefix.rstrip('.')}.{msg.receivers[0].name}"
        elif msg.capability_filter:
            category = EventBusCarrier._capability_category(msg.capability_filter)
            topic = f"{prefix.rstrip('.')}.cap.{category}"
        else:
            raise Undeliverable("message has neither receivers nor a capability filter")
        trace = getattr(envelope, "trace", None)
        return Event(
            event_type=topic,
            event_id=idempotency_key,
            payload={
                "codec": codec.content_type,
                "data": base64.b64encode(codec.encode(msg)).decode("ascii"),
            },
            source=msg.sender.name,
            correlation_id=envelope.correlation_id,
            metadata={
                "reply_to": f"{prefix.rstrip('.')}.{msg.sender.name}",
                "idempotency_key": idempotency_key,
                "trace_id": getattr(trace, "trace_id", None),
                "performative": msg.performative.value,
                "conversation_id": msg.conversation_id,
                "auth_token": msg.auth_token,
            },
        )

    @staticmethod
    def from_event(event: "Event", *, codecs: Mapping[str, EnvelopeCodec]) -> RoostMessage:
        """Decode an event, raising ``LookupError`` when its codec is unknown."""
        content_type = event.payload["codec"]
        try:
            codec = codecs[content_type]
        except KeyError as exc:
            raise LookupError(f"unknown Roost envelope codec: {content_type}") from exc
        encoded = base64.b64decode(event.payload["data"], validate=True)
        return codec.decode(encoded)

    async def _publish_dlq(self, event: "Event", error: Exception) -> None:
        """Publish an event that could not be decoded or delivered to the DLQ."""
        from navigator_eventbus.evb import Event  # noqa: PLC0415

        await self._bus.publish(
            Event(
                event_type=self._dlq,
                payload=event.payload,
                source=event.source,
                correlation_id=event.correlation_id,
                metadata={
                    **event.metadata,
                    "original_event_type": event.event_type,
                    "error": str(error),
                },
            )
        )

    @staticmethod
    def _capability_category(capability: str) -> str:
        """Return a stable broadcast category after dropping the leaf segment."""
        parts = [part for part in capability.strip(".").split(".") if part]
        if len(parts) > 1:
            parts.pop()
        return ".".join(parts)


def _config_value(name: str, fallback: Optional[str] = None) -> Optional[str]:
    """Read a Roost bus setting through navconfig with an environment fallback."""
    try:
        from navconfig import config as nav_config  # noqa: PLC0415

        value = nav_config.get(name, fallback=os.environ.get(name, fallback))
    except Exception:  # noqa: BLE001 — environment remains the dependency-free fallback
        value = os.environ.get(name, fallback)
    return str(value) if value is not None else None


def build_roost_bus() -> "EventBus":
    """Build a dedicated publish-and-subscribe Streams bus with an outbox."""
    from navigator_eventbus import EventBus  # noqa: PLC0415

    redis_url = _config_value("PARROT_ROOST_BUS_URL")
    if not redis_url:
        raise RuntimeError("PARROT_ROOST_BUS_URL is required for the Roost event bus")
    channel_prefix = _config_value("PARROT_ROOST_BUS_PREFIX", "roost:")
    outbox_path = os.path.join(os.environ.get("TMPDIR", "/tmp"), f"parrot-roost-{os.getpid()}.db")
    bus = EventBus(
        redis_url=redis_url,
        transport="streams",
        publish_only=False,
        channel_prefix=channel_prefix,
        outbox=outbox_path,
    )
    backend = getattr(getattr(bus, "_core", None), "_backend", None)
    if backend is not None and type(backend).__name__ != "RedisStreamsBackend":
        raise RuntimeError("Roost event bus must use transport='streams'")
    return bus
