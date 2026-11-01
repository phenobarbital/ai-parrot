"""Unit tests for the principal-keyed O365 device-code resolver."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from parrot.auth.oauth2.o365_devicecode_provider import O365DeviceCodeCredentialResolver
from parrot.auth.principal import Principal, set_principal_resolver


class FakeO365Client:
    """Controllable stand-in for the O365 device-code client."""

    def __init__(self, token_response=None, raise_exc=None):
        self.token_response = token_response
        self.raise_exc = raise_exc
        self.calls = []

    async def interactive_login(self, scopes=None, open_browser=True, device_flow_callback=None, **kwargs):
        self.calls.append({"scopes": scopes, "open_browser": open_browser})
        if device_flow_callback:
            device_flow_callback(
                {
                    "verification_uri": "https://microsoft.com/devicelogin",
                    "user_code": "A1B2-C3D4",
                    "expires_in": 900,
                    "message": "Sign in with the device code",
                }
            )
        if self.raise_exc:
            raise self.raise_exc
        return self.token_response


class FakeManager:
    """AsyncMock-backed stand-in for ``O365OAuthManager``."""

    def __init__(self):
        self.get_valid_token = AsyncMock(return_value=None)
        self.is_connected = AsyncMock(return_value=False)
        self.store_device_grant = AsyncMock()
        self.migrate_legacy_device_grant = AsyncMock(return_value=None)


class FakeLegacyVault:
    """Legacy ``VaultTokenSync`` double exposing read/delete only."""

    def __init__(self, legacy=None):
        self.legacy = legacy
        self.read_tokens = AsyncMock(side_effect=self._read)
        self.delete_tokens = AsyncMock(side_effect=self._delete)

    async def _read(self, user_id, provider):
        return self.legacy

    async def _delete(self, user_id, provider):
        self.legacy = None


class FakePrincipalResolver:
    """Resolve test channel identities to one platform principal."""

    def __init__(self, principal):
        self.principal = principal

    async def resolve(self, channel, channel_user_id):
        return self.principal


@pytest.fixture(autouse=True)
def registered_principal_resolver():
    principal = Principal(
        user_id="1042",
        canonical_identity="user@x",
        channel="cli",
        channel_user_id="user@x",
    )
    set_principal_resolver(FakePrincipalResolver(principal))
    yield principal
    set_principal_resolver(None)


@pytest.mark.asyncio
async def test_devicecode_resolver_reads_through_manager(registered_principal_resolver):
    manager = FakeManager()
    manager.get_valid_token.side_effect = [
        SimpleNamespace(access_token="cached-token"),
        SimpleNamespace(access_token="refreshed-token"),
    ]
    legacy = FakeLegacyVault({"access_token": "legacy-token"})
    client = FakeO365Client()
    resolver = O365DeviceCodeCredentialResolver(client, manager, legacy_vault=legacy)

    assert await resolver.resolve("cli", "user@x") == "cached-token"
    assert await resolver.resolve("cli", "user@x") == "refreshed-token"

    assert manager.get_valid_token.await_count == 2
    manager.get_valid_token.assert_awaited_with("cli", registered_principal_resolver.user_id)
    legacy.read_tokens.assert_not_awaited()
    assert client.calls == []


@pytest.mark.asyncio
async def test_devicecode_resolver_fails_closed_without_principal():
    set_principal_resolver(FakePrincipalResolver(None))
    manager = FakeManager()
    legacy = FakeLegacyVault({"access_token": "legacy-token"})
    client = FakeO365Client(token_response={"access_token": "device-token"})
    resolver = O365DeviceCodeCredentialResolver(client, manager, legacy_vault=legacy)

    with pytest.raises(PermissionError, match="No platform principal"):
        await resolver.resolve("cli", "unbound@x")

    manager.get_valid_token.assert_not_awaited()
    legacy.read_tokens.assert_not_awaited()
    assert client.calls == []


@pytest.mark.asyncio
async def test_devicecode_legacy_migration_once(monkeypatch):
    manager = FakeManager()
    migrated = SimpleNamespace(access_token="migrated-token")
    manager.get_valid_token.side_effect = [None, migrated, None]
    manager.migrate_legacy_device_grant.return_value = migrated
    legacy = FakeLegacyVault({"access_token": "legacy-token", "refresh_token": "legacy-refresh"})
    client = FakeO365Client(token_response={"access_token": "device-token", "expires_in": 3600})
    resolver = O365DeviceCodeCredentialResolver(client, manager, legacy_vault=legacy)

    assert await resolver.resolve("cli", "user@x") == "migrated-token"
    assert await resolver.resolve("cli", "user@x") == "migrated-token"
    legacy.read_tokens.assert_awaited_once_with("user@x", "o365")
    legacy.delete_tokens.assert_awaited_once_with("user@x", "o365")
    manager.migrate_legacy_device_grant.assert_awaited_once()

    monkeypatch.setattr("parrot.auth.oauth2.o365_devicecode_provider._legacy_window_open", lambda: False)
    assert await resolver.resolve("cli", "user@x") == "device-token"
    assert legacy.read_tokens.await_count == 1


@pytest.mark.asyncio
async def test_devicecode_legacy_concurrent_replace_revoke():
    current = SimpleNamespace(access_token="current-token")

    # A current record won the race: the spent legacy entry is deleted and the winner is returned
    # without a redundant device flow.
    losing_manager = FakeManager()
    losing_manager.get_valid_token.side_effect = [None, current, current]
    losing_legacy = FakeLegacyVault({"access_token": "legacy-token"})
    losing_client = FakeO365Client(token_response={"access_token": "device-token", "expires_in": 3600})
    losing_resolver = O365DeviceCodeCredentialResolver(losing_client, losing_manager, legacy_vault=losing_legacy)

    assert await losing_resolver.resolve("cli", "user@x") == "current-token"
    assert await losing_resolver.resolve("cli", "user@x") == "current-token"
    losing_manager.migrate_legacy_device_grant.assert_awaited_once()
    losing_legacy.delete_tokens.assert_awaited_once_with("user@x", "o365")
    losing_manager.store_device_grant.assert_not_awaited()
    assert losing_client.calls == []

    # A disconnect tombstone blocked the import: the legacy entry is deleted and the device flow runs.
    revoked_manager = FakeManager()
    revoked_legacy = FakeLegacyVault({"access_token": "legacy-token"})
    revoked_client = FakeO365Client(token_response={"access_token": "device-token", "expires_in": 3600})
    revoked_resolver = O365DeviceCodeCredentialResolver(revoked_client, revoked_manager, legacy_vault=revoked_legacy)

    assert await revoked_resolver.resolve("cli", "user@x") == "device-token"
    revoked_legacy.delete_tokens.assert_awaited_once_with("user@x", "o365")
    assert revoked_legacy.legacy is None
    revoked_manager.store_device_grant.assert_awaited_once()
    assert len(revoked_client.calls) == 1

    migrated = SimpleNamespace(access_token="migrated-token")
    cleanup_manager = FakeManager()
    cleanup_manager.get_valid_token.side_effect = [None, current]
    cleanup_manager.migrate_legacy_device_grant.return_value = migrated
    cleanup_legacy = FakeLegacyVault({"access_token": "legacy-token"})
    cleanup_legacy.delete_tokens.side_effect = [RuntimeError("delete unavailable"), None]
    cleanup_resolver = O365DeviceCodeCredentialResolver(FakeO365Client(), cleanup_manager, legacy_vault=cleanup_legacy)

    assert await cleanup_resolver.resolve("cli", "user@x") == "migrated-token"
    assert await cleanup_resolver.resolve("cli", "user@x") == "current-token"
    assert cleanup_legacy.delete_tokens.await_count == 2
    cleanup_manager.migrate_legacy_device_grant.assert_awaited_once()
    cleanup_manager.store_device_grant.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_partial_write_on_timeout():
    manager = FakeManager()
    client = FakeO365Client(raise_exc=RuntimeError("device flow timed out"))
    resolver = O365DeviceCodeCredentialResolver(client, manager)

    with pytest.raises(RuntimeError, match="timed out"):
        await resolver.resolve("cli", "user@x")

    manager.store_device_grant.assert_not_awaited()


@pytest.mark.asyncio
async def test_is_connected_uses_principal_manager(registered_principal_resolver):
    manager = FakeManager()
    manager.is_connected.return_value = True
    resolver = O365DeviceCodeCredentialResolver(FakeO365Client(), manager)

    assert await resolver.is_connected("cli", "user@x") is True
    manager.is_connected.assert_awaited_once_with("cli", registered_principal_resolver.user_id)


@pytest.mark.asyncio
async def test_get_auth_url_returns_device_login_url():
    resolver = O365DeviceCodeCredentialResolver(FakeO365Client(), FakeManager())

    assert await resolver.get_auth_url("cli", "user@x") == "https://microsoft.com/devicelogin"
