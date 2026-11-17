"""Legacy migration, typed refresh, and revoke tests for OAuth2 managers."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Dict, Optional

import pytest

from parrot.auth import oauth2_base
from parrot.auth.oauth2_base import AbstractOAuth2TokenSet, InvalidGrantError, RefreshTransientError

from ._oauth2_fakes import FakeCredentialStore, FakeManager, MemRedis


class _RecordingPublisher:
    """Record emitted connection events."""

    def __init__(self, order: Optional[list[str]] = None) -> None:
        self.calls: list[tuple[Any, Dict[str, Any]]] = []
        self.order = order

    async def publish(self, event: Any, state_payload: Optional[Dict[str, Any]] = None) -> None:
        """Record an event and optional ordering marker."""
        self.calls.append((event, state_payload or {}))
        if self.order is not None:
            self.order.append("event")


class _CountingManager(FakeManager):
    """Fake manager that records refresh endpoint calls."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.refresh_calls = 0

    async def _refresh_request(self, refresh_token: str) -> Dict[str, Any]:
        """Count and yield each scripted refresh request."""
        self.refresh_calls += 1
        await asyncio.sleep(0)
        return await super()._refresh_request(refresh_token)


def _expired_token(*, account_id: str = "account-1") -> AbstractOAuth2TokenSet:
    """Build an expired, refreshable token set."""
    return AbstractOAuth2TokenSet(
        access_token="old-access",
        refresh_token="old-refresh",
        expires_at=time.time() - 120,
        account_id=account_id,
        display_name="Test Account",
    )


async def _seed_grant(
    redis: MemRedis,
    store: FakeCredentialStore,
    token: AbstractOAuth2TokenSet,
    *,
    user_id: str = "1042",
) -> None:
    """Seed matching durable and cache copies without affecting call counts."""
    payload = token.model_dump(mode="json")
    store.rows[(user_id, "fake")] = payload
    await redis.set(f"oauth2:fake:{user_id}", json.dumps(payload))


@pytest.mark.asyncio
async def test_legacy_key_read_rewrite_delete(monkeypatch: pytest.MonkeyPatch) -> None:
    """A legacy token migrates once and legacy reads stop after cutover."""
    redis = MemRedis()
    store = FakeCredentialStore()
    manager = FakeManager(
        "cid",
        "https://cb",
        client_secret="s",
        redis_client=redis,
        credential_store=store,
    )
    token = AbstractOAuth2TokenSet(access_token="legacy", expires_at=time.time() + 3600, account_id="account-1")
    legacy_key = "oauth2:fake:telegram:88123"
    await redis.set(legacy_key, token.model_dump_json())
    vault_deletes: list[tuple[str, str]] = []

    async def delete_legacy_vault(user_id: str, vault_name: str) -> None:
        vault_deletes.append((user_id, vault_name))

    monkeypatch.setattr(oauth2_base, "delete_vault_credential", delete_legacy_vault)
    monkeypatch.setattr(oauth2_base, "OAUTH2_LEGACY_KEYS_UNTIL", "")

    migrated = await manager.get_valid_token("telegram", "1042", channel_user_id="88123")

    assert migrated == token
    assert await redis.get("oauth2:fake:1042") is not None
    assert await redis.get(legacy_key) is None
    assert store.rows[("1042", "fake")]["access_token"] == "legacy"
    # Migration must UPSERT into the durable store (minted=True): an update-only save would silently
    # skip a missing row and the legacy source is deleted right after.
    assert store.minted_flags == [True]
    assert vault_deletes == [("88123", "oauth2_fake_telegram_88123")]

    await redis.delete("oauth2:fake:1042")
    store.rows.clear()
    await redis.set(legacy_key, token.model_dump_json())
    monkeypatch.setattr(oauth2_base, "OAUTH2_LEGACY_KEYS_UNTIL", "2000-01-01")

    assert await manager.get_valid_token("telegram", "1042", channel_user_id="88123") is None
    assert await redis.get(legacy_key) is not None


