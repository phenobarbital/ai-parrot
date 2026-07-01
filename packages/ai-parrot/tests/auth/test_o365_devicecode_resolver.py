"""Unit tests for `O365DeviceCodeCredentialResolver` (FEAT-266)."""
import time

import pytest

from parrot.auth.oauth2.o365_devicecode_provider import O365DeviceCodeCredentialResolver


class FakeO365Client:
    """Stand-in for `O365Client` — controls `interactive_login` behavior."""

    tenant_id = "tenant-abc"

    def __init__(self, token_response=None, raise_exc=None, flow=None):
        self.token_response = token_response
        self.raise_exc = raise_exc
        self.flow = flow or {
            "verification_uri": "https://microsoft.com/devicelogin",
            "user_code": "A1B2-C3D4",
            "expires_in": 900,
            "message": "To sign in, use a web browser...",
        }
        self.calls = []

    async def interactive_login(self, scopes=None, open_browser=True, device_flow_callback=None, **kwargs):
        self.calls.append({"scopes": scopes, "open_browser": open_browser})
        if device_flow_callback:
            device_flow_callback(self.flow)
        if self.raise_exc:
            raise self.raise_exc
        return self.token_response


class FakeManager:
    """Stand-in for `O365OAuthManager` — controls `refresh_access_token` behavior."""

    def __init__(self, refresh_response=None, raise_exc=None):
        self.refresh_response = refresh_response
        self.raise_exc = raise_exc
        self.calls = []

    async def refresh_access_token(self, refresh_token):
        self.calls.append(refresh_token)
        if self.raise_exc:
            raise self.raise_exc
        return self.refresh_response


class FakeVault:
    """Stand-in for `VaultTokenSync` — in-memory `{(user_id, provider): tokens}` store."""

    def __init__(self):
        self._store = {}

    def seed(self, user_id, provider, tokens):
        self._store[(user_id, provider)] = dict(tokens)

    async def read_tokens(self, user_id, provider):
        return self._store.get((user_id, provider))

    async def store_tokens(self, user_id, provider, tokens):
        existing = self._store.get((user_id, provider), {})
        existing.update({k: v for k, v in tokens.items() if v is not None})
        self._store[(user_id, provider)] = existing


@pytest.fixture
def fake_vault():
    return FakeVault()


@pytest.mark.asyncio
async def test_cache_hit(fake_vault):
    fake_vault.seed(
        "user@x", "o365",
        {"access_token": "tok", "expires_at": time.time() + 99999},
    )
    o365 = FakeO365Client()
    manager = FakeManager()
    resolver = O365DeviceCodeCredentialResolver(
        o365_client=o365, o365_oauth_manager=manager, vault_token_sync=fake_vault,
        scopes=["User.Read", "offline_access"],
    )

    result = await resolver.resolve("cli", "user@x")

    assert result == "tok"
    assert o365.calls == []  # no device flow triggered


@pytest.mark.asyncio
async def test_refresh_on_expiry(fake_vault):
    fake_vault.seed(
        "user@x", "o365",
        {"access_token": "old-tok", "refresh_token": "rt-1", "expires_at": time.time() - 10},
    )
    o365 = FakeO365Client()
    manager = FakeManager(refresh_response={
        "access_token": "new-tok", "expires_in": 3600, "scope": "User.Read",
    })
    resolver = O365DeviceCodeCredentialResolver(
        o365_client=o365, o365_oauth_manager=manager, vault_token_sync=fake_vault,
    )

    result = await resolver.resolve("cli", "user@x")

    assert result == "new-tok"
    assert manager.calls == ["rt-1"]
    assert o365.calls == []  # no device flow triggered
    persisted = fake_vault._store[("user@x", "o365")]
    assert persisted["access_token"] == "new-tok"
    assert persisted["refresh_token"] == "rt-1"  # carried over (refresh response omitted it)


@pytest.mark.asyncio
async def test_device_flow_on_miss(fake_vault):
    captured = {}

    def prompt_callback(flow):
        captured.update(flow)

    o365 = FakeO365Client(token_response={
        "access_token": "device-tok",
        "refresh_token": "device-rt",
        "expires_in": 3600,
        "scope": "User.Read offline_access",
        "id_token": "id-tok",
    })
    manager = FakeManager()
    resolver = O365DeviceCodeCredentialResolver(
        o365_client=o365, o365_oauth_manager=manager, vault_token_sync=fake_vault,
        prompt_callback=prompt_callback,
    )

    result = await resolver.resolve("cli", "user@x")

    assert result == "device-tok"
    assert captured["user_code"] == "A1B2-C3D4"
    persisted = fake_vault._store[("user@x", "o365")]
    assert persisted["access_token"] == "device-tok"
    assert persisted["refresh_token"] == "device-rt"
    assert persisted["id_token"] == "id-tok"
    assert persisted["tenant_id"] == "tenant-abc"
    assert persisted["expires_at"] > time.time()


