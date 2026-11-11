"""Test support for FEAT-878 Redis-backed tests."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

TEST_REDIS_URL = "redis://localhost:6379/15"
_BATCH_SIZE = 100


@asynccontextmanager
async def redis_test_settings(monkeypatch: Any) -> AsyncIterator[str]:
    """Point the user store at db 15 and delete only this test's unique prefix."""
    import pytest

    from .settings import close_user_store_redis, get_user_store_redis

    prefix = f"test:feat878:{uuid.uuid4().hex}"
    monkeypatch.setenv("PARROT_USER_STORE_REDIS_URL", TEST_REDIS_URL)
    monkeypatch.setenv("PARROT_USER_STORE_REDIS_PREFIX", prefix)
    client = get_user_store_redis()
    try:
        await client.ping()
    except Exception as exc:  # noqa: BLE001
        await close_user_store_redis()
        pytest.skip(f"local Redis unreachable: {type(exc).__name__}")
    try:
        yield prefix
    finally:
        keys = [key async for key in client.scan_iter(match=f"{prefix}:*")]
        for index in range(0, len(keys), _BATCH_SIZE):
            await client.delete(*keys[index : index + _BATCH_SIZE])
        await close_user_store_redis()
