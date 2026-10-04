"""FEAT-621 M7 — cache bookkeeping with a fake clock (AC14). Pure: no database, no event loop."""
from unittest.mock import Mock
from uuid import uuid4

from parrot.manager.studio_cache import StudioCacheEntry, StudioRuntimeCache

KEY = "studio:acme:a1"
GRACE, SESSION_TTL, IDLE_TTL = 300.0, 3600.0, 3600.0


def _entry(version=1, session_id=None, now=0.0, agent_id=None, **kw):
    return StudioCacheEntry(
        qualified=KEY, session_id=session_id, agent_id=agent_id or uuid4(), version=version, bot=Mock(),
        asset_dir=None, last_used=now, **kw,
    )


def _due(cache, now):
    return cache.reclaimable(now=now, grace=GRACE, session_ttl=SESSION_TTL, idle_ttl=IDLE_TTL)


def test_install_retires_previous():
    cache = StudioRuntimeCache()
    v1, v2 = _entry(1, now=10), _entry(2, now=50)
    assert cache.install(v1) is None and cache.current(KEY) is v1
    assert cache.install(v2) is v1
    assert cache.current(KEY) is v2 and v1.retired_at == 50 and not v1.cleaned
    assert cache.install(v2) is None and v2.retired_at is None          # re-installing the same entry is a no-op
    assert cache.current("studio:acme:other") is None
    s1, s2 = _entry(1, "t1", now=5), _entry(2, "t1", now=7)
    cache.install(s1)
    assert cache.session(KEY, "t1") is s1 and cache.session(KEY, "t2") is None and cache.current(KEY) is v2
    assert cache.install(s2) is s1 and cache.session(KEY, "t1") is s2 and s1.retired_at == 7


def test_session_expiry_requires_no_lease():
    cache = StudioRuntimeCache()
    s = _entry(session_id="t1", now=0.0, leases=1)
    cache.install(s)
    assert _due(cache, SESSION_TTL - 1) == []
    assert _due(cache, SESSION_TTL + 1) == []                           # past the TTL but leased
    s.leases = 0
    assert _due(cache, SESSION_TTL + 1) == [s]
    s.last_used = SESSION_TTL                                           # touched: the TTL restarts
    assert _due(cache, SESSION_TTL + 1) == []
    s.expires_at = SESSION_TTL + 5                                      # a hard expiry applies as well
    assert _due(cache, SESSION_TTL + 6) == [s]


def test_idle_base_entry_is_retired_then_reclaimed_after_grace():
    cache = StudioRuntimeCache()
    base = _entry(now=0.0)
    cache.install(base)
    assert _due(cache, IDLE_TTL - 1) == [] and cache.current(KEY) is base
    assert _due(cache, IDLE_TTL) == []                                  # retired now, grace not yet over
    assert cache.current(KEY) is None and base.retired_at == IDLE_TTL
    assert _due(cache, IDLE_TTL + GRACE) == [base]
    leased = _entry(now=0.0, leases=1)
    cache2 = StudioRuntimeCache()
    cache2.install(leased)
    assert _due(cache2, IDLE_TTL * 5) == [] and cache2.current(KEY) is leased   # a leased entry is never idle


def test_retired_needs_grace_and_no_lease():
    cache = StudioRuntimeCache()
    old = _entry(1, now=0.0, leases=1)
    cache.install(old)
    cache.install(_entry(2, now=100.0))
    assert _due(cache, 100.0 + GRACE - 1) == []                         # grace not over
    assert _due(cache, 100.0 + GRACE + 1) == []                         # grace over, lease still held
    old.leases = 0
    assert _due(cache, 100.0 + GRACE) == [old]
    cache.retire(old, now=9999.0)                                       # idempotent: keeps the first retired_at
    assert old.retired_at == 100.0 and sum(e is old for e in cache.all_entries()) == 1


def test_three_versions_each_reclaimable_once():
    cache = StudioRuntimeCache()
    agent = uuid4()
    versions = [_entry(v, now=float(v), agent_id=agent) for v in (1, 2, 3)]
    for entry in versions:
        cache.install(entry)
    assert cache.current(KEY) is versions[2]
    due = _due(cache, 10 + GRACE)
    assert due == versions[:2]
    for entry in due:
        cache.mark_cleaned(entry)
    assert _due(cache, 10 + GRACE) == [] and cache.all_entries() == [versions[2]]
    cache.mark_cleaned(versions[2])
    assert cache.current(KEY) is None and cache.all_entries() == []
    cache.retire(versions[2], now=1e9)                                  # a cleaned entry never comes back
    assert cache.all_entries() == []


def test_dir_refcount_across_base_and_session():
    cache = StudioRuntimeCache()
    agent = uuid4()
    assert cache.acquire_dir(agent, 1) == 1 and cache.acquire_dir(agent, 1) == 2     # base + session share a dir
    assert cache.acquire_dir(agent, 2) == 1
    assert cache.release_dir(agent, 1) is False
    assert cache.release_dir(agent, 1) is True
    assert cache.release_dir(agent, 1) is False                          # unknown / already gone
    assert cache.release_dir(agent, 2) is True


def test_all_entries_covers_base_session_and_retired():
    cache = StudioRuntimeCache()
    base, sess, old = _entry(1, now=0.0), _entry(1, "t1"), _entry(0, now=0.0)
    cache.install(old)
    cache.install(base)
    cache.install(sess)
    assert {id(e) for e in cache.all_entries()} == {id(base), id(sess), id(old)}


def test_entry_flagged_cleaned_elsewhere_is_never_returned():
    cache = StudioRuntimeCache()
    old = _entry(1, now=0.0)
    cache.install(old)
    cache.install(_entry(2, now=1.0))
    old.cleaned = True                                                  # cleaned by another path (identity guard)
    assert _due(cache, 1.0 + GRACE) == [] and old not in cache.all_entries()
