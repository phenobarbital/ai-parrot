"""Shared durable-contract checks (FEAT-886 M4). NOT a test module: no ``test_`` prefix, never collected.

Each ``check_*`` coroutine takes a :class:`DurableHarness` built by a backend's own test file
(TASK-5574 SQLite, 5575 Postgres, 5576 Mongo, 5577 DynamoDB) and asserts ONE clause of the
spec §4 "Backend contract suite". A clause that cannot run on a backend raises ``pytest.skip``
from the HARNESS hook, never here.
"""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Awaitable, Callable, List

import pytest

from parrot.storage.backends.base import ConversationBackend
from parrot.storage.errors import (
    ConversationDeletedError,
    IndexNotReadyError,
    StorageUnavailableError,
    StorageWriteError,
)

USER, AGENT, SESSION = "u-durable", "agent-durable", "s-durable"


@dataclass
class DurableHarness:
    """Backend-specific hooks the shared checks need.

    Attributes:
        backend: The backend under test (already initialized and connected).
        disconnect: Make ``backend.is_connected`` False (e.g. ``close()``).
        inject_write_failure: ``() -> async context manager`` making the next durable write fail.
        seed_legacy: ``(session_id, rows)`` inserts pre-FEAT-886 rows (random ``turn_id``,
            no chronological entry); a row may carry a bad ``timestamp``.
        expire_transcript: ``(session_id)`` simulates TTL expiry / cleanup of the turns
            (tombstones must survive).
    """

    backend: ConversationBackend
    disconnect: Callable[[], Awaitable[None]]
    inject_write_failure: Callable[[], AbstractAsyncContextManager]
    seed_legacy: Callable[[str, List[dict]], Awaitable[None]]
    expire_transcript: Callable[[str], Awaitable[None]]


def _turn(turn_id: str, ts: str, seq: int, text: str = "x") -> dict:
    """A turn payload with emitter-owned ordering fields (ISO-8601 UTC timestamp)."""
    return {"turn_id": turn_id, "timestamp": ts, "sequence": seq, "user_message": text, "assistant_response": text}


def _ts(second: int) -> str:
    return f"2026-01-01T00:00:{second:02d}+00:00"


async def _put(b: ConversationBackend, session: str, turn: dict) -> None:
    await b.put_turn(USER, AGENT, session, turn["turn_id"], turn)


async def _window(b: ConversationBackend, session: str, limit: int = 50) -> List[dict]:
    return await b.query_turn_window(USER, AGENT, session, limit)


async def check_disconnected_raises(h: DurableHarness) -> None:
    """put_turn / query_turn_window / is_deleted / deleted_session_ids raise StorageUnavailableError on a
    disconnected backend."""
    await h.disconnect()
    b = h.backend
    with pytest.raises(StorageUnavailableError):
        await _put(b, "s-disc", _turn("t1", _ts(1), 1))
    with pytest.raises(StorageUnavailableError):
        await _window(b, "s-disc")
    with pytest.raises(StorageUnavailableError):
        await b.is_deleted(USER, AGENT, "s-disc")
    with pytest.raises(StorageUnavailableError):
        await b.deleted_session_ids(USER, AGENT, ["s-disc"])


async def check_failed_write_raises(h: DurableHarness) -> None:
    """A failed durable write raises StorageWriteError and stores nothing."""
    s = "s-failwrite"
    async with h.inject_write_failure():
        with pytest.raises(StorageWriteError):
            await _put(h.backend, s, _turn("t1", _ts(1), 1))
    assert await _window(h.backend, s) == []


async def check_put_turn_idempotent(h: DurableHarness) -> None:
    """Same turn_id twice -> one turn, ordering fields unchanged by the second write."""
    s = "s-idem"
    await _put(h.backend, s, _turn("t1", _ts(1), 1))
    await _put(h.backend, s, _turn("t1", _ts(30), 9))
    rows = await _window(h.backend, s)
    assert len(rows) == 1
    assert rows[0]["sequence"] == 1
    assert str(rows[0]["timestamp"]).startswith("2026-01-01T00:00:01")


