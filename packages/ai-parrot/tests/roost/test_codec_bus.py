"""Tests for the Roost JSON codec and navigator-eventbus carrier."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest
from navigator_eventbus import EventBus
from navigator_eventbus.evb import Event
from pydantic import BaseModel

from parrot.core.events.lifecycle import TraceContext
from parrot.roost.carriers.bus import EventBusCarrier
from parrot.roost.codec import JsonEnvelopeCodec, UnencodableContent
from parrot.roost.messages import AgentAddress, FailureInfo, LocalEnvelope, RoostMessage
from parrot.roost.performatives import FailureCode, InteractionProtocol as IP, Performative as P


class ExampleContent(BaseModel):
    """Importable Pydantic payload used to verify typed round trips."""

    value: int


class SerializablePermissionContext:
    """Minimal authority context exposing the required serialization seam."""

    def to_dict(self) -> dict[str, str]:
        """Return a JSON-compatible authority description."""
        return {"user_id": "user-1"}


@pytest.fixture
def envelope() -> LocalEnvelope:
    """Return a fully populated local envelope."""
    return LocalEnvelope(
        envelope_id="env-1",
        correlation_id="corr-1",
        trace=TraceContext(trace_id="trace-1", span_id="span-1"),
        budget_ms=500,
        token_budget=100,
        caller="agent-a",
        idempotency_key="idem-1",
    )


def _msg(envelope: LocalEnvelope, content: object = None) -> RoostMessage:
    return RoostMessage(
        message_id="message-1",
        performative=P.REQUEST,
        protocol=IP.REQUEST,
        conversation_id="conversation-1",
        in_reply_to="previous-1",
        envelope=envelope,
        sender=AgentAddress(name="agent-a"),
        receivers=[AgentAddress(name="agent-b")],
        content=content,
        content_type="application/example",
        body="request body",
        failure=FailureInfo(code=FailureCode.INTERNAL, detail="detail", retryable=True),
        permission_context=SerializablePermissionContext(),
        auth_token="token-1",
        created_at=datetime(2026, 10, 26, tzinfo=timezone.utc),
    )


def test_json_roundtrip_preserves_message_and_envelope(envelope: LocalEnvelope) -> None:
    codec = JsonEnvelopeCodec()
    original = _msg(envelope, ExampleContent(value=7))

    decoded = codec.decode(codec.encode(original))

    assert decoded.model_dump(exclude={"content", "envelope"}) == original.model_dump(
        exclude={"content", "envelope", "permission_context"}
    ) | {"permission_context": {"user_id": "user-1"}}
    assert decoded.content == ExampleContent(value=7)
    assert decoded.envelope.envelope_id == envelope.envelope_id
    assert decoded.envelope.correlation_id == envelope.correlation_id
    assert decoded.envelope.trace.trace_id == "trace-1"
    assert decoded.envelope.trace.span_id == "span-1"
    assert decoded.envelope.budget_ms == 500
    assert decoded.envelope.token_budget == 100
    assert decoded.envelope.caller == "agent-a"
    assert decoded.envelope.idempotency_key == "idem-1"


def test_json_roundtrip_preserves_raw_content(envelope: LocalEnvelope) -> None:
    decoded = JsonEnvelopeCodec().decode(JsonEnvelopeCodec().encode(_msg(envelope, {"x": [1, 2]})))

    assert decoded.content == {"x": [1, 2]}


def test_json_rejects_unencodable_content(envelope: LocalEnvelope) -> None:
    with pytest.raises(UnencodableContent):
        JsonEnvelopeCodec().encode(_msg(envelope, object()))


def test_bus_event_mapping_reply_to_idempotency(envelope: LocalEnvelope) -> None:
    event = EventBusCarrier.to_event(_msg(envelope, {"x": 1}), codec=JsonEnvelopeCodec(), prefix="roost")

    assert event.event_type == "roost.agent-b"
    assert event.event_id == "idem-1"
    assert event.correlation_id == "corr-1"
    assert event.metadata == {
        "reply_to": "roost.agent-a",
        "idempotency_key": "idem-1",
        "trace_id": "trace-1",
        "performative": "request",
        "conversation_id": "conversation-1",
        "auth_token": "token-1",
    }
    assert EventBusCarrier.from_event(event, codecs={"application/json": JsonEnvelopeCodec()}).auth_token == "token-1"


@pytest.mark.asyncio
async def test_replayed_event_is_delivered_once(envelope: LocalEnvelope) -> None:
    bus = EventBus(transport="memory")
    carrier = EventBusCarrier(bus)
    delivered = asyncio.Event()
    messages: list[RoostMessage] = []

    async def inbound(message: RoostMessage) -> None:
        messages.append(message)
        delivered.set()

    try:
        await carrier.subscribe(AgentAddress(name="agent-b"), inbound)
        event = carrier.to_event(_msg(envelope, {"x": 1}), codec=JsonEnvelopeCodec(), prefix="roost")
        await bus.publish(event)
        await bus.publish(event)
        await asyncio.wait_for(delivered.wait(), timeout=1)
        await asyncio.sleep(0.05)
        assert len(messages) == 1
    finally:
        await carrier.close()
        await bus.close()


@pytest.mark.asyncio
async def test_unknown_codec_goes_to_dlq() -> None:
    bus = EventBus(transport="memory")
    carrier = EventBusCarrier(bus)
    dlq_received = asyncio.Event()
    dlq_events: list[Event] = []

    async def inbound(_message: RoostMessage) -> None:
        raise AssertionError("unknown codec must not reach inbound")

    async def dlq_handler(event: Event) -> None:
        dlq_events.append(event)
        dlq_received.set()

    dlq_subscription = bus.subscribe("roost.dlq", dlq_handler)
    try:
        await carrier.subscribe(AgentAddress(name="agent-b"), inbound)
        await bus.publish(
            Event(
                event_type="roost.agent-b",
                event_id="bad-event",
                payload={"codec": "application/unknown", "data": ""},
                metadata={"idempotency_key": "bad-event"},
            )
        )
        await asyncio.wait_for(dlq_received.wait(), timeout=1)
        assert len(dlq_events) == 1
        assert dlq_events[0].metadata["original_event_type"] == "roost.agent-b"
        assert "unknown Roost envelope codec" in dlq_events[0].metadata["error"]
    finally:
        bus.unsubscribe(dlq_subscription)
        await carrier.close()
        await bus.close()


def test_publish_only_bus_is_rejected() -> None:
    bus = EventBus(transport="memory", publish_only=True)

    with pytest.raises(ValueError, match="publish_only"):
        EventBusCarrier(bus)
