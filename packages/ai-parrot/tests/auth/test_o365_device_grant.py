"""FEAT-777 M3: O365 device-code grants on the principal store (no fakeredis)."""
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.auth.o365_oauth import O365OAuthManager, O365TokenSet
from parrot.auth.oauth2_base import CredentialPersistenceError, InvalidGrantError, RefreshTransientError
from parrot.auth.principal import Principal


class _Lock:
    async def acquire(self):
        return True

    async def release(self):
        return None


class _MemRedis:
    """Async Redis double: get/set/delete + a no-op lock."""

    def __init__(self):
        self.data = {}

    async def get(self, key):
        return self.data.get(key)

    async def set(self, key, value, ex=None):
        self.data[key] = value

    async def delete(self, *keys):
        for key in keys:
            self.data.pop(key, None)

    def lock(self, *args, **kwargs):
        return _Lock()


class _MemStore:
    """CredentialStore double recording saves; ``fail=True`` raises on save."""

    def __init__(self, fail=False):
        self.fail = fail
        self.saved = {}
        self.save_calls = 0

    async def load(self, user_id, provider):
        return self.saved.get((user_id, provider))

    async def save(self, user_id, provider, payload, *, minted=False, principal=None, state_payload=None):
        if self.fail:
            raise RuntimeError("boom")
        self.save_calls += 1
        self.saved[(user_id, provider)] = payload

    async def delete(self, user_id, provider):
        self.saved.pop((user_id, provider), None)


def _make(fail=False):
    redis, store, events = _MemRedis(), _MemStore(fail=fail), MagicMock()
    events.publish = AsyncMock()
    mgr = O365OAuthManager(
        "cid", "secret", "http://x/cb", redis_client=redis, credential_store=store, event_publisher=events,
    )
    return mgr, redis, store, events


def _patch(monkeypatch, mgr):
    mgr._discover_identity = AsyncMock(
        return_value={"id": "oid", "displayName": "Ann", "mail": "a@x.io", "userPrincipalName": "a@x.io"}
    )
    row = SimpleNamespace(grant_origin=None, model_copy=lambda update: SimpleNamespace(**update))
    persist = AsyncMock(return_value=row)
    monkeypatch.setattr("parrot.auth.oauth2.service.IntegrationsService.persist_credential", persist)
    upsert = AsyncMock()
    monkeypatch.setattr("parrot.auth.oauth2.persistence.upsert_users_integration", upsert)
    return persist, upsert


P = Principal(user_id="u1", channel="web", channel_user_id="u1")


@pytest.mark.asyncio
async def test_o365_store_device_grant_durable_first(monkeypatch):
    """Store failure -> CredentialPersistenceError and no Redis key; success -> device_code."""
    mgr, redis, store, events = _make(fail=True)
    persist, upsert = _patch(monkeypatch, mgr)
    with pytest.raises(CredentialPersistenceError):
        await mgr.store_device_grant(P, {"access_token": "a", "refresh_token": "r", "expires_in": 100}, channel="web")
    assert redis.data == {}
    events.publish.assert_not_awaited()
    persist.assert_not_awaited()

    mgr, redis, store, events = _make()
    persist, upsert = _patch(monkeypatch, mgr)
    ts = await mgr.store_device_grant(P, {"access_token": "a", "refresh_token": "r", "expires_in": 100}, channel="web")
    assert ts.grant_origin == "device_code"
    assert store.saved[("u1", "o365")]["grant_origin"] == "device_code"
    assert "oauth2:o365:u1" in "".join(redis.data) or redis.data
    assert events.publish.await_count == 1
    assert persist.await_args.kwargs["channel"] == "web"
    upsert.assert_awaited_once()
    assert O365TokenSet(access_token="x").grant_origin == "authorization_code"


