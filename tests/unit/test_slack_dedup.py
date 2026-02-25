"""Unit tests for Slack event deduplication module."""
import pytest
import asyncio
from unittest.mock import AsyncMock
from parrot.integrations.slack.dedup import (
    EventDeduplicator,
    RedisEventDeduplicator,
)


class TestEventDeduplicator:
    """Tests for in-memory EventDeduplicator."""

    def test_first_event_not_duplicate(self):
        """First occurrence of event_id is not duplicate."""
        dedup = EventDeduplicator(ttl_seconds=300)
        assert dedup.is_duplicate("evt_123") is False

    def test_second_event_is_duplicate(self):
        """Same event_id seen twice is duplicate."""
        dedup = EventDeduplicator(ttl_seconds=300)
        assert dedup.is_duplicate("evt_123") is False
        assert dedup.is_duplicate("evt_123") is True

    def test_different_events_not_duplicate(self):
        """Different event_ids are not duplicates."""
        dedup = EventDeduplicator(ttl_seconds=300)
        assert dedup.is_duplicate("evt_1") is False
        assert dedup.is_duplicate("evt_2") is False

    def test_empty_event_id_not_duplicate(self):
        """Empty event_id returns False."""
        dedup = EventDeduplicator(ttl_seconds=300)
        assert dedup.is_duplicate("") is False
        assert dedup.is_duplicate("") is False  # Still not duplicate

    def test_none_event_id_not_duplicate(self):
        """None event_id returns False."""
        dedup = EventDeduplicator(ttl_seconds=300)
        assert dedup.is_duplicate(None) is False

    def test_seen_count_property(self):
        """seen_count reflects number of tracked events."""
        dedup = EventDeduplicator(ttl_seconds=300)
        assert dedup.seen_count == 0
        dedup.is_duplicate("evt_1")
        assert dedup.seen_count == 1
        dedup.is_duplicate("evt_2")
        assert dedup.seen_count == 2
        dedup.is_duplicate("evt_1")  # Duplicate, shouldn't increase count
        assert dedup.seen_count == 2

    def test_clear_removes_all_events(self):
        """clear() removes all tracked events."""
        dedup = EventDeduplicator(ttl_seconds=300)
        dedup.is_duplicate("evt_1")
        dedup.is_duplicate("evt_2")
        assert dedup.seen_count == 2
        dedup.clear()
        assert dedup.seen_count == 0
        # Events should be new again
        assert dedup.is_duplicate("evt_1") is False

    @pytest.mark.asyncio
    async def test_cleanup_removes_expired(self):
        """Cleanup task removes expired entries."""
        dedup = EventDeduplicator(ttl_seconds=1, cleanup_interval=0.5)
        dedup.is_duplicate("evt_old")
        assert dedup.seen_count == 1

        await dedup.start()
        # Wait for expiry (1 sec) + cleanup interval (0.5 sec) + buffer
        await asyncio.sleep(1.8)

        # Should be able to see the same event as new after expiry
        assert dedup.is_duplicate("evt_old") is False
        await dedup.stop()

    @pytest.mark.asyncio
    async def test_start_stop_lifecycle(self):
        """Start and stop work without errors."""
        dedup = EventDeduplicator()
        await dedup.start()
        assert dedup._cleanup_task is not None
        await dedup.stop()
        assert dedup._cleanup_task is None

    @pytest.mark.asyncio
    async def test_double_start_is_safe(self):
        """Calling start twice doesn't create duplicate tasks."""
        dedup = EventDeduplicator()
        await dedup.start()
        assert dedup._cleanup_task is not None
        await dedup.start()  # Should be idempotent - no error
        assert dedup._cleanup_task is not None
        await dedup.stop()

    @pytest.mark.asyncio
    async def test_stop_without_start_is_safe(self):
        """Calling stop without start doesn't raise."""
        dedup = EventDeduplicator()
        await dedup.stop()  # Should not raise


class TestRedisEventDeduplicator:
    """Tests for Redis-backed RedisEventDeduplicator."""

    @pytest.mark.asyncio
    async def test_first_event_not_duplicate(self):
        """Redis SETNX returns True (was set) for new event."""
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=True)  # Key was set

        dedup = RedisEventDeduplicator(mock_redis)
        result = await dedup.is_duplicate("evt_123")

        assert result is False
        mock_redis.set.assert_called_once_with(
            "slack:dedup:evt_123", "1", nx=True, ex=300
        )

    @pytest.mark.asyncio
    async def test_duplicate_event(self):
        """Redis SETNX returns None/False for existing event."""
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=None)  # Key exists

        dedup = RedisEventDeduplicator(mock_redis)
        result = await dedup.is_duplicate("evt_123")

        assert result is True

    @pytest.mark.asyncio
    async def test_duplicate_event_returns_false(self):
        """Redis SETNX returns False (instead of None) for existing event."""
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=False)  # Key exists

        dedup = RedisEventDeduplicator(mock_redis)
        result = await dedup.is_duplicate("evt_123")

        assert result is True

    @pytest.mark.asyncio
    async def test_custom_prefix_and_ttl(self):
        """Custom prefix and TTL are applied."""
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=True)

        dedup = RedisEventDeduplicator(
            mock_redis, prefix="myapp:dedup:", ttl=600
        )
        await dedup.is_duplicate("evt_123")

        mock_redis.set.assert_called_once_with(
            "myapp:dedup:evt_123", "1", nx=True, ex=600
        )

    @pytest.mark.asyncio
    async def test_empty_event_id_not_duplicate(self):
        """Empty event_id returns False without Redis call."""
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=True)

        dedup = RedisEventDeduplicator(mock_redis)
        result = await dedup.is_duplicate("")

        assert result is False
        mock_redis.set.assert_not_called()

    @pytest.mark.asyncio
    async def test_none_event_id_not_duplicate(self):
        """None event_id returns False without Redis call."""
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=True)

        dedup = RedisEventDeduplicator(mock_redis)
        result = await dedup.is_duplicate(None)

        assert result is False
        mock_redis.set.assert_not_called()

    @pytest.mark.asyncio
    async def test_start_stop_are_noop(self):
        """Start and stop are no-ops for Redis backend."""
        mock_redis = AsyncMock()
        dedup = RedisEventDeduplicator(mock_redis)

        # Should not raise
        await dedup.start()
        await dedup.stop()
