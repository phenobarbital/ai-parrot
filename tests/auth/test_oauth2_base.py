"""Unit tests for :mod:`parrot.auth.oauth2_base`.

Exercise the abstract OAuth2 manager with an in-memory subclass and a
``fakeredis`` instance so the full lifecycle (URL → callback → cache →
vault → refresh → revoke) can be validated without hitting the network.
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock

import pytest

from parrot.auth.oauth2_base import AbstractOAuth2Manager, AbstractOAuth2TokenSet


pytest.importorskip("fakeredis")
import fakeredis.aioredis  # noqa: E402


class _FakeTokenSet(AbstractOAuth2TokenSet):
    """Fake provider token set — adds a provider-specific identity field."""

    provider_user_handle: str = ""


class _FakeManager(AbstractOAuth2Manager):
    """In-memory manager used for testing the abstract base."""

    provider_id = "fakeprov"
    authorization_url = "https://auth.example.com/authorize"
    token_url = "https://auth.example.com/token"
    default_scopes = ["read", "write"]
    token_set_cls = _FakeTokenSet
    use_pkce = True
    require_client_secret = True

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.exchange_calls: list = []
        self.refresh_calls: list = []
        self.identity_calls: list = []
        self._refresh_responses: list = []
        self._refresh_error: Optional[Exception] = None

    async def _exchange_code(self, code: str, code_verifier):
        self.exchange_calls.append((code, code_verifier))
        return {
            "access_token": f"AT-{code}",
            "refresh_token": f"RT-{code}",
            "expires_in": 3600,
            "scope": "read write",
        }

    async def _refresh_request(self, refresh_token: str):
        self.refresh_calls.append(refresh_token)
        if self._refresh_error is not None:
            raise self._refresh_error
        if self._refresh_responses:
            return self._refresh_responses.pop(0)
        return {
            "access_token": f"AT2-{refresh_token}",
            "refresh_token": f"RT2-{refresh_token}",
            "expires_in": 3600,
            "scope": "read write",
        }

    async def _discover_identity(self, access_token: str):
        self.identity_calls.append(access_token)
        return {"id": "USER-1", "handle": "alice", "display_name": "Alice"}

    def _build_token_set(self, token_response, identity):
        now = time.time()
        return _FakeTokenSet(
            access_token=token_response["access_token"],
            refresh_token=token_response.get("refresh_token", ""),
            expires_at=now + int(token_response.get("expires_in", 3600)),
            scopes=token_response.get("scope", "").split(),
            granted_at=now,
            last_refreshed_at=now,
            account_id=identity["id"],
            display_name=identity["display_name"],
            provider_user_handle=identity["handle"],
        )


@pytest.fixture
async def vault_store():
    """In-memory dict used as the fake vault backing store."""
    return {}


@pytest.fixture
async def manager(vault_store):
    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    writer = AsyncMock()

    async def _write(user_id, vault_name, payload):
        vault_store[(user_id, vault_name)] = payload
        writer(user_id, vault_name, payload)

    async def _read(user_id, vault_name):
        try:
            return vault_store[(user_id, vault_name)]
        except KeyError:
            raise KeyError(vault_name)

    async def _delete(user_id, vault_name):
        vault_store.pop((user_id, vault_name), None)

    mgr = _FakeManager(
        client_id="cid",
        client_secret="csec",
        redirect_uri="https://app.example.com/cb",
        redis_client=redis_client,
        vault_writer=_write,
        vault_reader=_read,
        vault_deleter=_delete,
    )
    yield mgr
    close = getattr(redis_client, "aclose", None) or redis_client.close
    res = close()
    if hasattr(res, "__await__"):
        await res
    await mgr.aclose()


# ---------------------------------------------------------------------------
# Authorization URL
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_authorization_url_stores_pkce_nonce(manager):
    url, nonce = await manager.create_authorization_url(
        channel="web", user_id="42", extra_state={"agent_id": "operator"},
    )
    assert url.startswith("https://auth.example.com/authorize?")
    assert f"state={nonce}" in url
    assert "code_challenge=" in url
    assert "code_challenge_method=S256" in url

    raw = await manager.redis.get(manager._nonce_key(nonce))
    payload = json.loads(raw)
    assert payload["channel"] == "web"
    assert payload["user_id"] == "42"
    assert "code_verifier" in payload
    assert payload["extra"] == {"agent_id": "operator"}


@pytest.mark.asyncio
async def test_handle_callback_exchanges_and_persists(manager, vault_store):
    url, nonce = await manager.create_authorization_url("web", "42")
    token, state_payload = await manager.handle_callback("AUTHCODE", nonce)

    assert isinstance(token, _FakeTokenSet)
    assert token.access_token == "AT-AUTHCODE"
    assert token.refresh_token == "RT-AUTHCODE"
    assert token.account_id == "USER-1"
    assert token.provider_user_handle == "alice"
    assert state_payload["user_id"] == "42"

    # Redis cache populated.
    cached = await manager.redis.get(manager._token_key("web", "42"))
    assert json.loads(cached)["access_token"] == "AT-AUTHCODE"
    # Vault populated.
    assert vault_store[("42", manager._vault_name("web", "42"))]["access_token"] == "AT-AUTHCODE"

    # Nonce is single-use.
    assert await manager.redis.get(manager._nonce_key(nonce)) is None


@pytest.mark.asyncio
async def test_handle_callback_rejects_unknown_state(manager):
    with pytest.raises(ValueError):
        await manager.handle_callback("AUTHCODE", "no-such-nonce")


# ---------------------------------------------------------------------------
# get_valid_token, hydration, refresh, revoke
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_valid_token_returns_cached(manager):
    _, nonce = await manager.create_authorization_url("web", "42")
    await manager.handle_callback("CODE1", nonce)

    token = await manager.get_valid_token("web", "42")
    assert token is not None
    assert token.access_token == "AT-CODE1"
    assert not manager.refresh_calls


@pytest.mark.asyncio
async def test_get_valid_token_hydrates_from_vault_when_redis_empty(manager, vault_store):
    _, nonce = await manager.create_authorization_url("web", "42")
    await manager.handle_callback("CODE1", nonce)

    # Simulate a Redis flush — token only lives in the vault now.
    await manager.redis.delete(manager._token_key("web", "42"))
    assert await manager.redis.get(manager._token_key("web", "42")) is None

    token = await manager.get_valid_token("web", "42")
    assert token is not None
    assert token.access_token == "AT-CODE1"
    # Cache has been re-populated.
    assert await manager.redis.get(manager._token_key("web", "42")) is not None


@pytest.mark.asyncio
async def test_get_valid_token_refreshes_when_expired(manager):
    _, nonce = await manager.create_authorization_url("web", "42")
    await manager.handle_callback("CODE1", nonce)

    # Force expiry on the cached token by rewriting it with past expiry.
    cached_raw = await manager.redis.get(manager._token_key("web", "42"))
    cached = json.loads(cached_raw)
    cached["expires_at"] = time.time() - 100
    await manager.redis.set(manager._token_key("web", "42"), json.dumps(cached))

    token = await manager.get_valid_token("web", "42")
    assert token is not None
    assert manager.refresh_calls == ["RT-CODE1"]
    assert token.access_token == "AT2-RT-CODE1"
    assert not token.is_expired


@pytest.mark.asyncio
async def test_revoke_clears_both_layers(manager, vault_store):
    _, nonce = await manager.create_authorization_url("web", "42")
    await manager.handle_callback("CODE1", nonce)

    await manager.revoke("web", "42")
    assert await manager.redis.get(manager._token_key("web", "42")) is None
    assert ("42", manager._vault_name("web", "42")) not in vault_store


@pytest.mark.asyncio
async def test_get_valid_token_returns_none_when_no_token(manager):
    assert await manager.get_valid_token("web", "ghost") is None


@pytest.mark.asyncio
async def test_refresh_failure_revokes_locally(manager, vault_store):
    _, nonce = await manager.create_authorization_url("web", "42")
    await manager.handle_callback("CODE1", nonce)

    # Force expiry + a 400/PermissionError on refresh.
    cached_raw = await manager.redis.get(manager._token_key("web", "42"))
    cached = json.loads(cached_raw)
    cached["expires_at"] = time.time() - 100
    await manager.redis.set(manager._token_key("web", "42"), json.dumps(cached))
    manager._refresh_error = PermissionError("invalid_grant")

    with pytest.raises(PermissionError):
        await manager.get_valid_token("web", "42")

    # Both layers were revoked.
    assert await manager.redis.get(manager._token_key("web", "42")) is None
    assert ("42", manager._vault_name("web", "42")) not in vault_store


# ---------------------------------------------------------------------------
# Refresh contention — distributed lock
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_refresh_invokes_endpoint_once(manager):
    _, nonce = await manager.create_authorization_url("web", "42")
    await manager.handle_callback("CODE1", nonce)

    # Expire the cached token.
    cached_raw = await manager.redis.get(manager._token_key("web", "42"))
    cached = json.loads(cached_raw)
    cached["expires_at"] = time.time() - 100
    await manager.redis.set(manager._token_key("web", "42"), json.dumps(cached))

    # Fire two concurrent get_valid_token calls.
    results = await asyncio.gather(
        manager.get_valid_token("web", "42"),
        manager.get_valid_token("web", "42"),
    )
    assert all(r is not None for r in results)
    # Distributed lock + post-acquire re-read should ensure only one refresh.
    assert len(manager.refresh_calls) == 1
