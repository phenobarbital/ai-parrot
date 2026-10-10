"""Tests for AudioSessionStore and PartialSaveStore.remove_keys (FEAT-649 TASK-4219)."""
import pytest

from parrot_formdesigner.audio.models import Phase
from parrot_formdesigner.audio.session_store import (
    AudioSessionStore,
    AudioSnapshot,
    ResumeUnavailable,
    SnapshotConflict,
)
from parrot_formdesigner.core.partial import PartialFormData
from parrot_formdesigner.services.partial_saves import PartialSaveStore


class FakeRedis:
    """Dict-backed stub (fakeredis is not installed).

    ``eval`` emulates the production compare-and-set Lua script: SET ARGV[2] only
    when the current raw value equals ARGV[1] ("" = absent).
    """

    def __init__(self):
        self.kv = {}
        self.ttls = {}

    async def get(self, key):
        v = self.kv.get(key)
        return v.encode() if isinstance(v, str) else v

    async def setex(self, key, ttl, value):
        self.kv[key] = value
        self.ttls[key] = ttl

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.kv:
            return None
        self.kv[key] = value
        self.ttls[key] = ex
        return True

    async def delete(self, *keys):
        return sum(1 for k in keys if self.kv.pop(k, None) is not None)

    async def eval(self, script, numkeys, key, expected, value, ttl):
        if (self.kv.get(key) or "") == expected:
            self.kv[key] = value
            self.ttls[key] = ttl
            return 1
        return 0


@pytest.fixture
def stores():
    partial = PartialSaveStore(redis_url="redis://fake")
    partial._redis = FakeRedis()
    return partial, AudioSessionStore(partial, ttl_seconds=60)


def _snap(**kw):
    return AudioSnapshot(form_version="1.0", phase=Phase.ASKING, submission_id="s1", user_id="u1", **kw)


async def test_session_store_roundtrip_and_claim(stores):
    partial, store = stores
    assert await store.save("f", "sess", _snap()) == 1
    assert await store.save("f", "sess", _snap(), expected_revision=1) == 2
    loaded = await store.load("f", "sess")
    assert loaded.revision == 2 and loaded.saved_at and loaded.expires_at
    assert await store.load("f", "none") is None
    assert await store.claim_active("u1", "sess") is True
    assert await store.claim_active("u1", "other") is False
    assert await store.claim_active("u1", "sess") is True
    await store.delete("f", "sess")
    assert await store.load("f", "sess") is None
    assert await store.claim_active("u1", "other") is True


async def test_snapshot_cas_conflict(stores):
    _, store = stores
    await store.save("f", "sess", _snap())
    with pytest.raises(SnapshotConflict):
        await store.save("f", "sess", _snap(), expected_revision=0)
    assert (await store.load("f", "sess")).revision == 1


async def test_resume_unavailable_without_redis():
    store = AudioSessionStore(PartialSaveStore(), ttl_seconds=60)
    with pytest.raises(ResumeUnavailable):
        await store.load("f", "s")
    assert await store.save("f", "s", _snap()) == 0
    assert await store.claim_active("u1", "s") is True


async def test_partial_remove_keys(stores):
    partial, _ = stores
    assert await PartialSaveStore().remove_keys("f", "s", ["a"]) is None
    assert await partial.remove_keys("f", "s", ["a"]) is None
    await partial.save("f", "s", {"a": 1, "b": 2})
    updated = await partial.remove_keys("f", "s", ["a", "zzz"])
    assert isinstance(updated, PartialFormData)
    assert updated.data == {"b": 2}
    assert (await partial.get("f", "s")).data == {"b": 2}
