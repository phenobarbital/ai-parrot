"""FEAT-886 M7 — shared durable contract + Mongo-specific durability tests.

Real MongoDB, one database per test; skipped without ``MONGO_TEST_DSN``.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import pytest

from parrot.storage.backends.mongodb import ConversationMongoBackend
from parrot.storage.errors import (
    ConversationDeletedError,
    IndexNotReadyError,
    StorageUnavailableError,
    StorageWriteError,
)

from .. import durable_contract

DSN = os.environ.get("MONGO_TEST_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="MONGO_TEST_DSN not set — skipping Mongo durable contract")

UTC = timezone.utc
T0 = datetime(2026, 11, 1, 10, 0, 0, tzinfo=UTC)


@pytest.fixture
async def backend():
    b = ConversationMongoBackend(dsn=DSN, database=f"parrot_durable_{uuid.uuid4().hex[:10]}")
    await b.initialize()
    yield b
    try:
        await b._client.drop_database(b._database)
    finally:
        await b.close()


def _row(i: int, ts: datetime, seq: int = 0, **extra) -> dict:
    return {"timestamp": ts.isoformat(), "sequence": seq, "user_message": f"q{i}",
            "assistant_response": f"a{i}", **extra}


@asynccontextmanager
async def _inject_write_failure(backend):
    """Make the next durable write fail at the driver boundary (a real driver error type)."""
    from pymongo import errors as mongo_errors

    coll = backend._conversations
    original = coll.replace_one

    async def boom(*a, **kw):
        raise mongo_errors.WriteError("injected write failure")

    coll.replace_one = boom
    try:
        yield
    finally:
        coll.replace_one = original


async def _seed_legacy(backend, session_id: str, rows: list) -> None:
    for row in rows:  # pre-FEAT-886 documents: no ts_utc / seq fields at all
        await backend._conversations.insert_one({
            "user_id": durable_contract.USER, "agent_id": durable_contract.AGENT, "session_id": session_id,
            "kind": "turn", "sort_key": f"TURN#{row['turn_id']}", "updated_at": T0, **row})


@pytest.fixture
def harness(backend):
    async def expire(session_id):  # transcript TTL reaper: documents vanish, tombstones must not
        await backend._conversations.delete_many({"session_id": session_id})

    return durable_contract.DurableHarness(
        backend=backend,
        disconnect=backend.close,
        inject_write_failure=lambda: _inject_write_failure(backend),
        seed_legacy=lambda sid, rows: _seed_legacy(backend, sid, rows),
        expire_transcript=expire,
    )


@pytest.mark.parametrize("check", durable_contract.ALL_CHECKS, ids=lambda c: c.__name__)
async def test_mongo_durable_contract(check, harness):
    await check(harness)


async def test_disconnected_backend_raises_everywhere():
    b = ConversationMongoBackend(dsn=DSN, database="parrot_durable_never")  # never initialized
    for call in (lambda: b.put_turn("u", "a", "s", "t", {}), lambda: b.query_turns("u", "a", "s"),
                 lambda: b.query_turn_window("u", "a", "s", 5), lambda: b.is_deleted("u", "a", "s"),
                 lambda: b.get_index_state("u", "a", "s"), lambda: b.put_tombstone("u", "a", "s")):
        with pytest.raises(StorageUnavailableError):
            await call()


async def test_failed_write_raises_storage_write_error(backend):
    async with _inject_write_failure(backend):
        with pytest.raises(StorageWriteError):
            await backend.put_turn("u", "a", "s", "t1", _row(1, T0))


async def test_upsert_preserves_ordering_fields(backend):
    await backend.put_turn("u", "a", "s", "t1", _row(1, T0, seq=5, assistant_response="first"))
    await backend.put_turn("u", "a", "s", "t1", _row(1, T0 + timedelta(hours=9), seq=99,
                                                      assistant_response="retry"))
    [turn] = await backend.query_turn_window("u", "a", "s", 10)
    assert turn["assistant_response"] == "retry"
    assert turn["timestamp"] == T0.isoformat() and turn["sequence"] == 5
    assert "ts_utc" not in turn and "seq" not in turn  # internal fields do not leak


async def test_microsecond_ordering(backend):
    base = T0.replace(microsecond=0)
    for i, tid in enumerate(("late", "early")):  # 1 microsecond apart: millisecond BSON dates would tie
        await backend.put_turn("u", "a", "s", tid, _row(i, base + timedelta(microseconds=2 - i), seq=0))
    assert [t["turn_id"] for t in await backend.query_turn_window("u", "a", "s", 2)] == ["early", "late"]


async def test_concurrent_put_and_tombstone_then_cascade_leaves_nothing(backend):
    async def writer(i):
        try:
            await backend.put_turn("u", "a", "s", f"t{i}", _row(i, T0 + timedelta(seconds=i), seq=i))
        except ConversationDeletedError:
            pass

    await asyncio.gather(*(writer(i) for i in range(10)), backend.put_tombstone("u", "a", "s"))
    await backend.delete_thread_cascade("u", "a", "s")
    with pytest.raises(ConversationDeletedError):
        await backend.put_turn("u", "a", "s", "late", _row(99, T0))
    assert await backend.is_deleted("u", "a", "s") is True


async def test_legacy_documents_are_pending_then_ready(backend):
    await _seed_legacy(backend, "legacy", [{"turn_id": "old", "timestamp": T0.isoformat(),
                                            "user_message": "q", "assistant_response": "a"}])
    state = await backend.get_index_state(durable_contract.USER, durable_contract.AGENT, "legacy")
    assert state == "pending"
    with pytest.raises(IndexNotReadyError):
        await backend.query_turn_window(durable_contract.USER, durable_contract.AGENT, "legacy", 5)
    batch = await backend.backfill_batch(None, 10)
    assert batch.processed == 1 and batch.next_cursor is None
    assert await backend.get_index_state(durable_contract.USER, durable_contract.AGENT, "legacy") == "ready"
