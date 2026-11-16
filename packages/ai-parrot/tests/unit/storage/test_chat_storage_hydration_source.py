"""FEAT-886 M14 — ChatStorageHydrationSource: error mapping, [] -> None, key alignment, window."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from parrot.memory.hydration import (
    HydrationNotReadyError,
    HydrationSource,
    HydrationUnavailableError,
    SessionDeletedError,
)
from parrot.memory.persistence import TurnPresentation
from parrot.storage.backends.sqlite import ConversationSQLiteBackend
from parrot.storage.errors import StorageUnavailableError
from parrot.storage.hydration import ChatStorageHydrationSource
from parrot.storage.models import ChatStorageTurn

T0 = datetime(2026, 11, 1, 10, tzinfo=timezone.utc)


@pytest.fixture
async def backend(tmp_path):
    b = ConversationSQLiteBackend(path=str(tmp_path / "h.db"))
    await b.initialize()
    yield b
    await b.close()


def _turn(tid: str, sec: int, seq: int, session: str = "s1") -> ChatStorageTurn:
    return ChatStorageTurn(turn_id=tid, user_id="u1", session_id=session, agent_id="agent-name", chatbot_id="bot-uuid",
                           timestamp=T0 + timedelta(seconds=sec), sequence=seq, user_message=f"q{tid}",
                           assistant_response=f"a{tid}", presentation=TurnPresentation(output="x"))


async def _put(backend, turn: ChatStorageTurn) -> None:
    await backend.put_turn(turn.user_id, turn.agent_id, turn.session_id, turn.turn_id, turn.to_row())


async def test_returns_newest_window_ascending_with_attribution(backend):
    for i in range(1, 8):
        await _put(backend, _turn(f"t{i}", i, i))
    source = ChatStorageHydrationSource(backend)
    assert isinstance(source, HydrationSource)
    turns = await source.load_turns("agent-name", "u1", "s1", 3)
    assert [t.turn_id for t in turns] == ["t5", "t6", "t7"]
    assert all(t.chatbot_id == "bot-uuid" for t in turns)  # attribution kept for render_history
    assert turns[0].sequence == 5


async def test_key_alignment_uses_agent_name_not_user_position(backend):
    await _put(backend, _turn("t1", 1, 1))
    source = ChatStorageHydrationSource(backend)
    assert await source.load_turns("agent-name", "u1", "s1", 5) is not None
    assert await source.load_turns("u1", "agent-name", "s1", 5) is None  # swapped args hit another partition
    assert await source.max_sequence("agent-name", "u1", "s1") == 1


async def test_empty_active_session_is_none_not_a_list(backend):
    assert await ChatStorageHydrationSource(backend).load_turns("agent-name", "u1", "nothing", 5) is None


async def test_deleted_session_raises_session_deleted(backend):
    await _put(backend, _turn("t1", 1, 1))
    await backend.put_tombstone("u1", "agent-name", "s1")
    source = ChatStorageHydrationSource(backend)
    with pytest.raises(SessionDeletedError):
        await source.load_turns("agent-name", "u1", "s1", 5)
    assert await source.is_deleted("agent-name", "u1", "s1") is True


async def test_unready_index_raises_not_ready_but_deletion_wins(backend, tmp_path):
    raw = sqlite3.connect(str(tmp_path / "h.db"))
    for session in ("legacy", "legacy-dead"):
        raw.execute("INSERT INTO conversations (user_id, agent_id, session_id, kind, sort_key, payload, updated_at)"
                    " VALUES ('u1','agent-name',?,'turn','TURN#old','{\"timestamp\": \"2026-01-01T00:00:00+00:00\"}',1.0)",
                    (session,))
    raw.commit()
    raw.close()
    await backend.put_tombstone("u1", "agent-name", "legacy-dead")
    source = ChatStorageHydrationSource(backend)
    with pytest.raises(HydrationNotReadyError):
        await source.load_turns("agent-name", "u1", "legacy", 5)
    with pytest.raises(SessionDeletedError):
        await source.load_turns("agent-name", "u1", "legacy-dead", 5)


async def test_backend_failure_is_unavailable_never_empty(tmp_path):
    class _Down(ConversationSQLiteBackend):
        async def get_index_state(self, *a, **kw):
            raise StorageUnavailableError("down")

        async def is_deleted(self, *a, **kw):
            raise StorageUnavailableError("down")

        async def max_sequence(self, *a, **kw):
            raise StorageUnavailableError("down")

    down = _Down(path=str(tmp_path / "d.db"))
    source = ChatStorageHydrationSource(down)
    with pytest.raises(HydrationUnavailableError):
        await source.load_turns("a", "u", "s", 5)
    with pytest.raises(HydrationUnavailableError):
        await source.is_deleted("a", "u", "s")
    with pytest.raises(HydrationUnavailableError):
        await source.max_sequence("a", "u", "s")


async def test_corrupt_row_is_unavailable_not_silently_truncated(backend):
    await _put(backend, _turn("t1", 1, 1))
    await backend._conn.execute(
        "UPDATE conversations SET payload = json_set(payload, '$.state', 'not-a-state') WHERE sort_key='TURN#t1'")
    await backend._conn.commit()
    with pytest.raises(HydrationUnavailableError):
        await ChatStorageHydrationSource(backend).load_turns("agent-name", "u1", "s1", 5)


async def test_max_turns_must_be_positive(backend):
    with pytest.raises(ValueError):
        await ChatStorageHydrationSource(backend).load_turns("agent-name", "u1", "s1", 0)
