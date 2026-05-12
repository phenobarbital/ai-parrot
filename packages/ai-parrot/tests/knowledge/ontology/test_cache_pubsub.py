"""Unit tests for OntologyCache pub/sub subscriber (TASK-1099).

Strategy: mock pubsub.listen() as an async generator that yields test
messages then raises asyncio.CancelledError to break the while-True loop
cleanly (CancelledError is a BaseException, so it escapes the inner
``except Exception`` handler and propagates to the test).
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.knowledge.ontology.cache import OntologyCache


# ── Helpers ──────────────────────────────────────────────────────────────────

def _pmessage(channel: str) -> dict:
    """Build a realistic redis pmessage dict."""
    return {
        "type": "pmessage",
        "pattern": b"ontology:invalidate:*",
        "channel": channel.encode(),
        "data": b"1",
    }


def _subscribe_ack(channel: str) -> dict:
    """Build a subscribe acknowledgment message (should be ignored)."""
    return {
        "type": "psubscribe",
        "pattern": b"ontology:invalidate:*",
        "channel": channel.encode(),
        "data": 1,
    }


async def _make_listen(*messages):
    """Async generator: yield messages then raise CancelledError to exit."""
    for m in messages:
        yield m
    raise asyncio.CancelledError("test done")


def _make_pubsub(*messages) -> MagicMock:
    """Build a mock pubsub object whose listen() yields the given messages."""
    pubsub = MagicMock()
    pubsub.psubscribe = AsyncMock()
    pubsub.listen = lambda: _make_listen(*messages)
    return pubsub


def _make_cache(pubsub: MagicMock) -> OntologyCache:
    """Build an OntologyCache backed by a mock Redis client."""
    redis = MagicMock()
    redis.pubsub = MagicMock(return_value=pubsub)
    # scan_iter used by invalidate_tenant — return empty async iterator
    async def _empty_scan(**_kwargs):
        return
        yield  # make it an async generator

    redis.scan_iter = _empty_scan
    redis.delete = AsyncMock()
    return OntologyCache(redis_client=redis)


def _make_manager() -> MagicMock:
    mgr = MagicMock()
    mgr.invalidate = MagicMock()  # sync
    return mgr


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestCachePubSubSubscriber:
    async def test_subscriber_calls_invalidate(self):
        """Subscriber calls invalidate on both manager and cache when message received."""
        msg = _pmessage("ontology:invalidate:tenant-a")
        pubsub = _make_pubsub(msg)
        cache = _make_cache(pubsub)
        manager = _make_manager()

        with pytest.raises(asyncio.CancelledError):
            await cache.subscribe_invalidation(manager)

        manager.invalidate.assert_called_once_with("tenant-a")

    async def test_subscriber_calls_invalidate_tenant_on_cache(self):
        """Subscriber also calls self.invalidate_tenant(tenant_id)."""
        msg = _pmessage("ontology:invalidate:tenant-b")
        pubsub = _make_pubsub(msg)
        cache = _make_cache(pubsub)
        manager = _make_manager()

        with patch.object(cache, "invalidate_tenant", new_callable=AsyncMock) as mock_inv:
            with pytest.raises(asyncio.CancelledError):
                await cache.subscribe_invalidation(manager)

        mock_inv.assert_called_once_with("tenant-b")

    async def test_subscriber_extracts_tenant_from_channel(self):
        """Subscriber correctly extracts tenant_id from complex channel names."""
        msg = _pmessage("ontology:invalidate:my-complex-tenant-id")
        pubsub = _make_pubsub(msg)
        cache = _make_cache(pubsub)
        manager = _make_manager()

        with pytest.raises(asyncio.CancelledError):
            await cache.subscribe_invalidation(manager)

        manager.invalidate.assert_called_once_with("my-complex-tenant-id")

    async def test_subscriber_handles_string_channel(self):
        """Subscriber works when channel is already a string (not bytes)."""
        msg = {
            "type": "pmessage",
            "pattern": b"ontology:invalidate:*",
            "channel": "ontology:invalidate:tenant-c",  # string, not bytes
            "data": b"1",
        }
        pubsub = _make_pubsub(msg)
        cache = _make_cache(pubsub)
        manager = _make_manager()

        with pytest.raises(asyncio.CancelledError):
            await cache.subscribe_invalidation(manager)

        manager.invalidate.assert_called_once_with("tenant-c")

    async def test_subscriber_ignores_non_pmessage(self):
        """Subscriber ignores subscribe/unsubscribe confirmation messages."""
        ack = _subscribe_ack("ontology:invalidate:*")
        # After the ack, raise CancelledError to exit
        pubsub = _make_pubsub(ack)
        cache = _make_cache(pubsub)
        manager = _make_manager()

        with pytest.raises(asyncio.CancelledError):
            await cache.subscribe_invalidation(manager)

        # No invalidation calls — ack message was ignored
        manager.invalidate.assert_not_called()

    async def test_subscriber_processes_multiple_messages(self):
        """Subscriber processes multiple messages in sequence."""
        msgs = [
            _pmessage("ontology:invalidate:tenant-x"),
            _pmessage("ontology:invalidate:tenant-y"),
        ]
        pubsub = _make_pubsub(*msgs)
        cache = _make_cache(pubsub)
        manager = _make_manager()

        with pytest.raises(asyncio.CancelledError):
            await cache.subscribe_invalidation(manager)

        assert manager.invalidate.call_count == 2
        calls = [c.args[0] for c in manager.invalidate.call_args_list]
        assert "tenant-x" in calls
        assert "tenant-y" in calls

    async def test_subscriber_psubscribes_to_wildcard(self):
        """Subscriber calls psubscribe with the correct wildcard pattern."""
        pubsub = _make_pubsub()
        cache = _make_cache(pubsub)
        manager = _make_manager()

        with pytest.raises(asyncio.CancelledError):
            await cache.subscribe_invalidation(manager)

        pubsub.psubscribe.assert_called_once_with("ontology:invalidate:*")

    async def test_reconnects_on_exception(self):
        """Subscriber logs error and reconnects when an exception occurs."""
        call_count = 0

        async def _failing_listen():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("Redis dropped")
            # Second call: yield nothing then cancel
            raise asyncio.CancelledError("test done")
            yield  # make async generator

        redis = MagicMock()
        pubsub = MagicMock()
        pubsub.psubscribe = AsyncMock()
        pubsub.listen = _failing_listen
        redis.pubsub = MagicMock(return_value=pubsub)
        redis.scan_iter = MagicMock()
        redis.delete = AsyncMock()

        cache = OntologyCache(redis_client=redis)
        manager = _make_manager()

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            with pytest.raises(asyncio.CancelledError):
                await cache.subscribe_invalidation(manager)

        # Sleep was called once (after the first exception)
        mock_sleep.assert_called_once_with(5.0)
        # listen() was called twice — once failing, once cancelling
        assert call_count == 2
