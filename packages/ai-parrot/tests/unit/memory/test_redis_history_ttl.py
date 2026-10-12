"""``RedisConversation(history_ttl=...)`` expires an idle conversation (real Redis; skipped when none is configured)."""

from __future__ import annotations

import os
import uuid

import pytest
from redis.asyncio import Redis

from parrot.memory import ConversationTurn
from parrot.memory.redis import RedisConversation

REDIS_URL = os.environ.get("TEST_REDIS_URL", "")  # a dedicated db: only this test's prefix is removed


@pytest.fixture
async def prefix():
    if not REDIS_URL:
        pytest.skip("TEST_REDIS_URL not set")
    name = f"ttltest{uuid.uuid4().hex[:8]}"
    yield name
    client = Redis.from_url(REDIS_URL, decode_responses=True)
    keys = [k async for k in client.scan_iter(match=f"{name}*")]
    if keys:
        await client.delete(*keys)
    await client.aclose()


async def _ttl(memory: RedisConversation, prefix: str) -> list[int]:
    return [await memory.redis.ttl(k) async for k in memory.redis.scan_iter(match=f"{prefix}:*")]


@pytest.mark.parametrize("hash_storage", [True, False])
async def test_turns_refresh_the_ttl(prefix, hash_storage):
    memory = RedisConversation(redis_url=REDIS_URL, key_prefix=prefix, use_hash_storage=hash_storage, history_ttl=120)
    try:
        await memory.create_history("u", "s", chatbot_id="bot")
        await memory.add_turn("u", "s", ConversationTurn(turn_id="t1", user_id="u", user_message="hi", assistant_response="yo"), chatbot_id="bot")
        ttls = await _ttl(memory, prefix)
        assert ttls and all(0 < t <= 120 for t in ttls)
        assert len((await memory.get_history("u", "s", chatbot_id="bot")).turns) == 1
    finally:
        await memory.close()


async def test_no_ttl_by_default(prefix):
    memory = RedisConversation(redis_url=REDIS_URL, key_prefix=prefix)
    try:
        await memory.add_turn("u", "s", ConversationTurn(turn_id="t1", user_id="u", user_message="hi", assistant_response="yo"), chatbot_id="bot")
        assert await _ttl(memory, prefix) == [-1]
    finally:
        await memory.close()
