# TASK-025: Slack Event Deduplication Module

**Feature**: Slack Wrapper Integration Enhancements
**Spec**: `sdd/specs/slack-wrapper-integration.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: claude-session

---

## Context

> This task implements event deduplication to prevent duplicate agent responses.
> Reference: Spec Section 2 (De-duplicación de Eventos) and Section 3 (Module 2).

Slack retries event delivery if it doesn't receive HTTP 200 within ~3 seconds. Without deduplication, the same message can be processed multiple times, causing duplicate responses. This module provides both in-memory and Redis-backed deduplication.

---

## Scope

- Create `parrot/integrations/slack/dedup.py` module
- Implement `EventDeduplicator` class (in-memory with TTL)
- Implement `RedisEventDeduplicator` class (for multi-instance)
- Add background cleanup task for expired events
- Support configurable TTL (default 5 minutes)

**NOT in scope**:
- Integrating into wrapper.py (TASK-024)
- Retry header handling (handled in TASK-024)
- Database-backed deduplication

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/integrations/slack/dedup.py` | CREATE | Deduplication module |
| `tests/unit/test_slack_dedup.py` | CREATE | Unit tests |
| `parrot/integrations/slack/__init__.py` | MODIFY | Export classes |

---

## Implementation Notes

### Pattern to Follow
```python
# parrot/integrations/slack/dedup.py
"""Event deduplication for Slack integration."""
import time
import asyncio
import logging
from typing import Dict, Optional, Protocol

logger = logging.getLogger("SlackDedup")


class EventDeduplicatorProtocol(Protocol):
    """Protocol for event deduplication backends."""
    def is_duplicate(self, event_id: str) -> bool: ...
    async def start(self) -> None: ...
    async def stop(self) -> None: ...


class EventDeduplicator:
    """
    In-memory event deduplication with TTL.

    For single-instance deployments. Use RedisEventDeduplicator
    for multi-instance production environments.
    """

    def __init__(self, ttl_seconds: int = 300, cleanup_interval: int = 60):
        self._seen: Dict[str, float] = {}
        self._ttl = ttl_seconds
        self._cleanup_interval = cleanup_interval
        self._cleanup_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Start the background cleanup task."""
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def stop(self) -> None:
        """Stop the cleanup task."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

    def is_duplicate(self, event_id: str) -> bool:
        """Check if event was already seen. Thread-safe for sync contexts."""
        if not event_id:
            return False
        now = time.time()
        if event_id in self._seen:
            logger.debug("Duplicate event detected: %s", event_id)
            return True
        self._seen[event_id] = now
        return False

    async def _cleanup_loop(self) -> None:
        """Periodically remove expired entries."""
        while True:
            await asyncio.sleep(self._cleanup_interval)
            cutoff = time.time() - self._ttl
            expired = [k for k, v in self._seen.items() if v < cutoff]
            for k in expired:
                del self._seen[k]
            if expired:
                logger.debug("Cleaned up %d expired events", len(expired))


class RedisEventDeduplicator:
    """
    Redis-backed deduplication for multi-instance deployments.

    Uses Redis SET NX with TTL for atomic deduplication.
    """

    def __init__(
        self,
        redis_pool,  # aioredis/redis-py async pool
        prefix: str = "slack:dedup:",
        ttl: int = 300
    ):
        self._redis = redis_pool
        self._prefix = prefix
        self._ttl = ttl

    async def is_duplicate(self, event_id: str) -> bool:
        """Check if event was seen using Redis SETNX."""
        if not event_id:
            return False
        key = f"{self._prefix}{event_id}"
        # SET NX returns True if key was set (new), None/False if exists
        was_set = await self._redis.set(key, "1", nx=True, ex=self._ttl)
        return not was_set

    async def start(self) -> None:
        """No-op for Redis (connection managed externally)."""
        pass

    async def stop(self) -> None:
        """No-op for Redis (connection managed externally)."""
        pass
```

### Key Constraints
- `is_duplicate()` must be idempotent and fast
- Cleanup must not block the event loop
- Redis version must use atomic SETNX
- Must handle empty/None event_ids gracefully

### References in Codebase
- Similar TTL cache pattern in `parrot/memory/redis_memory.py`
- asyncio task patterns in `parrot/bots/orchestration/`

---

## Acceptance Criteria

- [x] `EventDeduplicator.is_duplicate()` returns False for first event
- [x] Returns True for same event_id within TTL
- [x] Cleanup removes expired entries
- [x] `RedisEventDeduplicator` uses atomic SETNX
- [x] Both classes implement same protocol
- [x] All tests pass: `pytest tests/unit/test_slack_dedup.py -v`
- [x] No linting errors: `ruff check parrot/integrations/slack/dedup.py`
- [x] Import works: `from parrot.integrations.slack.dedup import EventDeduplicator`

---

## Test Specification

```python
# tests/unit/test_slack_dedup.py
import pytest
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock
from parrot.integrations.slack.dedup import EventDeduplicator, RedisEventDeduplicator


class TestEventDeduplicator:
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
        """Empty or None event_id returns False."""
        dedup = EventDeduplicator(ttl_seconds=300)
        assert dedup.is_duplicate("") is False
        assert dedup.is_duplicate(None) is False

    @pytest.mark.asyncio
    async def test_cleanup_removes_expired(self):
        """Cleanup task removes expired entries."""
        dedup = EventDeduplicator(ttl_seconds=1, cleanup_interval=0.5)
        dedup.is_duplicate("evt_old")

        await dedup.start()
        await asyncio.sleep(1.5)  # Wait for expiry + cleanup

        # Should be new again after expiry
        assert dedup.is_duplicate("evt_old") is False
        await dedup.stop()

    @pytest.mark.asyncio
    async def test_start_stop_lifecycle(self):
        """Start and stop work without errors."""
        dedup = EventDeduplicator()
        await dedup.start()
        await dedup.stop()


class TestRedisEventDeduplicator:
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
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-025-slack-event-deduplication.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-24
**Notes**: Implemented both in-memory and Redis-backed event deduplication:
- `EventDeduplicator` - In-memory with TTL and background cleanup task
- `RedisEventDeduplicator` - Redis-backed using atomic SETNX with TTL
- Added `EventDeduplicatorProtocol` for type-safe backend swapping
- Added utility methods: `seen_count` property, `clear()` method
- Exported classes from package `__init__.py`
- Created 18 comprehensive unit tests covering all functionality

**Deviations from spec**:
- Added `seen_count` property and `clear()` method to `EventDeduplicator` for testing/debugging
- Added `DeduplicatorType` type alias for convenience
- Added extra safety checks for double-start scenarios
