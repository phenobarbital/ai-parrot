"""FEAT-886 M6 — shared durable contract + Postgres-specific durability tests.

Real Postgres, one scratch database per test; skipped without ``POSTGRES_TEST_DSN``.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit, urlunsplit

import pytest

from parrot.storage.backends.postgres import ConversationPostgresBackend
from parrot.storage.errors import (
    ConversationDeletedError,
    IndexNotReadyError,
    StorageUnavailableError,
    StorageWriteError,
)

from .. import durable_contract

DSN = os.environ.get("POSTGRES_TEST_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="POSTGRES_TEST_DSN not set — skipping Postgres durable contract")

UTC = timezone.utc
T0 = datetime(2026, 11, 1, 10, 0, 0, tzinfo=UTC)
LEGACY_TABLE = """CREATE TABLE parrot_conversations (
    user_id TEXT NOT NULL, agent_id TEXT NOT NULL, session_id TEXT NOT NULL, kind TEXT NOT NULL,
    sort_key TEXT NOT NULL, payload JSONB NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ, PRIMARY KEY (user_id, agent_id, session_id, kind, sort_key))"""


def _dsn_for(dbname: str) -> str:
    return urlunsplit(urlsplit(DSN)._replace(path=f"/{dbname}"))


@pytest.fixture
async def scratch_dsn():
    """A throw-away database per test: tombstones are retained forever by design, so isolate, don't clean."""
    import asyncpg

    name = f"parrot_durable_{uuid.uuid4().hex[:12]}"
    try:
        admin = await asyncpg.connect(DSN)
        await admin.execute(f'CREATE DATABASE "{name}"')
    except Exception as exc:  # no CREATEDB privilege / unreachable server
        pytest.skip(f"cannot create a scratch database: {exc}")
    yield _dsn_for(name)
    await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    await admin.close()


@pytest.fixture
async def backend(scratch_dsn):
    b = ConversationPostgresBackend(dsn=scratch_dsn)
    await b.initialize()
    yield b
    await b.close()


def _row(i: int, ts: datetime, seq: int = 0, **extra) -> dict:
    return {"timestamp": ts.isoformat(), "sequence": seq, "user_message": f"q{i}",
            "assistant_response": f"a{i}", **extra}


@asynccontextmanager
async def _inject_write_failure(dsn: str):
    """REAL failure: a trigger makes every write to parrot_conversations raise."""
    import asyncpg

    conn = await asyncpg.connect(dsn)
    await conn.execute(
        """CREATE OR REPLACE FUNCTION parrot_test_fail_write() RETURNS trigger AS $$
           BEGIN RAISE EXCEPTION 'injected write failure'; END; $$ LANGUAGE plpgsql""")
    await conn.execute(
        "CREATE TRIGGER parrot_test_fail BEFORE INSERT OR UPDATE ON parrot_conversations"
        " FOR EACH ROW EXECUTE FUNCTION parrot_test_fail_write()")
    try:
        yield
    finally:
        await conn.execute("DROP TRIGGER IF EXISTS parrot_test_fail ON parrot_conversations")
        await conn.close()


async def _seed_legacy(dsn: str, session_id: str, rows: list) -> None:
    """Insert pre-FEAT-886 rows directly (no ts_utc / seq / turn_id)."""
    import asyncpg
    import json

    conn = await asyncpg.connect(dsn)
    try:
        for row in rows:
            await conn.execute(
                "INSERT INTO parrot_conversations (user_id, agent_id, session_id, kind, sort_key, payload)"
                " VALUES ($1, $2, $3, 'turn', $4, $5::jsonb)",
                durable_contract.USER, durable_contract.AGENT, session_id, f"TURN#{row['turn_id']}",
                json.dumps(row))
    finally:
        await conn.close()


@pytest.fixture
def harness(backend, scratch_dsn):
    async def expire(session_id):  # simulate TTL expiry: rows move into the past
        import asyncpg

        conn = await asyncpg.connect(scratch_dsn)
        try:
            await conn.execute(
                "UPDATE parrot_conversations SET expires_at = now() - interval '1 day' WHERE session_id = $1",
                session_id)
        finally:
            await conn.close()

    return durable_contract.DurableHarness(
        backend=backend,
        disconnect=backend.close,
        inject_write_failure=lambda: _inject_write_failure(scratch_dsn),
        seed_legacy=lambda sid, rows: _seed_legacy(scratch_dsn, sid, rows),
        expire_transcript=expire,
    )


@pytest.mark.parametrize("check", durable_contract.ALL_CHECKS, ids=lambda c: c.__name__)
async def test_postgres_durable_contract(check, harness):
    await check(harness)


async def test_disconnected_backend_raises_everywhere(scratch_dsn):
    b = ConversationPostgresBackend(dsn=scratch_dsn)  # never initialized
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
    assert turn["assistant_response"] == "retry"
    assert turn["timestamp"] == T0.isoformat() and turn["sequence"] == 5


async def test_equal_timestamp_ties_use_byte_order_not_locale(backend):
    for tid in ("a", "B", "c", "D"):  # "C" collation: B < D < a < c ; a locale collation interleaves them
        await backend.put_turn("u", "a", "s", tid, _row(0, T0, seq=1))
    window = await backend.query_turn_window("u", "a", "s", 4)
    assert [t["turn_id"] for t in window] == ["B", "D", "a", "c"]


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


async def test_tombstone_survives_restart(scratch_dsn):
    b = ConversationPostgresBackend(dsn=scratch_dsn)
    await b.initialize()
    await b.put_tombstone("u", "a", "s")
    await b.close()
    b = ConversationPostgresBackend(dsn=scratch_dsn)
    await b.initialize()
    try:
        assert await b.is_deleted("u", "a", "s") is True
        with pytest.raises(ValueError):
            await b.put_tombstone("u", "a", "s", "")
    finally:
        await b.close()


async def test_legacy_table_migrates_and_keeps_data(scratch_dsn):
    import asyncpg
    import json

    raw = await asyncpg.connect(scratch_dsn)
    await raw.execute(LEGACY_TABLE)
    await raw.execute(
        "INSERT INTO parrot_conversations (user_id, agent_id, session_id, kind, sort_key, payload)"
        " VALUES ('u','a','s','turn','TURN#old',$1::jsonb)",
        json.dumps({"timestamp": T0.isoformat(), "user_message": "q", "assistant_response": "a"}))
    await raw.close()
    b = ConversationPostgresBackend(dsn=scratch_dsn)
    await b.initialize()
    try:
        assert await b.get_index_state("u", "a", "s") == "pending"
        with pytest.raises(IndexNotReadyError):
            await b.query_turn_window("u", "a", "s", 5)
        assert [t["turn_id"] for t in await b.query_turns("u", "a", "s")] == ["old"]
        batch = await b.backfill_batch(None, 10)
        assert batch.processed == 1 and batch.next_cursor is None
        assert await b.get_index_state("u", "a", "s") == "ready"
    finally:
        await b.close()


async def test_failed_write_raises_storage_write_error(backend, scratch_dsn):
    async with _inject_write_failure(scratch_dsn):
        with pytest.raises(StorageWriteError):
            await backend.put_turn("u", "a", "s", "t1", _row(1, T0))
