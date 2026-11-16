"""FEAT-886 M5 — shared durable contract + SQLite-specific durability tests (real SQLite, no mocks)."""
from __future__ import annotations

import asyncio
import json
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import pytest

from parrot.storage.backends.sqlite import ConversationSQLiteBackend
from parrot.storage.errors import (
    ConversationDeletedError,
    IndexNotReadyError,
    StorageUnavailableError,
    StorageWriteError,
)

from .. import durable_contract

UTC = timezone.utc
T0 = datetime(2026, 11, 1, 10, 0, 0, tzinfo=UTC)


@pytest.fixture
async def backend(tmp_path):
    b = ConversationSQLiteBackend(path=str(tmp_path / "durable.db"))
    await b.initialize()
    yield b
    await b.close()


def _row(i: int, ts: datetime, seq: int = 0, **extra) -> dict:
    return {"timestamp": ts.isoformat(), "sequence": seq, "user_message": f"q{i}",
            "assistant_response": f"a{i}", **extra}


@asynccontextmanager
async def _inject_write_failure(backend):  # REAL failure: SQLite rejects every write
    await backend._conn.execute("PRAGMA query_only = ON")
    try:
        yield
    finally:
        await backend._conn.execute("PRAGMA query_only = OFF")


async def _seed_legacy(path: str, session_id: str, rows: list) -> None:
    """Insert pre-FEAT-886 rows with the stdlib: no ts_utc/seq/turn_id columns are written."""
    raw = sqlite3.connect(path)
    for row in rows:
        raw.execute(
            "INSERT INTO conversations (user_id, agent_id, session_id, kind, sort_key, payload,"
            " updated_at, expires_at) VALUES (?, ?, ?, 'turn', ?, ?, 1.0, NULL)",
            (durable_contract.USER, durable_contract.AGENT, session_id,
             f"TURN#{row['turn_id']}", json.dumps(row)),
        )
    raw.commit()
    raw.close()


@pytest.fixture
def harness(backend, tmp_path):
    async def expire(session_id):  # simulate TTL expiry: rows become past-due, then swept
        await backend._conn.execute("UPDATE conversations SET expires_at = 1 WHERE session_id = ?", (session_id,))
        await backend.sweep_expired()

    return durable_contract.DurableHarness(
        backend=backend,
        disconnect=backend.close,
        inject_write_failure=lambda: _inject_write_failure(backend),
        seed_legacy=lambda sid, rows: _seed_legacy(str(tmp_path / "durable.db"), sid, rows),
        expire_transcript=expire,
    )


@pytest.mark.parametrize("check", durable_contract.ALL_CHECKS, ids=lambda c: c.__name__)
async def test_sqlite_durable_contract(check, harness):
    await check(harness)


async def test_failed_write_raises_storage_write_error(backend):
    async with _inject_write_failure(backend):
        with pytest.raises(StorageWriteError):
            await backend.put_turn("u", "a", "s", "t1", _row(1, T0))
    await backend.put_turn("u", "a", "s", "t1", _row(1, T0))  # recovers once writable


async def test_disconnected_backend_raises_everywhere(tmp_path):
    b = ConversationSQLiteBackend(path=str(tmp_path / "x.db"))  # never initialized
    for call in (lambda: b.put_turn("u", "a", "s", "t", {}), lambda: b.query_turns("u", "a", "s"),
                 lambda: b.query_turn_window("u", "a", "s", 5), lambda: b.is_deleted("u", "a", "s"),
                 lambda: b.get_index_state("u", "a", "s"), lambda: b.put_tombstone("u", "a", "s")):
        with pytest.raises(StorageUnavailableError):
            await call()


async def test_upsert_preserves_ordering_fields(backend):
    await backend.put_turn("u", "a", "s", "t1", _row(1, T0, seq=5, assistant_response="first"))
    await backend.put_turn("u", "a", "s", "t1", _row(1, T0 + timedelta(hours=9), seq=99,
                                                      assistant_response="retry"))
    [turn] = await backend.query_turn_window("u", "a", "s", 10)
    assert turn["assistant_response"] == "retry"  # payload replaced
    assert turn["timestamp"] == T0.isoformat() and turn["sequence"] == 5  # ordering kept


