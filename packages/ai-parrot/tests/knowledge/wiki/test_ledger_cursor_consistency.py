"""FEAT-902 coherent cursor and transactional replay contracts."""

from __future__ import annotations

import asyncio
from pathlib import Path

import aiosqlite
import pytest

from parrot.knowledge.wiki.ledger.events import LedgerEvent
from parrot.knowledge.wiki.ledger.index import LedgerIndex
from parrot.knowledge.wiki.ledger.log import LedgerLog
from parrot.knowledge.wiki.ledger.store import LedgerCursorInvalid, LedgerStore
from parrot.knowledge.wiki.store import SQLitePragmaPolicy


@pytest.fixture
def store(tmp_path: Path) -> LedgerStore:
    """Own a temporary ledger using a bounded test busy timeout."""
    return LedgerStore(str(tmp_path / "ledger.db"), sqlite_policy=SQLitePragmaPolicy(busy_timeout_s=1))


def _opened_event(number: int) -> LedgerEvent:
    """Build one deterministic issue event accepted by the materialized index."""
    return LedgerEvent(
        kind="issue.opened",
        subject=f"issue:{number:012d}",
        actor="agent:test",
        ts=f"2026-11-16T00:00:{number:02d}+00:00",
        payload={
            "title": f"Issue {number}",
            "body": "test body",
            "kind": "bug",
            "severity": "minor",
            "discovered_from": "task:TASK-5713",
            "about": [],
        },
    )


@pytest.mark.asyncio
async def test_cursor_pair_is_one_snapshot(store: LedgerStore, tmp_path: Path) -> None:
    """A WAL reader sees either peer cursor generation, never a mixed pair."""
    async with store.ledger_transaction("test.seed_cursor") as conn:
        await LedgerIndex._write_cursor(conn, 10, "event-before")

    reader_ready = asyncio.Event()
    peer_staged = asyncio.Event()
    commit_peer = asyncio.Event()
    peer_committed = asyncio.Event()

    async with aiosqlite.connect(tmp_path / "ledger.db") as reader, aiosqlite.connect(tmp_path / "ledger.db") as writer:
        await reader.execute("PRAGMA busy_timeout = 1000")
        await writer.execute("PRAGMA busy_timeout = 1000")
        async with reader.execute("PRAGMA journal_mode") as cursor:
            assert (await cursor.fetchone())[0].lower() == "wal"
        statements: list[str] = []
        await reader.set_trace_callback(statements.append)

        async def update_peer_cursor() -> None:
            """Stage a complete peer cursor and commit only when the reader has a snapshot."""
            await reader_ready.wait()
            await writer.execute("BEGIN IMMEDIATE")
            await writer.execute("UPDATE ledger_state SET value = '20' WHERE key = 'cursor_offset'")
            await writer.execute("UPDATE ledger_state SET value = 'event-after' WHERE key = 'last_event_id'")
            peer_staged.set()
            await commit_peer.wait()
            await writer.commit()
            peer_committed.set()

        peer_task = asyncio.create_task(update_peer_cursor())
        try:
            await reader.execute("BEGIN")
            assert await store.read_cursor_in(reader) == (10, "event-before")
            reader_ready.set()
            await peer_staged.wait()
            commit_peer.set()
            await peer_committed.wait()

            assert await store.read_cursor_in(reader) == (10, "event-before")
            await reader.commit()
            assert await store.read_cursor_in(reader) == (20, "event-after")
        finally:
            if not peer_task.done():
                commit_peer.set()
            await peer_task

    data_selects = [statement for statement in statements if "FROM ledger_state" in statement]
    assert len(data_selects) == 3
    assert all("cursor_offset'" in statement and "last_event_id'" in statement for statement in data_selects)


@pytest.mark.asyncio
async def test_transaction_reads_own_cursor(store: LedgerStore, tmp_path: Path) -> None:
    """Repeated sync(conn) observes its uncommitted cursor advance exactly once."""
    log = LedgerLog(str(tmp_path / "events.jsonl"))
    first_event = _opened_event(1)
    second_event = _opened_event(2)
    await asyncio.to_thread(log.append, first_event)
    _, second_offset = await asyncio.to_thread(log.append, second_event)
    index = LedgerIndex(store, log)

    async with store.ledger_transaction("test.repeated_sync") as conn:
        assert await index.sync(conn) == 2
        assert await index.sync(conn) == 0
        assert await store.read_cursor_in(conn) == (second_offset, second_event.event_id)
        async with conn.execute("SELECT count(*) FROM pages") as cursor:
            assert (await cursor.fetchone())[0] == 2

    assert await store.read_cursor() == (second_offset, second_event.event_id)


@pytest.mark.asyncio
async def test_cursor_errors_are_explicit(store: LedgerStore) -> None:
    """Absent, invalid, and failed storage reads have distinct outcomes."""
    assert await store.read_cursor() == (0, None)

    invalid_values = (("offset-only", None), ("not-an-int", "event"), ("-1", "event"), ("0", ""))
    for offset, event_id in invalid_values:
        async with store.ledger_transaction("test.invalid_cursor") as conn:
            await conn.execute("DELETE FROM ledger_state")
            if offset is not None:
                await conn.execute("INSERT INTO ledger_state (key, value) VALUES ('cursor_offset', ?)", (offset,))
            if event_id is not None:
                await conn.execute("INSERT INTO ledger_state (key, value) VALUES ('last_event_id', ?)", (event_id,))
        with pytest.raises(LedgerCursorInvalid):
            await store.read_cursor()

    async with store.ledger_transaction("test.empty_cursor") as conn:
        await conn.execute("DELETE FROM ledger_state")
    assert await store.read_cursor() == (0, None)

    closed_conn = await aiosqlite.connect(":memory:")
    await closed_conn.close()
    with pytest.raises(ValueError):
        await store.read_cursor_in(closed_conn)


@pytest.mark.asyncio
async def test_invalid_cursor_rebuild_converges(store: LedgerStore, tmp_path: Path) -> None:
    """A malformed persisted cursor rebuilds once and then remains caught up."""
    log = LedgerLog(str(tmp_path / "events.jsonl"))
    first_event = _opened_event(3)
    second_event = _opened_event(4)
    await asyncio.to_thread(log.append, first_event)
    _, second_offset = await asyncio.to_thread(log.append, second_event)
    index = LedgerIndex(store, log)

    async with store.ledger_transaction("test.invalid_cursor") as conn:
        await conn.execute("INSERT INTO ledger_state (key, value) VALUES ('cursor_offset', '99')")

    assert await index.sync() == 2
    assert await index.sync() == 0
    assert await store.read_cursor() == (second_offset, second_event.event_id)
