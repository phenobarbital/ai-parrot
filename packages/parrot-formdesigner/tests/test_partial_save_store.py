"""Unit tests for PartialSaveStore Redis service (TASK-1248).

All Redis interactions are mocked — no live Redis required.

Tests:
- save() stores a single field
- save() stores multiple fields in bulk
- save() merges new values over existing cached values (last-write-wins)
- get() returns PartialFormData when data is cached
- get() returns None when no data is cached
- delete() removes cached data and returns True/False
- session isolation: different session IDs use separate keys
- graceful degradation when Redis is unavailable (no redis_url)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot_formdesigner.core.partial import PartialFormData
from parrot_formdesigner.services.partial_saves import PartialSaveStore


@pytest.fixture
def store() -> PartialSaveStore:
    """PartialSaveStore configured with a fake Redis URL."""
    return PartialSaveStore(ttl_seconds=60, redis_url="redis://localhost:6379")


def _make_partial(
    form_id: str = "test-form",
    session_id: str = "sess-1",
    data: dict | None = None,
) -> PartialFormData:
    """Build a minimal PartialFormData for use in mock return values."""
    now = datetime.now(tz=timezone.utc)
    return PartialFormData(
        form_id=form_id,
        session_id=session_id,
        data=data or {},
        field_errors={},
        saved_at=now,
        expires_at=now + timedelta(seconds=60),
    )


class TestRedisKeyFormat:
    """Verify Redis key construction."""

    def test_key_format(self, store: PartialSaveStore):
        """Key follows parrot:partial:{form_id}:{session_id} pattern."""
        key = store._redis_key("my-form", "abc-123")
        assert key == "parrot:partial:my-form:abc-123"

    def test_key_prefix(self, store: PartialSaveStore):
        """REDIS_KEY_PREFIX is correct."""
        assert store.REDIS_KEY_PREFIX == "parrot:partial:"


class TestPartialSaveStoreSave:
    """Tests for PartialSaveStore.save()."""

    async def test_save_single_field(self, store: PartialSaveStore):
        """save() with one field stores and returns PartialFormData."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock()

        with patch.object(store, "_get_redis", return_value=mock_redis):
            result = await store.save("form1", "sess1", {"name": "Alice"})

        assert isinstance(result, PartialFormData)
        assert result.form_id == "form1"
        assert result.session_id == "sess1"
        assert result.data == {"name": "Alice"}
        mock_redis.setex.assert_called_once()

    async def test_save_bulk(self, store: PartialSaveStore):
        """save() with multiple fields stores all of them."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock()

        with patch.object(store, "_get_redis", return_value=mock_redis):
            result = await store.save(
                "form1", "sess1", {"name": "Alice", "age": 30, "email": "a@b.com"}
            )

        assert result.data == {"name": "Alice", "age": 30, "email": "a@b.com"}

    async def test_save_merge_overwrite(self, store: PartialSaveStore):
        """save() merges new answers over cached answers (last-write-wins)."""
        existing = _make_partial(data={"name": "Alice", "age": 25})

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=existing.model_dump_json())
        mock_redis.setex = AsyncMock()

        with patch.object(store, "_get_redis", return_value=mock_redis):
            result = await store.save("form1", "sess1", {"age": 30, "email": "a@b.com"})

        # "age" should be overwritten; "name" preserved; "email" added
        assert result.data["name"] == "Alice"
        assert result.data["age"] == 30
        assert result.data["email"] == "a@b.com"

    async def test_save_refreshes_ttl(self, store: PartialSaveStore):
        """save() calls setex with the configured TTL in seconds."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock()

        with patch.object(store, "_get_redis", return_value=mock_redis):
            await store.save("form1", "sess1", {"x": 1})

        # setex(key, ttl_secs, json_value)
        call_args = mock_redis.setex.call_args
        assert call_args is not None
        key_arg, ttl_arg, _ = call_args[0]
        assert ttl_arg == 60  # matches ttl_seconds=60 in fixture

    async def test_save_sets_expires_at(self, store: PartialSaveStore):
        """expires_at is saved_at + ttl."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock()

        with patch.object(store, "_get_redis", return_value=mock_redis):
            result = await store.save("form1", "sess1", {})

        delta = result.expires_at - result.saved_at
        assert abs(delta.total_seconds() - 60) < 2


class TestPartialSaveStoreGet:
    """Tests for PartialSaveStore.get()."""

    async def test_get_existing(self, store: PartialSaveStore):
        """get() returns PartialFormData when data is cached."""
        cached = _make_partial(data={"name": "Bob"})
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=cached.model_dump_json())

        with patch.object(store, "_get_redis", return_value=mock_redis):
            result = await store.get("test-form", "sess-1")

        assert result is not None
        assert result.data == {"name": "Bob"}

    async def test_get_nonexistent(self, store: PartialSaveStore):
        """get() returns None when no data is cached."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        with patch.object(store, "_get_redis", return_value=mock_redis):
            result = await store.get("no-form", "no-sess")

        assert result is None

    async def test_get_uses_correct_key(self, store: PartialSaveStore):
        """get() queries Redis using the correct key."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        with patch.object(store, "_get_redis", return_value=mock_redis):
            await store.get("form-x", "session-y")

        mock_redis.get.assert_called_once_with("parrot:partial:form-x:session-y")


class TestPartialSaveStoreDelete:
    """Tests for PartialSaveStore.delete()."""

    async def test_delete_existing_returns_true(self, store: PartialSaveStore):
        """delete() returns True when the key existed."""
        mock_redis = AsyncMock()
        mock_redis.delete = AsyncMock(return_value=1)

        with patch.object(store, "_get_redis", return_value=mock_redis):
            result = await store.delete("form1", "sess1")

        assert result is True

    async def test_delete_nonexistent_returns_false(self, store: PartialSaveStore):
        """delete() returns False when the key did not exist."""
        mock_redis = AsyncMock()
        mock_redis.delete = AsyncMock(return_value=0)

        with patch.object(store, "_get_redis", return_value=mock_redis):
            result = await store.delete("form1", "sess1")

        assert result is False

    async def test_delete_uses_correct_key(self, store: PartialSaveStore):
        """delete() deletes using the correct Redis key."""
        mock_redis = AsyncMock()
        mock_redis.delete = AsyncMock(return_value=1)

        with patch.object(store, "_get_redis", return_value=mock_redis):
            await store.delete("form-a", "sess-b")

        mock_redis.delete.assert_called_once_with("parrot:partial:form-a:sess-b")


class TestSessionIsolation:
    """Tests for per-session key isolation."""

    async def test_different_sessions_use_different_keys(self, store: PartialSaveStore):
        """Two sessions produce independent Redis keys."""
        key_a = store._redis_key("my-form", "session-A")
        key_b = store._redis_key("my-form", "session-B")
        assert key_a != key_b
        assert "session-A" in key_a
        assert "session-B" in key_b

    async def test_save_isolates_sessions(self, store: PartialSaveStore):
        """Saving for one session does not affect another session's data."""
        redis_store: dict[str, str] = {}

        async def fake_get(key: str) -> str | None:
            return redis_store.get(key)

        async def fake_setex(key: str, ttl: int, value: str) -> None:
            redis_store[key] = value

        mock_redis = AsyncMock()
        mock_redis.get = fake_get
        mock_redis.setex = fake_setex

        with patch.object(store, "_get_redis", return_value=mock_redis):
            await store.save("form1", "sessA", {"x": 1})
            await store.save("form1", "sessB", {"x": 99})

        # sessA key should still have x=1
        key_a = store._redis_key("form1", "sessA")
        data_a = PartialFormData.model_validate_json(redis_store[key_a])
        assert data_a.data["x"] == 1

        # sessB key should have x=99
        key_b = store._redis_key("form1", "sessB")
        data_b = PartialFormData.model_validate_json(redis_store[key_b])
        assert data_b.data["x"] == 99


