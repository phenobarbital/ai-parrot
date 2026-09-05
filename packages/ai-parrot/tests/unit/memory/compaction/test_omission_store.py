"""Unit tests for FEAT-525 OmissionStore (InMemory / Redis fake / File backends)."""

import pytest

from parrot.memory.compaction.models import Omission
from parrot.memory.compaction.omission import (
    FileOmissionStore,
    InMemoryOmissionStore,
    RedisOmissionStore,
    content_id,
)


class _RecordingRedis:
    """Minimal async fake: hset/hget/hdel/delete/expire over dicts; records expire calls."""

    def __init__(self):
        self._hashes: dict[str, dict[str, str]] = {}
        self.expire_calls: list[tuple[str, int]] = []

    async def hset(self, key, field, value):
        self._hashes.setdefault(key, {})[field] = value

    async def hget(self, key, field):
        return self._hashes.get(key, {}).get(field)

    async def hdel(self, key, *fields):
        h = self._hashes.get(key, {})
        for f in fields:
            h.pop(f, None)

    async def delete(self, *keys):
        for k in keys:
            self._hashes.pop(k, None)

    async def expire(self, key, ttl):
        self.expire_calls.append((key, ttl))


@pytest.fixture(params=["memory", "file", "redis"])
def store(request, tmp_path):
    if request.param == "memory":
        return InMemoryOmissionStore()
    if request.param == "file":
        return FileOmissionStore(tmp_path)
    return RedisOmissionStore(_RecordingRedis(), key_prefix="conversation")


async def test_put_get_list_clear_isolated(store):
    cid = await store.put("bot:u:s", "payload", turn_id="t1")
    assert cid == content_id("payload") and await store.get("bot:u:s", cid) == "payload"
    assert await store.put("bot:u:s", "payload", turn_id="t1") == cid
    assert await store.list_by_turn("bot:u:s", "t1") == [cid]
    assert await store.get("bot:u:other", cid) is None
    await store.clear("bot:u:s")
    assert await store.get("bot:u:s", cid) is None and await store.list_by_turn("bot:u:s", "t1") == []


async def test_redis_ttl_none_default_no_expire():
    fake = _RecordingRedis()
    await RedisOmissionStore(fake).put("k", "c", turn_id="t")
    assert fake.expire_calls == []
    await RedisOmissionStore(fake, ttl=60).put("k", "c", turn_id="t")
    assert len(fake.expire_calls) == 2


async def test_put_many(store):
    await store.put_many(
        "k",
        [
            Omission(content_id("a"), "a", "t1", "q", "output"),
            Omission(content_id("b"), "b", "t1", "q", "output"),
        ],
    )
    assert await store.list_by_turn("k", "t1") == [content_id("a"), content_id("b")]