@pytest.mark.asyncio
async def test_devicecode_legacy_expiry_preserved(monkeypatch):
    """Usable legacy token keeps expires_at exactly; others refresh first."""
    now = time.time()
    mgr, redis, store, events = _make()
    _patch(monkeypatch, mgr)
    mgr.refresh_access_token = AsyncMock()
    exp = now + 3600
    ts = await mgr.migrate_legacy_device_grant(
        P, {"access_token": "a", "refresh_token": "r", "expires_at": exp, "scope": "User.Read"}, channel="web",
    )
    assert ts.expires_at == exp
    assert ts.scopes == ["User.Read"]
    mgr.refresh_access_token.assert_not_awaited()

    for bad in (None, "abc", now + 30, now - 10):
        mgr, redis, store, events = _make()
        _patch(monkeypatch, mgr)
        order = []
        mgr.refresh_access_token = AsyncMock(
            side_effect=lambda rt, order=order: order.append("refresh") or {"access_token": "n", "expires_in": 600}
        )
        orig = mgr._discover_identity
        mgr._discover_identity = AsyncMock(side_effect=lambda t, order=order, orig=orig: order.append("probe") or orig.return_value)
        ts = await mgr.migrate_legacy_device_grant(
            P, {"access_token": "a", "refresh_token": "r", "expires_at": bad}, channel="web",
        )
        assert order == ["refresh", "probe"]
        assert ts.access_token == "n"
        assert ts.expires_at == pytest.approx(time.time() + 600, abs=5)


@pytest.mark.asyncio
async def test_devicecode_legacy_refresh_and_failure(monkeypatch):
    """Refresh rotates/keeps refresh token; failures persist nothing."""
    legacy = {"access_token": "a", "refresh_token": "old", "expires_at": 1}
    mgr, _, store, _ = _make()
    _patch(monkeypatch, mgr)
    mgr.refresh_access_token = AsyncMock(return_value={"access_token": "n", "refresh_token": "new", "expires_in": 60})
    assert (await mgr.migrate_legacy_device_grant(P, legacy, channel="web")).refresh_token == "new"

    mgr, _, store, _ = _make()
    _patch(monkeypatch, mgr)
    mgr.refresh_access_token = AsyncMock(return_value={"access_token": "n", "expires_in": 60})
    assert (await mgr.migrate_legacy_device_grant(P, legacy, channel="web")).refresh_token == "old"

    mgr, redis, store, events = _make()
    _patch(monkeypatch, mgr)
    mgr.refresh_access_token = AsyncMock(side_effect=RefreshTransientError("t"))
    with pytest.raises(RefreshTransientError):
        await mgr.migrate_legacy_device_grant(P, legacy, channel="web")
    mgr.refresh_access_token = AsyncMock(side_effect=InvalidGrantError("g"))
    with pytest.raises(InvalidGrantError):
        await mgr.migrate_legacy_device_grant(P, legacy, channel="web")
    mgr.refresh_access_token = AsyncMock(return_value={"access_token": "n", "expires_in": 60})
    mgr._discover_identity = AsyncMock(side_effect=ValueError("graph"))
    with pytest.raises(RefreshTransientError):
        await mgr.migrate_legacy_device_grant(P, legacy, channel="web")
    with pytest.raises(InvalidGrantError):
        await mgr.migrate_legacy_device_grant(P, {"access_token": "a", "expires_at": 1}, channel="web")
    assert store.saved == {} and redis.data == {}
    events.publish.assert_not_awaited()

    mgr, redis, store, events = _make(fail=True)
    _patch(monkeypatch, mgr)
    mgr.refresh_access_token = AsyncMock(return_value={"access_token": "n", "expires_in": 60})
    with pytest.raises(CredentialPersistenceError):
        await mgr.migrate_legacy_device_grant(P, legacy, channel="web")
    assert redis.data == {}


@pytest.mark.asyncio
async def test_legacy_migration_current_record_and_revoke_win(monkeypatch):
    """Existing current record -> None; after revoke() legacy migration is disallowed."""
    mgr, redis, store, events = _make()
    persist, _ = _patch(monkeypatch, mgr)
    await mgr.store_device_grant(P, {"access_token": "a", "refresh_token": "r", "expires_in": 100}, channel="web")
    events.publish.reset_mock()
    saves = store.save_calls
    legacy = {"access_token": "z", "refresh_token": "r", "expires_at": time.time() + 3600}
    assert await mgr.migrate_legacy_device_grant(P, legacy, channel="web") is None
    assert store.save_calls == saves
    events.publish.assert_not_awaited()

    assert await mgr.legacy_migration_allowed("u1") is True
    await mgr.revoke("web", "u1")
    assert await mgr.legacy_migration_allowed("u1") is False
    assert await mgr.migrate_legacy_device_grant(P, legacy, channel="web") is None
    assert store.saved == {}
