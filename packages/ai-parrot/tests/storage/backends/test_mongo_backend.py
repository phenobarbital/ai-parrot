"""Unit tests for parrot.storage.backends.mongodb.ConversationMongoBackend.

TASK-828: MongoDB Backend Implementation — FEAT-116.

These tests skip when MONGO_TEST_DSN is not set.
"""
import os
import pytest

from parrot.storage.backends.mongodb import ConversationMongoBackend

DSN = os.environ.get("MONGO_TEST_DSN")
pytestmark = pytest.mark.skipif(
    not DSN,
    reason="MONGO_TEST_DSN not set — skipping MongoDB backend tests",
)


@pytest.fixture
async def backend(request):
    b = ConversationMongoBackend(dsn=DSN, database=f"parrot_test_{request.node.name[:20]}")
    await b.initialize()
    yield b
    try:
        await b.delete_thread_cascade("u", "a", "s1")
        await b.delete_session_artifacts("u", "a", "s1")
    except Exception:
        pass
    await b.close()


async def test_initialize_creates_indexes(backend):
    # Upsert same key twice → only one document
    await backend.put_turn("u", "a", "s1", "001", {"text": "x"})
    await backend.put_turn("u", "a", "s1", "001", {"text": "y"})
    turns = await backend.query_turns("u", "a", "s1", limit=10)
    assert len(turns) == 1
    assert turns[0]["text"] == "y"


async def test_nested_roundtrip(backend):
    await backend.put_artifact("u", "a", "s1", "art", {
        "artifact_type": "chart",
        "title": "c",
        "definition": {"nested": {"a": 1, "b": [1, 2, 3]}},
    })
    got = await backend.get_artifact("u", "a", "s1", "art")
    assert got["definition"]["nested"] == {"a": 1, "b": [1, 2, 3]}
    assert "_id" not in got


async def test_query_turns_newest_first(backend):
    await backend.put_thread("u", "a", "s1", {"title": "t"})
    for i in range(3):
        await backend.put_turn("u", "a", "s1", f"{i:03d}", {"text": f"t-{i}"})
    turns = await backend.query_turns("u", "a", "s1", limit=10, newest_first=True)
    assert [t["turn_id"] for t in turns] == ["002", "001", "000"]


async def test_build_overflow_prefix(backend):
    assert backend.build_overflow_prefix("u", "a", "s", "aid") == \
        "artifacts/USER#u#AGENT#a/THREAD#s/aid"