async def check_window_newest_ascending(h: DurableHarness) -> None:
    """Random and reverse-lexical IDs, equal timestamps, rows > limit -> the same newest window, ascending."""
    s = "s-window"
    ids = ["zz", "b3", "a9", "m1", "c0", "y7", "d2", "x5"]
    turns = [_turn(tid, _ts(i // 2), i % 3) for i, tid in enumerate(ids)]  # equal ts pairs, repeated seqs
    for t in reversed(turns):
        await _put(h.backend, s, t)
    limit = 5
    expected = [
        t["turn_id"] for t in sorted(turns, key=lambda t: (t["timestamp"], t["sequence"], t["turn_id"]))[-limit:]
    ]
    got = [t["turn_id"] for t in await _window(h.backend, s, limit)]
    assert got == expected


async def check_tombstone_blocks_put(h: DurableHarness) -> None:
    """put_turn after put_tombstone raises ConversationDeletedError (session AND turn scoped); idempotent."""
    b = h.backend
    s = "s-tomb"
    await _put(b, s, _turn("keep", _ts(1), 1))
    await b.put_tombstone(USER, AGENT, s, "gone")
    await b.put_tombstone(USER, AGENT, s, "gone")  # idempotent
    assert await b.is_deleted(USER, AGENT, s, "gone") is True
    assert await b.is_deleted(USER, AGENT, s) is False
    with pytest.raises(ConversationDeletedError):
        await _put(b, s, _turn("gone", _ts(2), 2))
    await _put(b, s, _turn("other", _ts(3), 3))  # only that turn is refused
    await b.put_tombstone(USER, AGENT, s)
    assert await b.is_deleted(USER, AGENT, s) is True
    with pytest.raises(ConversationDeletedError):
        await _put(b, s, _turn("late", _ts(4), 4))
    with pytest.raises(ConversationDeletedError):
        await _window(b, s)


async def check_tombstone_survives_cleanup(h: DurableHarness) -> None:
    """Tombstones survive delete_thread_cascade and transcript expiry."""
    b = h.backend
    s = "s-cleanup"
    await _put(b, s, _turn("t1", _ts(1), 1))
    await b.put_tombstone(USER, AGENT, s)
    await b.delete_thread_cascade(USER, AGENT, s)
    await h.expire_transcript(s)
    assert await b.is_deleted(USER, AGENT, s) is True


async def check_index_state(h: DurableHarness) -> None:
    """Legacy sessions report pending / invalid; new sessions ready; not-ready window raises IndexNotReadyError."""
    b = h.backend
    legacy = lambda tid, ts: {
        "turn_id": tid,
        "timestamp": ts,
        "user_message": "q",
        "assistant_response": "a",
    }  # noqa: E731
    await h.seed_legacy("s-legacy-ok", [legacy("l1", _ts(1)), legacy("l2", _ts(2))])
    await h.seed_legacy("s-legacy-bad", [legacy("b1", _ts(1)), legacy("b2", "not-a-date")])
    assert await b.get_index_state(USER, AGENT, "s-legacy-ok") == "pending"
    with pytest.raises(IndexNotReadyError):
        await _window(b, "s-legacy-ok")
    cursor = None
    while True:
        batch = await b.backfill_batch(cursor, 100)
        cursor = batch.next_cursor
        if cursor is None:
            break
    assert await b.get_index_state(USER, AGENT, "s-legacy-ok") == "ready"
    assert await b.get_index_state(USER, AGENT, "s-legacy-bad") == "invalid"
    with pytest.raises(IndexNotReadyError):
        await _window(b, "s-legacy-bad")
    await _put(b, "s-new", _turn("n1", _ts(1), 1))
    assert await b.get_index_state(USER, AGENT, "s-new") == "ready"


async def check_max_sequence(h: DurableHarness) -> None:
    """max_sequence is the highest stored sequence, 0 when none."""
    b = h.backend
    assert await b.max_sequence(USER, AGENT, "s-maxseq") == 0
    await _put(b, "s-maxseq", _turn("t1", _ts(1), 3))
    await _put(b, "s-maxseq", _turn("t2", _ts(2), 8))
    await _put(b, "s-maxseq", _turn("t3", _ts(3), 5))
    assert await b.max_sequence(USER, AGENT, "s-maxseq") == 8


async def check_backfill_batch_resumable(h: DurableHarness) -> None:
    """backfill_batch pages with a cursor, returns BackfillBatch, and a second run is a no-op."""
    b = h.backend
    rows = [
        {"turn_id": f"r{i:02d}", "timestamp": _ts(i), "user_message": "q", "assistant_response": "a"} for i in range(7)
    ]
    await h.seed_legacy("s-bf-ok", rows)
    await h.seed_legacy(
        "s-bf-bad", [{"turn_id": "bad1", "timestamp": "garbage", "user_message": "q", "assistant_response": "a"}]
    )
    processed, cursor, invalid, steps = 0, None, set(), 0
    while steps < 100:
        batch = await b.backfill_batch(cursor, 3)
        processed += batch.processed
        invalid.update(batch.invalid_sessions)
        cursor = batch.next_cursor
        steps += 1
        if cursor is None:
            break
    assert cursor is None
    assert processed >= 7
    assert any("s-bf-bad" in s for s in invalid)
    again = await b.backfill_batch(None, 100)
    assert again.processed == 0


async def check_deleted_turn_ids(h: DurableHarness) -> None:
    """deleted_turn_ids returns exactly the TURN tombstones of the session in one read: no session tombstone,
    no other session's, no other agent's."""
    b = h.backend
    s, other = "s-batch-tomb", "s-batch-other"
    assert await b.deleted_turn_ids(USER, AGENT, s) == set()
    await b.put_tombstone(USER, AGENT, s, "t-a")
    await b.put_tombstone(USER, AGENT, s, "t-b")
    await b.put_tombstone(USER, AGENT, s, "t-a")  # idempotent
    await b.put_tombstone(USER, AGENT, other, "t-other")
    await b.put_tombstone(USER, AGENT + "-2", s, "t-agent2")
    assert await b.deleted_turn_ids(USER, AGENT, s) == {"t-a", "t-b"}
    await b.put_tombstone(USER, AGENT, s)  # a session tombstone is not a turn id
    assert await b.deleted_turn_ids(USER, AGENT, s) == {"t-a", "t-b"}


async def check_deleted_session_ids(h: DurableHarness) -> None:
    """deleted_session_ids returns exactly the SESSION-tombstoned members of its input in one batched read:
    no turn tombstone, no other agent's, no other user's, no id that was not asked for; empty input → empty set;
    150 ids cross DynamoDB's 100-key BatchGetItem chunk."""
    b = h.backend
    asked = [f"s-many-{i:03d}" for i in range(150)]
    assert await b.deleted_session_ids(USER, AGENT, []) == set()
    assert await b.deleted_session_ids(USER, AGENT, asked) == set()
    for sid in ("s-many-000", "s-many-099", "s-many-149"):
        await b.put_tombstone(USER, AGENT, sid)
    await b.put_tombstone(USER, AGENT, "s-many-149")  # idempotent
    await b.put_tombstone(USER, AGENT, "s-many-050", "t-1")  # a turn tombstone is not a session tombstone
    await b.put_tombstone(USER, AGENT + "-2", "s-many-001")  # another agent's
    await b.put_tombstone(USER + "-2", AGENT, "s-many-002")  # another user's
    await b.put_tombstone(USER, AGENT, "s-not-asked")
    assert await b.deleted_session_ids(USER, AGENT, asked) == {"s-many-000", "s-many-099", "s-many-149"}
    assert await b.deleted_session_ids(USER, AGENT, ["s-many-099", "s-many-099", "s-many-098"]) == {"s-many-099"}


async def check_is_deleted_turn_includes_session(h: DurableHarness) -> None:
    """is_deleted(…, turn_id) means "the session OR that turn is tombstoned"; a turn tombstone never deletes
    the session."""
    b = h.backend
    turn_only, whole = "s-turn-only", "s-whole"
    await b.put_tombstone(USER, AGENT, turn_only, "t-gone")
    assert await b.is_deleted(USER, AGENT, turn_only, "t-gone") is True
    assert await b.is_deleted(USER, AGENT, turn_only, "t-alive") is False
    assert await b.is_deleted(USER, AGENT, turn_only) is False
    assert await b.is_deleted(USER, AGENT, whole, "t-any") is False
    await b.put_tombstone(USER, AGENT, whole)
    assert await b.is_deleted(USER, AGENT, whole) is True
    assert await b.is_deleted(USER, AGENT, whole, "t-any") is True  # never stored, still deleted with its session


ALL_CHECKS: List[Callable[[DurableHarness], Awaitable[None]]] = [
    check_disconnected_raises,
    check_failed_write_raises,
    check_put_turn_idempotent,
    check_window_newest_ascending,
    check_tombstone_blocks_put,
    check_tombstone_survives_cleanup,
    check_index_state,
    check_max_sequence,
    check_backfill_batch_resumable,
    check_deleted_turn_ids,
    check_deleted_session_ids,
    check_is_deleted_turn_includes_session,
]