@pytest.mark.asyncio
async def test_refresh_dead_falls_back_to_device_flow(fake_vault):
    fake_vault.seed(
        "user@x", "o365",
        {"access_token": "old-tok", "refresh_token": "dead-rt", "expires_at": time.time() - 10},
    )
    o365 = FakeO365Client(token_response={
        "access_token": "fresh-tok", "expires_in": 3600,
    })
    manager = FakeManager(raise_exc=PermissionError("dead refresh token"))
    resolver = O365DeviceCodeCredentialResolver(
        o365_client=o365, o365_oauth_manager=manager, vault_token_sync=fake_vault,
    )

    result = await resolver.resolve("cli", "user@x")

    assert result == "fresh-tok"
    assert len(o365.calls) == 1


@pytest.mark.asyncio
async def test_no_partial_write_on_timeout(fake_vault):
    o365 = FakeO365Client(raise_exc=RuntimeError("device flow timed out"))
    manager = FakeManager()
    resolver = O365DeviceCodeCredentialResolver(
        o365_client=o365, o365_oauth_manager=manager, vault_token_sync=fake_vault,
    )

    with pytest.raises(RuntimeError):
        await resolver.resolve("cli", "user@x")

    assert ("user@x", "o365") not in fake_vault._store


@pytest.mark.asyncio
async def test_fail_closed_without_identity(fake_vault):
    o365 = FakeO365Client()
    manager = FakeManager()
    resolver = O365DeviceCodeCredentialResolver(
        o365_client=o365, o365_oauth_manager=manager, vault_token_sync=fake_vault,
    )

    with pytest.raises((ValueError, PermissionError)):
        await resolver.resolve("cli", "")


@pytest.mark.asyncio
async def test_get_auth_url_returns_device_login_url(fake_vault):
    resolver = O365DeviceCodeCredentialResolver(
        o365_client=FakeO365Client(), o365_oauth_manager=FakeManager(),
        vault_token_sync=fake_vault,
    )
    url = await resolver.get_auth_url("cli", "user@x")
    assert url == "https://microsoft.com/devicelogin"


# ---------------------------------------------------------------------------
# FEAT-267: missing expires_at is treated as expired, not valid-forever
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_expires_at_on_read_is_treated_as_expired(fake_vault):
    """A freshly-read o365:* token set missing `expires_at` (e.g. from a
    partial VaultTokenSync.store_tokens write) must NOT be treated as a
    valid-forever cache hit — resolve() must attempt refresh (or fall back
    to the device flow) instead.
    """
    fake_vault.seed(
        "user@x", "o365",
        {"access_token": "stale-tok", "refresh_token": "rt-1"},  # no expires_at
    )
    o365 = FakeO365Client()
    manager = FakeManager(refresh_response={
        "access_token": "refreshed-tok", "expires_in": 3600, "scope": "User.Read",
    })
    resolver = O365DeviceCodeCredentialResolver(
        o365_client=o365, o365_oauth_manager=manager, vault_token_sync=fake_vault,
    )

    result = await resolver.resolve("cli", "user@x")

    assert result == "refreshed-tok"
    assert manager.calls == ["rt-1"]  # refresh was attempted, not a silent cache-hit
    assert o365.calls == []


@pytest.mark.asyncio
async def test_missing_expires_at_without_refresh_token_falls_back_to_device_flow(fake_vault):
    """Missing `expires_at` and no refresh_token -> device flow, not a cache-hit."""
    fake_vault.seed(
        "user@x", "o365",
        {"access_token": "stale-tok"},  # no expires_at, no refresh_token
    )
    o365 = FakeO365Client(token_response={
        "access_token": "device-tok", "expires_in": 3600, "scope": "User.Read",
    })
    manager = FakeManager()
    resolver = O365DeviceCodeCredentialResolver(
        o365_client=o365, o365_oauth_manager=manager, vault_token_sync=fake_vault,
    )

    result = await resolver.resolve("cli", "user@x")

    assert result == "device-tok"
    assert len(o365.calls) == 1


@pytest.mark.asyncio
async def test_is_connected_false_when_expires_at_missing(fake_vault):
    """is_connected() mirrors resolve()'s interpretation — no silent divergence."""
    fake_vault.seed(
        "user@x", "o365",
        {"access_token": "stale-tok"},  # no expires_at
    )
    resolver = O365DeviceCodeCredentialResolver(
        o365_client=FakeO365Client(), o365_oauth_manager=FakeManager(),
        vault_token_sync=fake_vault,
    )

    assert await resolver.is_connected("cli", "user@x") is False


@pytest.mark.asyncio
async def test_is_connected_true_when_expires_at_present_and_fresh(fake_vault):
    fake_vault.seed(
        "user@x", "o365",
        {"access_token": "tok", "expires_at": time.time() + 99999},
    )
    resolver = O365DeviceCodeCredentialResolver(
        o365_client=FakeO365Client(), o365_oauth_manager=FakeManager(),
        vault_token_sync=fake_vault,
    )

    assert await resolver.is_connected("cli", "user@x") is True
