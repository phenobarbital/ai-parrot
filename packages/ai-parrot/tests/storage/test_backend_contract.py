"""Shared backend contract test suite.

Exercises every ConversationBackend method against all available backends.
Only ``sqlite`` runs unconditionally; others skip when their DSN is unset or
moto is not installed.

TASK-830: Shared Backend Contract Test Suite — FEAT-116.
"""
import pytest


async def test_initialize_idempotent(any_backend):
    """Calling initialize() twice must not raise and leave is_connected True."""
    await any_backend.initialize()  # second call
    assert any_backend.is_connected is True


async def test_thread_roundtrip(any_backend):
    """put_thread + query_threads returns the thread with correct fields."""
    await any_backend.put_thread("u", "a", "s1", {"title": "Hello", "message_count": 0})
    threads = await any_backend.query_threads("u", "a", limit=10)
    match = next((t for t in threads if t["session_id"] == "s1"), None)
    assert match is not None
    assert match["title"] == "Hello"


async def test_turn_ordering_newest_first(any_backend):
    """Three turns → newest_first=True returns descending turn_id."""
    await any_backend.put_thread("u", "a", "s1", {"title": "t"})
    for i in range(3):
        await any_backend.put_turn("u", "a", "s1", f"{i:03d}", {"text": f"t-{i}"})
    turns = await any_backend.query_turns("u", "a", "s1", limit=10, newest_first=True)
    ids = [t["turn_id"] for t in turns]
    assert ids == ["002", "001", "000"]


async def test_turn_ordering_oldest_first(any_backend):
    """Three turns → newest_first=False returns ascending turn_id."""
    await any_backend.put_thread("u", "a", "s1", {"title": "t"})
    for i in range(3):
        await any_backend.put_turn("u", "a", "s1", f"{i:03d}", {"text": f"t-{i}"})
    turns = await any_backend.query_turns("u", "a", "s1", limit=10, newest_first=False)
    ids = [t["turn_id"] for t in turns]
    assert ids == ["000", "001", "002"]


async def test_delete_turn(any_backend):
    """delete_turn returns True on existing turn, False on missing."""
    await any_backend.put_thread("u", "a", "s1", {"title": "t"})
    await any_backend.put_turn("u", "a", "s1", "001", {"text": "x"})
    ok = await any_backend.delete_turn("u", "a", "s1", "001")
    assert ok is True
    ok2 = await any_backend.delete_turn("u", "a", "s1", "does-not-exist")
    assert ok2 is False


async def test_delete_thread_cascade(any_backend):
    """delete_thread_cascade removes all turns + artifacts; returns non-zero count."""
    await any_backend.put_thread("u", "a", "s1", {"title": "t"})
    for i in range(3):
        await any_backend.put_turn("u", "a", "s1", f"{i:03d}", {"text": "x"})
    await any_backend.put_artifact(
        "u", "a", "s1", "art1", {"artifact_type": "chart", "title": "c"}
    )

    deleted = await any_backend.delete_thread_cascade("u", "a", "s1")
    assert deleted >= 3  # at least 3 turns; some backends count thread row too
    assert await any_backend.query_turns("u", "a", "s1") == []


async def test_artifact_roundtrip_inline_payload(any_backend):
    """put_artifact → get_artifact preserves nested dict structure."""
    payload = {
        "artifact_type": "chart",
        "title": "c",
        "definition": {"nested": {"a": 1, "b": [1, 2, 3]}},
        "created_by": "user",
    }
    await any_backend.put_artifact("u", "a", "s1", "art", payload)
    got = await any_backend.get_artifact("u", "a", "s1", "art")
    assert got is not None
    assert got["definition"] == {"nested": {"a": 1, "b": [1, 2, 3]}}


async def test_artifact_list_has_id_and_type(any_backend):
    """query_artifacts returns rows that include artifact_id."""
    await any_backend.put_artifact(
        "u", "a", "s1", "art2",
        {"artifact_type": "chart", "title": "x", "created_by": "user"},
    )
    items = await any_backend.query_artifacts("u", "a", "s1")
    assert any(i.get("artifact_id") == "art2" for i in items)


async def test_delete_session_artifacts(any_backend):
    """delete_session_artifacts removes all artifacts for a session."""
    for i in range(2):
        await any_backend.put_artifact(
            "u", "a", "s1", f"a{i}", {"title": f"t{i}"}
        )
    count = await any_backend.delete_session_artifacts("u", "a", "s1")
    assert count >= 2
    remaining = await any_backend.query_artifacts("u", "a", "s1")
    assert remaining == []


async def test_build_overflow_prefix_matches_dynamodb_layout(any_backend):
    """Every backend must return the DynamoDB-compatible prefix format."""
    result = any_backend.build_overflow_prefix("u", "a", "s", "aid")
    assert result == "artifacts/USER#u#AGENT#a/THREAD#s/aid"


async def test_update_thread_changes_fields(any_backend):
    """update_thread(..., title='new') reflects in query_threads."""
    await any_backend.put_thread("u", "a", "s1", {"title": "old", "count": 0})
    await any_backend.update_thread("u", "a", "s1", title="new")
    threads = await any_backend.query_threads("u", "a", limit=10)
    match = next((t for t in threads if t["session_id"] == "s1"), None)
    assert match is not None
    assert match["title"] == "new"


async def test_get_artifact_returns_none_when_missing(any_backend):
    """get_artifact returns None for non-existent items."""
    result = await any_backend.get_artifact("u", "a", "s1", "no-such-artifact")
    assert result is None
