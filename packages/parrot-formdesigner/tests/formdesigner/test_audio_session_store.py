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
    return partial, AudioSessionStore(partial, resume_ttl_seconds=60, active_ttl_seconds=30)


def _snap(**kw):
    return AudioSnapshot(form_version="1.0", phase=Phase.ASKING, submission_id="s1", user_id="u1", **kw)


async def test_session_store_roundtrip_and_claim(stores):
    partial, store = stores
    assert await store.save("f", "sess", _snap()) == 1
    assert await store.save("f", "sess", _snap(), expected_revision=1) == 2
    loaded = await store.load("f", "sess")
    assert loaded.revision == 2 and loaded.saved_at and loaded.expires_at
    assert await store.load("f", "none") is None
    assert await store.claim_active("u1", "sess", form_uid="f", tenant="t1") is True
    assert await store.claim_active("u1", "other", form_uid="f", tenant="t1") is False
    assert await store.claim_active("u1", "sess", form_uid="f", tenant="t1") is True
    await store.delete("f", "sess")
    assert await store.load("f", "sess") is None
    assert await store.claim_active("u1", "other", form_uid="f", tenant="t1") is True


async def test_snapshot_cas_conflict(stores):
    _, store = stores
    await store.save("f", "sess", _snap())
    with pytest.raises(SnapshotConflict):
        await store.save("f", "sess", _snap(), expected_revision=0)
    assert (await store.load("f", "sess")).revision == 1


async def test_resume_unavailable_without_redis():
    store = AudioSessionStore(PartialSaveStore())
    with pytest.raises(ResumeUnavailable):
        await store.load("f", "s")
    assert await store.save("f", "s", _snap()) == 0
    assert await store.claim_active("u1", "s", form_uid="f", tenant="t1") is True


async def test_partial_remove_keys(stores):
    partial, _ = stores
    assert await PartialSaveStore().remove_keys("f", "s", ["a"]) is None
    assert await partial.remove_keys("f", "s", ["a"]) is None
    await partial.save("f", "s", {"a": 1, "b": 2})
    updated = await partial.remove_keys("f", "s", ["a", "zzz"])
    assert isinstance(updated, PartialFormData)
    assert updated.data == {"b": 2}
    assert (await partial.get("f", "s")).data == {"b": 2}


MARKER = "parrot:audio:active:u1"


async def test_claim_active_stores_holder_json(stores):
    from parrot_formdesigner.audio.session_store import ActiveHolder

    partial, store = stores
    assert await store.claim_active("u1", "s1", form_uid="f1", tenant="t1") is True
    assert await store.active_holder("u1") == ActiveHolder(session_id="s1", form_uid="f1", tenant="t1")
    assert partial._redis.ttls[MARKER] == 30


async def test_active_holder_legacy_bare_value(stores):
    from parrot_formdesigner.audio.session_store import ActiveHolder

    partial, store = stores
    partial._redis.kv[MARKER] = "s1"
    assert await store.active_holder("u1") == ActiveHolder(session_id="s1", form_uid=None, tenant=None)
    assert await store.claim_active("u1", "s1", form_uid="f", tenant="t1") is True
    assert partial._redis.kv[MARKER].startswith("{")
    partial._redis.kv[MARKER] = "s1"
    await store.release_active("u1", "s1")
    assert MARKER not in partial._redis.kv


async def test_active_holder_absent_and_no_redis(stores):
    _, store = stores
    assert await store.active_holder("u1") is None
    assert await AudioSessionStore(PartialSaveStore()).active_holder("u1") is None


async def test_save_uses_snapshot_resume_ttl(stores):
    from parrot_formdesigner.core.voice import VoiceFormConfig

    partial, store = stores
    await store.save("f", "sess", _snap(config=VoiceFormConfig(resume_ttl_seconds=7200)))
    assert partial._redis.ttls["parrot:audio:f:sess"] == 7200
    loaded = await store.load("f", "sess")
    assert (loaded.expires_at - loaded.saved_at).total_seconds() == 7200
    await store.save("f", "sess2", _snap())
    assert partial._redis.ttls["parrot:audio:f:sess2"] == 60


async def test_save_refreshes_marker_of_same_session_only(stores):
    partial, store = stores
    await store.claim_active("u1", "sess", form_uid="f", tenant="t1")
    partial._redis.ttls[MARKER] = 1
    await store.save("f", "sess", _snap())
    assert partial._redis.ttls[MARKER] == 30
    partial._redis.kv[MARKER] = '{"session_id": "other"}'
    partial._redis.ttls[MARKER] = 1
    await store.save("f", "sess", _snap())
    assert partial._redis.ttls[MARKER] == 1
    assert partial._redis.kv[MARKER] == '{"session_id": "other"}'


async def test_refresh_marker_does_not_clobber_concurrent_new_holder(stores):
    """The marker is replaced by another session between the refresh's GET and its write."""
    partial, store = stores
    await store.claim_active("u1", "sess", form_uid="f", tenant="t1")
    new_holder = '{"session_id": "B", "form_uid": "f2", "tenant": "t1"}'

    class RacingRedis(FakeRedis):
        async def get(self, key):
            value = await super().get(key)
            if key == MARKER and self.kv[key] != new_holder:
                self.kv[key] = new_holder
                self.ttls[key] = 99
            return value

    racing = RacingRedis()
    racing.kv, racing.ttls = partial._redis.kv, partial._redis.ttls
    partial._redis = racing
    await store._refresh_active(racing, "u1", "sess")
    assert racing.kv[MARKER] == new_holder
    assert racing.ttls[MARKER] == 99