async def test_tombstone_survives_restart_cascade_and_sweep(tmp_path):
    path = str(tmp_path / "t.db")
    b = ConversationSQLiteBackend(path=path, default_ttl_days=0)
    await b.initialize()
    await b.put_turn("u", "a", "s", "t1", _row(1, T0))
    await b.put_tombstone("u", "a", "s")
    await b.put_tombstone("u", "a", "s2", "only-this")
    await b.delete_thread_cascade("u", "a", "s")
    await b.sweep_expired()
    await b.close()
    b = ConversationSQLiteBackend(path=path)
    await b.initialize()
    try:
        assert await b.is_deleted("u", "a", "s") is True
        assert await b.is_deleted("u", "a", "s2", "only-this") is True
        assert await b.is_deleted("u", "a", "s2", "other") is False
        with pytest.raises(ConversationDeletedError):
            await b.put_turn("u", "a", "s", "t9", _row(9, T0))
        with pytest.raises(ValueError):
            await b.put_tombstone("u", "a", "s", "")
    finally:
        await b.close()


async def test_concurrent_put_and_tombstone_never_resurrects(backend):
    async def writer(i):
        try:
            await backend.put_turn("u", "a", "s", f"t{i}", _row(i, T0 + timedelta(seconds=i), seq=i))
        except ConversationDeletedError:
            pass

    await asyncio.gather(*(writer(i) for i in range(10)), backend.put_tombstone("u", "a", "s"))
    with pytest.raises(ConversationDeletedError):
        await backend.put_turn("u", "a", "s", "late", _row(99, T0))
    cursor = await backend._conn.execute(
        "SELECT COUNT(*) AS n FROM conversations WHERE session_id='s' AND turn_id='late'")
    assert (await cursor.fetchone())["n"] == 0


async def test_legacy_database_migrates_and_keeps_data(tmp_path):
    path = str(tmp_path / "legacy.db")
    raw = sqlite3.connect(path)
    raw.execute(
        "CREATE TABLE conversations (user_id TEXT NOT NULL, agent_id TEXT NOT NULL, session_id TEXT NOT NULL,"
        " kind TEXT NOT NULL, sort_key TEXT NOT NULL, payload TEXT NOT NULL, updated_at REAL NOT NULL,"
        " expires_at REAL, PRIMARY KEY (user_id, agent_id, session_id, kind, sort_key))")
    raw.execute("INSERT INTO conversations VALUES ('u','a','s','turn','TURN#old',?,1.0,NULL)",
                (json.dumps({"timestamp": T0.isoformat(), "user_message": "q", "assistant_response": "a"}),))
    raw.commit()
    raw.close()
    b = ConversationSQLiteBackend(path=path)
    await b.initialize()
    try:
        assert await b.get_index_state("u", "a", "s") == "pending"
        with pytest.raises(IndexNotReadyError):
            await b.query_turn_window("u", "a", "s", 5)
        assert [t["turn_id"] for t in await b.query_turns("u", "a", "s")] == ["old"]
        batch = await b.backfill_batch(None, 10)
        assert batch.processed == 1 and batch.next_cursor is None
        assert await b.get_index_state("u", "a", "s") == "ready"
        assert [t["turn_id"] for t in await b.query_turn_window("u", "a", "s", 5)] == ["old"]
    finally:
        await b.close()


async def test_window_query_uses_the_chrono_index(backend):
    cursor = await backend._conn.execute(
        "EXPLAIN QUERY PLAN " + backend._SELECT_WINDOW, ("u", "a", "s", 0.0, 5))
    plan = " ".join(str(r["detail"]) for r in await cursor.fetchall())
    assert "idx_conv_turn_chrono" in plan
    assert "TEMP B-TREE" not in plan  # ORDER BY is served by the index, no sort


async def test_backfill_skips_tombstoned_and_new_rows(backend, tmp_path):
    await _seed_legacy(str(tmp_path / "durable.db"), "dead", [
        {"turn_id": "d1", "timestamp": T0.isoformat(), "user_message": "q", "assistant_response": "a"}])
    await backend.put_tombstone(durable_contract.USER, durable_contract.AGENT, "dead")
    await backend.put_turn("u", "a", "new", "n1", _row(1, T0))
    batch = await backend.backfill_batch(None, 50)
    assert batch.processed == 0


async def test_equal_timestamp_and_sequence_ties_break_on_turn_id(backend):
    for tid in ("c", "a", "d", "b"):  # same ts, same seq: only turn_id orders them
        await backend.put_turn("u", "a", "s", tid, _row(0, T0, seq=1))
    window = await backend.query_turn_window("u", "a", "s", 3)
    assert [t["turn_id"] for t in window] == ["b", "c", "d"]
