"""FEAT-886 M2 — sequence round-trip, presentation mapping, publisher envelope."""
from __future__ import annotations

import asyncio

from parrot.core.events.lifecycle import TraceContext
from parrot.core.events.lifecycle.events.memory import TurnCompletedEvent
from parrot.memory import ConversationTurn
from parrot.memory.persistence import (
    TURN_COMPLETED_TOPIC,
    BusTurnPublisher,
    TurnPresentation,
)
from parrot.models.basic import CompletionUsage
from parrot.models.responses import AIMessage, SourceDocument


def _turn(**kw) -> ConversationTurn:
    return ConversationTurn(
        turn_id="turn-1", user_id="u", user_message="  raw   text  ", assistant_response="a", **kw
    )


def test_turn_sequence_round_trip():
    """``sequence`` survives to_dict/from_dict; a legacy dict (no key) loads with None."""
    data = _turn(sequence=7).to_dict()
    assert ConversationTurn.from_dict(data).sequence == 7
    data.pop("sequence")
    assert ConversationTurn.from_dict(data).sequence is None


def test_presentation_from_ai_message():
    """All mapped fields populate; attributes the message lacks become None / []."""
    msg = AIMessage(
        input="q", output="the output", response="the response", data={"k": 1}, code="print(1)",
        model="m1", provider="p1",
        usage=CompletionUsage(prompt_tokens=3, completion_tokens=5, estimated_cost=0.42),
        source_documents=[SourceDocument(source="doc-a", filename="a.txt")],
    )
    p = TurnPresentation.from_ai_message(msg, output_mode="default", response_time_ms=120, tenant="acme")
    assert p.output == "the response"
    assert p.output_mode == "default"
    assert p.data == {"k": 1}
    assert p.code == "print(1)"
    assert p.sources[0]["source"] == "doc-a" and p.sources[0]["filename"] == "a.txt"
    assert p.response_time_ms == 120 and p.tenant == "acme"
    assert p.model == "m1" and p.provider == "p1"
    assert p.cost_usd == 0.42
    assert p.usage == msg.usage.model_dump()

    bare = AIMessage(input="q", output="o", model="m", provider="p", usage=CompletionUsage())
    b = TurnPresentation.from_ai_message(bare, output_mode=None, response_time_ms=None, tenant=None)
    assert b.data is None and b.code is None and b.sources == []
    assert b.tenant is None and b.response_time_ms is None


async def test_publisher_envelope_shape():
    """Topic, the scoped event_id and the RAW turn reach a real in-memory bus subscriber."""
    from navigator_eventbus import EventBus

    bus = EventBus(transport="memory")
    received: list = []
    delivered = asyncio.Event()

    async def handler(event) -> None:
        received.append(event)
        delivered.set()

    bus.subscribe(TURN_COMPLETED_TOPIC, handler)
    turn = _turn()
    event = TurnCompletedEvent(
        trace_context=TraceContext.new_root(),
        agent_name="agent-a", chatbot_id="bot-uuid", user_id="u", session_id="s",
        turn=turn.to_dict(), presentation=TurnPresentation(output="x").model_dump(),
    )
    try:
        await BusTurnPublisher(bus).publish(event)
        await asyncio.wait_for(delivered.wait(), timeout=2)
    finally:
        await bus.close()
    got = received[0]
    assert got.event_type == TURN_COMPLETED_TOPIC
    from parrot.memory.persistence import turn_event_id

    assert got.event_id == turn_event_id("agent-a", "u", "s", turn.turn_id)
    assert got.payload["turn"]["turn_id"] == turn.turn_id  # the stored turn id stays the client's id
    assert got.payload["turn"]["user_message"] == "  raw   text  "
    assert got.payload["agent_name"] == "agent-a"


def test_event_id_has_the_scope_of_the_storage_key():
    """A retry of the same turn dedups; two conversations that reuse a client turn id do not."""
    from parrot.memory.persistence import turn_event_id

    same = turn_event_id("agent-a", "u1", "s1", "msg-1")
    assert same == turn_event_id("agent-a", "u1", "s1", "msg-1")  # deterministic: a retry gets the same id
    assert len({same,
                turn_event_id("agent-a", "u2", "s1", "msg-1"),   # other user
                turn_event_id("agent-b", "u1", "s1", "msg-1"),   # other agent
                turn_event_id("agent-a", "u1", "s2", "msg-1"),   # other session
                turn_event_id("agent-a", "u1", "s1", "msg-2")}) == 5  # other turn
