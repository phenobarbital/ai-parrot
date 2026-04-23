"""Unit tests for parrot.storage.backends.sqlite.ConversationSQLiteBackend.

TASK-826: SQLite Backend Implementation — FEAT-116.
"""
import time
import pytest

from parrot.storage.backends.sqlite import ConversationSQLiteBackend


@pytest.fixture
async def backend(tmp_path):
    b = ConversationSQLiteBackend(path=str(tmp_path / "parrot.db"))
    await b.initialize()
    yield b
    await b.close()


async def test_initialize_is_idempotent(tmp_path):
    path = str(tmp_path / "parrot.db")
    b = ConversationSQLiteBackend(path=path)
    await b.initialize()
    await b.initialize()  # second call must NOT raise
    assert b.is_connected is True
    await b.close()


async def test_put_and_query_thread(backend):
    await backend.put_thread("u", "a", "s1", {"title": "Hello", "created_at": "2026-04-22T00:00:00"})
    threads = await backend.query_threads("u", "a", limit=10)
    assert len(threads) == 1
    assert threads[0]["session_id"] == "s1"
    assert threads[0]["title"] == "Hello"


async def test_update_thread_changes_fields(backend):
    await backend.put_thread("u", "a", "s1", {"title": "old"})
    await backend.update_thread("u", "a", "s1", title="new")
    threads = await backend.query_threads("u", "a", limit=10)
    assert threads[0]["title"] == "new"


async def test_put_and_query_turns_newest_first(backend):
    await backend.put_thread("u", "a", "s1", {"title": "t"})
    for i in range(3):
        await backend.put_turn("u", "a", "s1", f"{i:03d}", {"text": f"turn-{i}"})
    turns = await backend.query_turns("u", "a", "s1", limit=10, newest_first=True)
    assert [t["turn_id"] for t in turns] == ["002", "001", "000"]


async def test_put_and_query_turns_oldest_first(backend):
    await backend.put_thread("u", "a", "s1", {"title": "t"})
    for i in range(3):
        await backend.put_turn("u", "a", "s1", f"{i:03d}", {"text": f"turn-{i}"})
    turns = await backend.query_turns("u", "a", "s1", limit=10, newest_first=False)
    assert [t["turn_id"] for t in turns] == ["000", "001", "002"]


async def test_delete_turn_returns_true_when_deleted(backend):
    await backend.put_thread("u", "a", "s1", {"title": "t"})
    await backend.put_turn("u", "a", "s1", "001", {"text": "x"})
    ok = await backend.delete_turn("u", "a", "s1", "001")
    assert ok is True


async def test_delete_turn_returns_false_when_missing(backend):
    ok = await backend.delete_turn("u", "a", "s1", "does-not-exist")
    assert ok is False


async def test_ttl_expiry_hides_row(tmp_path):
    b = ConversationSQLiteBackend(path=str(tmp_path / "parrot.db"), default_ttl_days=0)
    await b.initialize()
    await b.put_thread("u", "a", "sX", {"title": "expired"})
    threads = await b.query_threads("u", "a", limit=10)
    assert not any(t["session_id"] == "sX" for t in threads)
    await b.close()


async def test_delete_thread_cascade_removes_turns_and_artifacts(backend):
    await backend.put_thread("u", "a", "s1", {"title": "t"})
    await backend.put_turn("u", "a", "s1", "001", {"text": "x"})
    await backend.put_artifact("u", "a", "s1", "art1", {"artifact_type": "chart", "title": "c"})
    deleted = await backend.delete_thread_cascade("u", "a", "s1")
    assert deleted >= 2
    assert await backend.query_turns("u", "a", "s1") == []
    assert await backend.query_artifacts("u", "a", "s1") == []


async def test_artifact_roundtrip(backend):
    await backend.put_artifact(
        "u", "a", "s1", "art1",
        {"artifact_type": "chart", "title": "c", "definition": {"nested": {"k": 1}}}
    )
    got = await backend.get_artifact("u", "a", "s1", "art1")
    assert got is not None
    assert got["artifact_id"] == "art1"
    assert got["definition"] == {"nested": {"k": 1}}


async def test_get_artifact_returns_none_when_missing(backend):
    result = await backend.get_artifact("u", "a", "s1", "no-such")
    assert result is None


async def test_delete_session_artifacts(backend):
    await backend.put_artifact("u", "a", "s1", "a1", {"title": "x"})
    await backend.put_artifact("u", "a", "s1", "a2", {"title": "y"})
    count = await backend.delete_session_artifacts("u", "a", "s1")
    assert count == 2
    assert await backend.query_artifacts("u", "a", "s1") == []


async def test_sweep_expired(tmp_path):
    b = ConversationSQLiteBackend(path=str(tmp_path / "parrot.db"), default_ttl_days=0)
    await b.initialize()
    await b.put_thread("u", "a", "sX", {"title": "expired"})
    count = await b.sweep_expired()
    assert count >= 1
    await b.close()


async def test_is_connected_false_after_close(tmp_path):
    b = ConversationSQLiteBackend(path=str(tmp_path / "parrot.db"))
    await b.initialize()
    assert b.is_connected is True
    await b.close()
    assert b.is_connected is False


async def test_build_overflow_prefix_default(backend):
    prefix = backend.build_overflow_prefix("u", "a", "s", "aid")
    assert prefix == "artifacts/USER#u#AGENT#a/THREAD#s/aid"
