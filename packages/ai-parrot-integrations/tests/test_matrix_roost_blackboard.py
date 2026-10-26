"""Tests for the Matrix room-state blackboard (FEAT-747 M12), with a mocked client."""
from unittest.mock import MagicMock

import pytest

from parrot.integrations.matrix.events import ParrotEventType
from parrot.integrations.matrix.roost import MatrixBlackboard
from parrot.roost.blackboard import StaleWriteError, WriterDeniedError, WriterPolicy


class _FakeRoom:
    """In-memory stand-in for the room state API of MatrixClientWrapper."""

    def __init__(self) -> None:
        self.state: dict = {}
        self.writes: list = []
        self.client = MagicMock()

        async def set_room_state(room_id, event_type, content, state_key=""):
            self.state[(room_id, event_type, state_key)] = content
            self.writes.append((event_type, state_key, content))
            return "$s"

        async def get_room_state_event(room_id, event_type, state_key=""):
            return self.state.get((room_id, event_type, state_key))

        self.client.set_room_state = set_room_state
        self.client.get_room_state_event = get_room_state_event


def _board(room: _FakeRoom) -> MatrixBlackboard:
    return MatrixBlackboard(room.client, room_id="!r", scope="s", policy=WriterPolicy())


async def test_put_replaces_state_and_bumps_version():
    room = _FakeRoom()
    bb = _board(room)
    e1 = await bb.put("digest", {"a": 1}, writer="w", expected_version=None)
    e2 = await bb.put("digest", {"a": 2}, writer="w", expected_version=1)
    assert (e1.version, e2.version) == (1, 2)
    assert room.writes[-1][0] == ParrotEventType.BLACKBOARD and room.writes[-1][1] == "digest"
    assert room.state[("!r", ParrotEventType.BLACKBOARD, "digest")]["value"] == {"a": 2}
    got = await bb.get("digest", reader="anyone")
    assert got is not None and got.version == 2 and got.value == {"a": 2}


async def test_stale_version_refused():
    room = _FakeRoom()
    bb = _board(room)
    await bb.put("digest", 1, writer="w", expected_version=None)
    with pytest.raises(StaleWriteError):
        await bb.put("digest", 2, writer="w", expected_version=5)
    with pytest.raises(StaleWriteError):
        await bb.put("digest", 2, writer="w", expected_version=None)
    assert len(room.writes) == 1


async def test_writer_denied_and_subscriber_notified():
    room = _FakeRoom()
    bb = _board(room)
    with pytest.raises(WriterDeniedError):
        await bb.put("roster", {}, writer="intruder", expected_version=None)
    seen = []

    async def cb(msg):
        seen.append(msg)

    await bb.subscribe("roster", cb, subscriber_name="s")
    await bb.put("roster", {"k": 1}, writer="harness", expected_version=None)
    assert len(seen) == 1
    assert await bb.keys(reader="x") == ["roster"]
