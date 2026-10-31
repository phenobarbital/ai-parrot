"""ConnectionCache / RemoteConnectionResolver / build_cli_broker (FEAT-774 M4, AC-6)."""

from __future__ import annotations

import asyncio
import base64
import os
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from parrot.auth.credentials import AuthRequiredPayload
from parrot.auth.oauth2.local_cache import CachedConnection, ConnectionCache, RemoteConnectionResolver, build_cli_broker
from parrot.auth.oauth2.models import NotConnected, PulledToken
from parrot.cli.login import LoginRecord, LoginStore


def _entry(provider: str = "jira", *, expires_at: float | None = None) -> CachedConnection:
    """Return a cache entry with a deterministic token for tests."""
    return CachedConnection(
        provider=provider,
        access_token=f"{provider}-access-token",
        expires_at=expires_at if expires_at is not None else time.time() + 3600,
        scopes=["read"],
        account_id="account-1",
        pulled_at=time.time(),
    )


def _login_record() -> LoginRecord:
    """Return a valid login record with a 32-byte base64url cache key."""
    return LoginRecord(
        server_url="https://parrot.test",
        access_token="login-access-token",
        expires_at=time.time() + 3600,
        user_id="user-1",
        cache_key=base64.urlsafe_b64encode(b"k" * 32).decode("ascii").rstrip("="),
        issued_at=time.time(),
    )


async def test_connection_cache_encrypt_roundtrip_and_tamper(tmp_path, caplog):
    """Cache encryption, private permissions, tamper handling, and wrong keys work."""
    path = tmp_path / "connections.cache"
    cache = ConnectionCache(path, b"k" * 32)
    entry = _entry()

    await cache.put(entry)

    assert await cache.get("jira") == entry
    assert path.stat().st_mode & 0o777 == 0o600
    raw = path.read_bytes()
    assert entry.access_token.encode() not in raw

    path.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
    assert await cache.get("jira") is None
    assert "connection cache unreadable; treating as empty" in caplog.text

    await cache.put(entry)
    assert await ConnectionCache(path, b"z" * 32).get("jira") is None


async def test_cache_io_off_event_loop_and_single_flight(tmp_path, monkeypatch):
    """Cache operations use to_thread and concurrent misses make one remote pull."""
    calls = []
    original_to_thread = asyncio.to_thread

    async def spying_to_thread(function, /, *args, **kwargs):
        calls.append(function)
        return await original_to_thread(function, *args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", spying_to_thread)
    cache = ConnectionCache(tmp_path / "connections.cache", b"k" * 32)
    client = AsyncMock()
    client.pull_token.return_value = PulledToken(
        provider="jira",
        access_token="pulled-access-token",
        expires_at=time.time() + 3600,
        scopes=["read"],
        account_id="account-1",
    )
    resolver = RemoteConnectionResolver("jira", cache=cache, client=client)

    results = await asyncio.gather(*(resolver.resolve("cli", "user-1") for _ in range(10)))

    assert results == ["pulled-access-token"] * 10
    client.pull_token.assert_awaited_once_with("jira")
    assert cache._read_sync in calls
    assert cache._write_sync in calls


async def test_remote_resolver_hit_miss_not_connected(tmp_path):
    """Resolver uses fresh entries, refreshes expired ones, and maps disconnects to misses."""
    cache = ConnectionCache(tmp_path / "connections.cache", b"k" * 32)
    client = AsyncMock()
    resolver = RemoteConnectionResolver("jira", cache=cache, client=client)

    await cache.put(_entry())
    assert await resolver.resolve("cli", "user-1") == "jira-access-token"
    client.pull_token.assert_not_awaited()

    await cache.put(_entry(expires_at=time.time() - 1))
    client.pull_token.return_value = PulledToken(
        provider="jira",
        access_token="refreshed-access-token",
        expires_at=time.time() + 3600,
    )
    assert await resolver.resolve("cli", "user-1") == "refreshed-access-token"
    client.pull_token.assert_awaited_once_with("jira")

    disconnected = RemoteConnectionResolver("github", cache=cache, client=client)
    client.pull_token.side_effect = NotConnected(AuthRequiredPayload(provider="github"))
    assert await disconnected.resolve("cli", "user-1") is None
    client.start_connect.return_value = SimpleNamespace(auth_url="https://auth.example/connect")
    assert await disconnected.get_auth_url("agentd", "user-1") == "https://auth.example/connect"
    client.start_connect.assert_awaited_once_with("github", channel="agentd")


def test_build_cli_broker_registers_declared_providers(tmp_path):
    """Builder registers exactly one OAuth2 resolver for each declared provider."""
    store = LoginStore(tmp_path / "login.json")
    store.save(_login_record())
    client = AsyncMock()

    broker = build_cli_broker(store, {"jira", "fake"}, client=client)

    assert set(broker._resolvers) == {"jira", "fake"}
    assert {auth_kind for _, auth_kind in broker._resolvers.values()} == {"oauth2"}
    assert all(isinstance(resolver, RemoteConnectionResolver) for resolver, _ in broker._resolvers.values())
