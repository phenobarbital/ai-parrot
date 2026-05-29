"""Tests for SuspendedExecution + SuspendedExecutionStore (FEAT-204 / TASK-1380)."""
from __future__ import annotations

import pytest
import pytest_asyncio
import fakeredis.aioredis
from datetime import datetime, timezone

from parrot.human.suspended_store import SuspendedExecution, SuspendedExecutionStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def fake_redis():
    """Provide a fakeredis async client with decode_responses=True."""
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield client
    await client.aclose()


@pytest_asyncio.fixture
async def store(fake_redis):
    """Provide a SuspendedExecutionStore backed by fakeredis."""
    return SuspendedExecutionStore(fake_redis)


def _make_record(**overrides) -> SuspendedExecution:
    """Build a minimal SuspendedExecution for testing."""
    defaults = dict(
        interaction_id="i1",
        session_id="s1",
        user_id="u1",
        agent_name="test-agent",
        tool_call_id="tc-1",
        messages=[{"role": "user", "content": "hi"}],
        created_at=datetime(2026, 5, 29, 12, 0, 0, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return SuspendedExecution(**defaults)


# ---------------------------------------------------------------------------
# SuspendedExecution model tests
# ---------------------------------------------------------------------------


def test_suspended_execution_has_required_fields():
    """SuspendedExecution has exactly the 7 specified fields."""
    fields = set(SuspendedExecution.model_fields.keys())
    assert fields == {
        "interaction_id",
        "session_id",
        "user_id",
        "agent_name",
        "tool_call_id",
        "messages",
        "created_at",
    }


def test_suspended_execution_created_at_defaults_to_utc_now():
    """created_at defaults to UTC now when not provided."""
    rec = SuspendedExecution(
        interaction_id="x",
        session_id="s",
        user_id="u",
        agent_name="a",
        tool_call_id="t",
        messages=[],
    )
    assert rec.created_at.tzinfo is not None


# ---------------------------------------------------------------------------
# Store key helper
# ---------------------------------------------------------------------------


def test_key_format():
    """Key format is 'hitl:suspended:{interaction_id}'."""
    assert SuspendedExecutionStore._key("abc-123") == "hitl:suspended:abc-123"


# ---------------------------------------------------------------------------
# Save / load round-trip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_roundtrip(store, fake_redis):
    """save → load returns an equal record; TTL is applied via setex."""
    rec = _make_record()
    await store.save(rec, ttl=120)

    loaded = await store.load("i1")
    assert loaded == rec


@pytest.mark.asyncio
async def test_ttl_is_set(store, fake_redis):
    """TTL is applied to the key after save."""
    rec = _make_record()
    await store.save(rec, ttl=300)

    ttl_remaining = await fake_redis.ttl("hitl:suspended:i1")
    assert 0 < ttl_remaining <= 300


@pytest.mark.asyncio
async def test_load_missing_returns_none(store):
    """load of a missing id returns None."""
    result = await store.load("nope")
    assert result is None


@pytest.mark.asyncio
async def test_roundtrip_complex_messages(store):
    """Messages with nested content blocks round-trip correctly."""
    messages = [
        {
            "role": "user",
            "content": [{"type": "text", "text": "approve?"}],
        },
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "tc-1",
                    "name": "ask_human",
                    "input": {"question": "approve?"},
                }
            ],
        },
    ]
    rec = _make_record(messages=messages)
    await store.save(rec, ttl=120)
    loaded = await store.load("i1")
    assert loaded.messages == messages


# ---------------------------------------------------------------------------
# Delete only the suspended key
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_only_suspended_key(store, fake_redis):
    """delete removes hitl:suspended:{id} but NOT hitl:interaction:{id}."""
    # Pre-populate the interaction key (simulates manager persisting it)
    await fake_redis.set("hitl:interaction:i1", '{"interaction_id": "i1"}')

    rec = _make_record()
    await store.save(rec, ttl=120)

    # Confirm both keys exist
    assert await fake_redis.get("hitl:suspended:i1") is not None
    assert await fake_redis.get("hitl:interaction:i1") is not None

    await store.delete("i1")

    # Suspended key gone; interaction key untouched
    assert await store.load("i1") is None
    assert await fake_redis.get("hitl:interaction:i1") is not None


@pytest.mark.asyncio
async def test_delete_nonexistent_is_safe(store):
    """Deleting a key that does not exist does not raise."""
    await store.delete("does-not-exist")  # should complete silently