class TestGracefulDegradation:
    """Tests for graceful failure when Redis is unavailable."""

    async def test_save_no_redis_returns_partial(self):
        """save() without redis_url returns PartialFormData without persisting."""
        store = PartialSaveStore(ttl_seconds=60, redis_url=None)
        result = await store.save("form1", "sess1", {"name": "test"})
        assert isinstance(result, PartialFormData)
        assert result.data == {"name": "test"}

    async def test_get_no_redis_returns_none(self):
        """get() without redis_url returns None."""
        store = PartialSaveStore(ttl_seconds=60, redis_url=None)
        result = await store.get("form1", "sess1")
        assert result is None

    async def test_delete_no_redis_returns_false(self):
        """delete() without redis_url returns False."""
        store = PartialSaveStore(ttl_seconds=60, redis_url=None)
        result = await store.delete("form1", "sess1")
        assert result is False

    async def test_save_redis_exception_still_returns(self, store: PartialSaveStore):
        """save() swallows Redis errors and returns the partial."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock(side_effect=Exception("Redis down"))

        with patch.object(store, "_get_redis", return_value=mock_redis):
            result = await store.save("form1", "sess1", {"name": "Alice"})

        assert result.data == {"name": "Alice"}

    async def test_get_redis_exception_returns_none(self, store: PartialSaveStore):
        """get() swallows Redis errors and returns None."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(side_effect=Exception("Connection refused"))

        with patch.object(store, "_get_redis", return_value=mock_redis):
            result = await store.get("form1", "sess1")

        assert result is None


class TestClose:
    """Tests for PartialSaveStore.close()."""

    async def test_close_calls_redis_close(self, store: PartialSaveStore):
        """close() closes the Redis connection."""
        mock_redis = AsyncMock()
        store._redis = mock_redis

        await store.close()

        mock_redis.close.assert_called_once()
        assert store._redis is None

    async def test_close_without_redis_is_no_op(self):
        """close() is safe when Redis was never initialized."""
        store = PartialSaveStore(ttl_seconds=60, redis_url=None)
        await store.close()  # should not raise
