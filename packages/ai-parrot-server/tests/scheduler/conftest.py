"""Shared fixtures for scheduler tests: real Redis on db 15 (FEAT-644)."""

from __future__ import annotations

import uuid

import pytest

redis_asyncio = pytest.importorskip("redis.asyncio")
redis_sync = pytest.importorskip("redis")

from parrot.conf import CACHE_HOST, CACHE_PORT  # noqa: E402
from parrot.scheduler.sanitize import sanitize_redis_settings  # noqa: E402

TEST_REDIS_DB = 15


@pytest.fixture
def scheduler_namespace() -> str:
    """Unique ``registered_name`` so keys never collide across tests or sessions."""
    return f"t-{uuid.uuid4().hex[:12]}"


@pytest.fixture
async def scheduler_redis(scheduler_namespace: str):
    """Async client on db 15; skip when unreachable and remove only test keys."""
    client = redis_asyncio.Redis(
        **sanitize_redis_settings(CACHE_HOST, CACHE_PORT, db=TEST_REDIS_DB),
        decode_responses=True,
    )
    try:
        await client.ping()
    except Exception:  # noqa: BLE001
        await client.aclose()
        pytest.skip("Redis not reachable for scheduler tests")
    try:
        yield client
    finally:
        async for key in client.scan_iter(match=f"parrot:scheduler:{scheduler_namespace}:*"):
            await client.delete(key)
        await client.aclose()


@pytest.fixture
def scheduler_redis_sync(scheduler_namespace: str):
    """Sync client for RedisJobStore tests; use the same isolated cleanup policy."""
    client = redis_sync.Redis(
        **sanitize_redis_settings(CACHE_HOST, CACHE_PORT, db=TEST_REDIS_DB),
        decode_responses=True,
    )
    try:
        client.ping()
    except Exception:  # noqa: BLE001
        client.close()
        pytest.skip("Redis not reachable for scheduler tests")
    try:
        yield client
    finally:
        for key in client.scan_iter(match=f"parrot:scheduler:{scheduler_namespace}:*"):
            client.delete(key)
        client.close()
