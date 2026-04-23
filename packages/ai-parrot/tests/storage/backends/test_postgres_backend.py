"""Unit tests for parrot.storage.backends.postgres.ConversationPostgresBackend.

TASK-827: PostgreSQL Backend Implementation — FEAT-116.

These tests skip when POSTGRES_TEST_DSN is not set.
"""
import os
import pytest

from parrot.storage.backends.postgres import ConversationPostgresBackend

DSN = os.environ.get("POSTGRES_TEST_DSN")
pytestmark = pytest.mark.skipif(
    not DSN,
    reason="POSTGRES_TEST_DSN not set — skipping Postgres backend tests",
)


@pytest.fixture
async def backend():
    b = ConversationPostgresBackend(dsn=DSN)
    await b.initialize()
    yield b
    # Clean up test rows
    try:
        await b.delete_thread_cascade("u", "a", "s1")
        for i in range(3):
            await b.delete_thread_cascade("u", "a", f"sess-{i}")
    except Exception:
        pass
    await b.close()


async def test_initialize_is_idempotent():
    b = ConversationPostgresBackend(dsn=DSN)
    await b.initialize()
    await b.initialize()
    assert b.is_connected is True
    await b.close()


async def test_put_and_query_thread(backend):
    await backend.put_thread("u", "a", "s1", {"title": "Hello"})
    threads = await backend.query_threads("u", "a", limit=10)
    assert any(t["session_id"] == "s1" and t["title"] == "Hello" for t in threads)


async def test_jsonb_roundtrip_preserves_nested(backend):
    await backend.put_artifact("u", "a", "s1", "art-1", {
        "artifact_type": "chart",
        "title": "c",
        "definition": {"nested": {"a": 1, "b": [1, 2, 3]}},
    })
    got = await backend.get_artifact("u", "a", "s1", "art-1")
    assert got["definition"] == {"nested": {"a": 1, "b": [1, 2, 3]}}


async def test_query_threads_newest_first(backend):
    for i, title in enumerate(["first", "second", "third"]):
        await backend.put_thread("u", "a", f"sess-{i}", {"title": title})
    threads = await backend.query_threads("u", "a", limit=10)
    titles = [t["title"] for t in threads if t.get("title") in {"first", "second", "third"}]
    assert titles[0] == "third"


async def test_delete_turn(backend):
    await backend.put_thread("u", "a", "s1", {"title": "t"})
    await backend.put_turn("u", "a", "s1", "001", {"text": "x"})
    ok = await backend.delete_turn("u", "a", "s1", "001")
    assert ok is True
    ok2 = await backend.delete_turn("u", "a", "s1", "001")
    assert ok2 is False


async def test_build_overflow_prefix(backend):
    assert backend.build_overflow_prefix("u", "a", "s", "aid") == \
        "artifacts/USER#u#AGENT#a/THREAD#s/aid"
