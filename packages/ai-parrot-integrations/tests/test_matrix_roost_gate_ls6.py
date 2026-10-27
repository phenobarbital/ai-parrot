"""Gate L-S6 — Roost over a real Matrix room (FEAT-747 AC-24). Opt-in: PARROT_TEST_MATRIX=1.

Start the dev homeserver with ``docker-compose.matrix.yml`` (see ``scripts/matrix/bootstrap.sh``) and provide:

* ``PARROT_TEST_MATRIX_HOMESERVER`` (default ``http://localhost:8008``)
* ``PARROT_TEST_MATRIX_MXID`` / ``PARROT_TEST_MATRIX_TOKEN`` — a user that is joined to the room
* ``PARROT_TEST_MATRIX_ROOM_ID`` — the room used by the gate
"""

import asyncio
import os
import uuid
from typing import AsyncIterator

import pytest
import pytest_asyncio

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.environ.get("PARROT_TEST_MATRIX") != "1", reason="live Matrix gate (FEAT-747 L-S6)"),
]


def _env(name: str, default: str = "") -> str:
    value = os.environ.get(name, default)
    if not value:
        pytest.skip(f"{name} is required for the live Matrix gate")
    return value


@pytest_asyncio.fixture
async def matrix_client() -> AsyncIterator[object]:
    from parrot.integrations.matrix.client import MatrixClientWrapper

    client = MatrixClientWrapper(
        _env("PARROT_TEST_MATRIX_HOMESERVER", "http://localhost:8008"),
        _env("PARROT_TEST_MATRIX_MXID"),
        _env("PARROT_TEST_MATRIX_TOKEN"),
    )
    await client.connect()
    await client.start_sync()
    try:
        yield client
    finally:
        await client.disconnect()


async def test_typed_envelope_with_readable_body(matrix_client) -> None:
    from parrot.integrations.matrix.roost import MatrixCarrier
    from parrot.roost.messages import AgentAddress, RoostMessage
    from parrot.roost.performatives import CarrierKind, InteractionProtocol, Performative

    room_id = _env("PARROT_TEST_MATRIX_ROOM_ID")
    carrier = MatrixCarrier(matrix_client, room_id=room_id, agent_name="gate-sender")
    received: "asyncio.Queue[RoostMessage]" = asyncio.Queue()

    async def inbound(msg: RoostMessage) -> None:
        await received.put(msg)

    await carrier.subscribe(AgentAddress(name="gate-receiver", carrier=CarrierKind.MATRIX), inbound)
    message_id = uuid.uuid4().hex
    msg = RoostMessage(
        message_id=message_id,
        performative=Performative.INFORM,
        protocol=InteractionProtocol.INFORM,
        conversation_id=uuid.uuid4().hex,
        sender=AgentAddress(name="gate-sender", carrier=CarrierKind.MATRIX),
        receivers=[AgentAddress(name="gate-receiver", carrier=CarrierKind.MATRIX)],
        content={"answer": 42},
    )
    content = MatrixCarrier.to_content(msg, body=msg.body or MatrixCarrier._default_render(msg)).model_dump(mode="json")
    assert content["body"].startswith("[inform] gate-sender")  # a human-readable body an ordinary client shows
    await carrier.send(msg)
    try:
        while True:
            got = await asyncio.wait_for(received.get(), timeout=30)
            if got.message_id == message_id:
                break
    finally:
        await carrier.close()
    assert got.performative is Performative.INFORM
    assert got.content == {"answer": 42}
    assert got.body and got.body.startswith("[inform]")
    rebuilt = MatrixCarrier.from_content(content, event_id="$local")
    assert rebuilt.message_id == message_id
    assert rebuilt.content == {"answer": 42}


async def test_blackboard_state_replaces_not_appends(matrix_client) -> None:
    from parrot.integrations.matrix.roost import MatrixBlackboard
    from parrot.roost.blackboard import WriterPolicy
    from parrot.integrations.matrix.events import ParrotEventType

    room_id = _env("PARROT_TEST_MATRIX_ROOM_ID")
    board = MatrixBlackboard(
        matrix_client, room_id=room_id, scope=uuid.uuid4().hex, policy=WriterPolicy(coordinator="gate-writer")
    )
    current = await board._read("digest")
    expected = current.version if current else None
    first = await board.put("digest", {"n": 1}, writer="gate-writer", expected_version=expected)
    second = await board.put("digest", {"n": 2}, writer="gate-writer", expected_version=first.version)
    assert second.version == first.version + 1
    raw = await matrix_client.get_room_state_event(room_id, ParrotEventType.BLACKBOARD, "digest")
    assert raw["version"] == second.version
    assert raw["value"] == {"n": 2}  # replaced, not appended