@pytest.mark.asyncio
async def test_refresh_invalid_grant_revokes_and_emits() -> None:
    """Invalid grants delete local state and emit refresh_failed."""
    redis = MemRedis()
    store = FakeCredentialStore()
    publisher = _RecordingPublisher()
    manager = FakeManager(
        "cid",
        "https://cb",
        client_secret="s",
        redis_client=redis,
        credential_store=store,
        event_publisher=publisher,
    )
    token = _expired_token()
    await _seed_grant(redis, store, token)
    manager.refresh_result = InvalidGrantError("invalid grant")

    with pytest.raises(InvalidGrantError):
        await manager.get_valid_token("telegram", "1042")

    assert ("1042", "fake") not in store.rows
    assert await redis.get("oauth2:fake:1042") is None
    assert len(publisher.calls) == 1
    event, _ = publisher.calls[0]
    assert event.kind == "connection.refresh_failed"
    assert event.reason == "InvalidGrantError"


@pytest.mark.asyncio
async def test_refresh_transient_keeps_grant() -> None:
    """Transient refresh failures preserve the grant and emit no event."""
    redis = MemRedis()
    store = FakeCredentialStore()
    publisher = _RecordingPublisher()
    manager = FakeManager(
        "cid",
        "https://cb",
        client_secret="s",
        redis_client=redis,
        credential_store=store,
        event_publisher=publisher,
    )
    token = _expired_token()
    await _seed_grant(redis, store, token)
    manager.refresh_result = RefreshTransientError("try again")

    with pytest.raises(RefreshTransientError):
        await manager.get_valid_token("telegram", "1042")

    assert store.rows[("1042", "fake")]["refresh_token"] == "old-refresh"
    assert await redis.get("oauth2:fake:1042") is not None
    assert publisher.calls == []


@pytest.mark.asyncio
async def test_concurrent_refresh_single_flight() -> None:
    """Concurrent callers share one refresh and persist its rotated token once."""
    redis = MemRedis()
    store = FakeCredentialStore()
    manager = _CountingManager(
        "cid",
        "https://cb",
        client_secret="s",
        redis_client=redis,
        credential_store=store,
    )
    token = _expired_token()
    await _seed_grant(redis, store, token)
    manager.refresh_result = {
        "access_token": "new-access",
        "refresh_token": "rotated-refresh",
        "expires_in": 3600,
        "scope": "read",
    }

    first, second = await asyncio.gather(
        manager.get_valid_token("telegram", "1042"),
        manager.get_valid_token("telegram", "1042"),
    )

    assert first is not None and first.refresh_token == "rotated-refresh"
    assert second is not None and second.refresh_token == "rotated-refresh"
    assert manager.refresh_calls == 1
    assert store.calls.count(("save", "1042", "fake")) == 1
    assert store.rows[("1042", "fake")]["refresh_token"] == "rotated-refresh"


@pytest.mark.asyncio
async def test_revoke_calls_remote_then_local_then_event(monkeypatch: pytest.MonkeyPatch) -> None:
    """Revocation orders remote work before local deletion and publication."""
    order: list[str] = []

    class _OrderedStore(FakeCredentialStore):
        async def delete(self, user_id: str, provider: str) -> None:
            order.append("local")
            await super().delete(user_id, provider)

    class _OrderedManager(FakeManager):
        async def _revoke_remote(self, token_set: AbstractOAuth2TokenSet) -> None:
            del token_set
            order.append("remote")

    async def delete_legacy_vault(user_id: str, vault_name: str) -> None:
        del user_id, vault_name

    redis = MemRedis()
    store = _OrderedStore()
    publisher = _RecordingPublisher(order)
    manager = _OrderedManager(
        "cid",
        "https://cb",
        client_secret="s",
        redis_client=redis,
        credential_store=store,
        event_publisher=publisher,
    )
    token = _expired_token()
    await _seed_grant(redis, store, token)
    await redis.set("oauth2:fake:telegram:88123", token.model_dump_json())
    monkeypatch.setattr(oauth2_base, "delete_vault_credential", delete_legacy_vault)

    await manager.revoke("telegram", "1042", channel_user_id="88123")

    assert order == ["remote", "local", "event"]
    assert store.rows == {}
    assert await redis.get("oauth2:fake:1042") is None
    assert await redis.get("oauth2:fake:telegram:88123") is None
    assert publisher.calls[0][0].kind == "connection.revoked"
