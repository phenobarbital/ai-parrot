"""Tests for the Matrix Roost carrier (FEAT-747 M12), with a mocked client."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from parrot.integrations.matrix.events import ParrotEventType, RoostEventContent
from parrot.integrations.matrix.roost import MatrixCarrier
from parrot.roost.messages import AgentAddress, FailureInfo, LocalEnvelope, RoostMessage
from parrot.roost.performatives import FailureCode, InteractionProtocol as IP, Performative as P


def _msg(**kw) -> RoostMessage:
    base = dict(
        performative=P.INFORM,
        protocol=IP.INFORM,
        conversation_id="c",
        sender=AgentAddress(name="a"),
        receivers=[AgentAddress(name="b")],
        content={"x": 1},
    )
    base.update(kw)
    return RoostMessage(**base)


def _client() -> MagicMock:
    client = MagicMock()
    client.send_event = AsyncMock(return_value="$ev1")
    return client


def test_body_mandatory():
    with pytest.raises(ValidationError):
        RoostEventContent(performative="inform", protocol="inform", conversation_id="c", message_id="m", sender="a")


async def test_send_uses_roost_event():
    client = _client()
    car = MatrixCarrier(client, room_id="!r", agent_name="a")
    await car.send(_msg())
    room, etype, content = client.send_event.await_args.args
    assert room == "!r" and etype == ParrotEventType.ROOST and content["body"]
    assert "m.relates_to" not in content


def test_round_trip_keeps_fields():
    env = LocalEnvelope(correlation_id="corr", caller="a", budget_ms=5, token_budget=7, idempotency_key="k")
    msg = _msg(
        performative=P.FAILURE,
        in_reply_to="orig",
        envelope=env,
        failure=FailureInfo(code=FailureCode.TIMEOUT, detail="slow", retryable=True),
        capability_filter="cap",
    )
    content = MatrixCarrier.to_content(msg, body="hello").model_dump(mode="json")
    out = MatrixCarrier.from_content(content, event_id="$e")
    assert out.message_id == msg.message_id and out.performative == P.FAILURE and out.protocol == IP.INFORM
    assert out.conversation_id == "c" and out.in_reply_to == "orig" and out.capability_filter == "cap"
    assert out.sender.name == "a" and [r.name for r in out.receivers] == ["b"]
    assert out.content == {"x": 1} and out.body == "hello"
    assert out.failure == msg.failure
    assert out.envelope.correlation_id == "corr" and out.envelope.budget_ms == 5
    assert out.envelope.token_budget == 7 and out.envelope.idempotency_key == "k"


def test_unencodable_content_raises():
    with pytest.raises(ValueError):
        MatrixCarrier.to_content(_msg(content=object()), body="b")


def test_handle_goes_to_content_ref():
    handle = SimpleNamespace(handle_id="h-1")
    content = MatrixCarrier.to_content(_msg(content=handle), body="b")
    assert content.content is None and content.content_ref == "h-1"


async def test_reply_carries_relates_to():
    client = _client()
    car = MatrixCarrier(client, room_id="!r", agent_name="a")
    first = _msg()
    await car.send(first)
    await car.send(_msg(in_reply_to=first.message_id))
    content = client.send_event.await_args.args[2]
    assert content["m.relates_to"] == {"m.in_reply_to": {"event_id": "$ev1"}}


async def test_subscribe_dispatch_and_unsubscribe():
    client = _client()
    car = MatrixCarrier(client, room_id="!r", agent_name="b")
    got = []

    async def inbound(m: RoostMessage) -> None:
        got.append(m)

    sub = await car.subscribe(AgentAddress(name="b"), inbound)
    cb = client.on_custom_event.call_args.args[1]
    content = MatrixCarrier.to_content(_msg(), body="hi").model_dump(mode="json")
    await cb(SimpleNamespace(room_id="!r", event_id="$x", content=content))
    assert len(got) == 1
    other = MatrixCarrier.to_content(_msg(receivers=[AgentAddress(name="z")]), body="hi").model_dump(mode="json")
    await cb(SimpleNamespace(room_id="!r", event_id="$y", content=other))
    assert len(got) == 1
    assert await car.unsubscribe(sub) is True
    await cb(SimpleNamespace(room_id="!r", event_id="$z", content=content))
    assert len(got) == 1
    assert await car.unsubscribe(sub) is False
