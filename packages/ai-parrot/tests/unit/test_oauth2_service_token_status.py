"""Token status reads the durable credential owner for every provider."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.auth.oauth2.registry import OAuth2ProviderRegistry
from parrot.auth.oauth2.service import IntegrationsService


class _FakeIdentityStore:
    """IdentityStore double with controllable lookup and decrypt outcomes."""

    def __init__(
        self,
        identity: Any = "identity-row",
        decrypt_error: Optional[Exception] = None,
        lookup_error: Optional[Exception] = None,
    ) -> None:
        self._identity = identity
        self._decrypt_error = decrypt_error
        self._lookup_error = lookup_error
        self.get_calls: list[tuple[Any, str]] = []

    async def get_by_provider(self, user_id: Any, provider: str) -> Any:
        """Return the configured identity row."""
        self.get_calls.append((user_id, provider))
        if self._lookup_error is not None:
            raise self._lookup_error
        return self._identity

    def decrypt_credential(self, identity: Any) -> SimpleNamespace:
        """Open the configured credential synchronously like IdentityStore."""
        if self._decrypt_error is not None:
            raise self._decrypt_error
        return SimpleNamespace(access_token="token")


@pytest.fixture(autouse=True)
def reset_registry() -> None:
    """Isolate the singleton provider registry."""
    OAuth2ProviderRegistry._reset()
    yield
    OAuth2ProviderRegistry._reset()


@pytest.mark.parametrize("provider_id", ["jira", "o365", "fireflies"])
@pytest.mark.asyncio
async def test_every_provider_reads_identity_vault(provider_id: str) -> None:
    """No provider is gated onto the obsolete Session Vault path."""
    store = _FakeIdentityStore()
    service = IntegrationsService()
    service._identity_store_instance = store

    status = await service._token_status("42", provider_id, SimpleNamespace(app={"authdb": object()}))

    assert status == "connected"
    assert store.get_calls == [("42", provider_id)]


@pytest.mark.asyncio
async def test_identity_vault_missing_row_needs_reconnect() -> None:
    """A provably absent durable credential is not connected."""
    service = IntegrationsService()
    service._identity_store_instance = _FakeIdentityStore(identity=None)

    assert await service._token_status("42", "o365", SimpleNamespace(app={"authdb": object()})) == "needs_reconnect"


@pytest.mark.asyncio
async def test_identity_vault_credential_error_needs_reconnect() -> None:
    """An unreadable durable credential requires reconnection."""
    from navigator_auth.identity.store import IdentityCredentialError

    service = IntegrationsService()
    service._identity_store_instance = _FakeIdentityStore(
        decrypt_error=IdentityCredentialError("o365", "access_token", "sealed value will not open")
    )

    assert await service._token_status("42", "o365", SimpleNamespace(app={"authdb": object()})) == "needs_reconnect"


@pytest.mark.asyncio
async def test_identity_vault_operational_error_fails_open() -> None:
    """An owner outage does not hide a potentially working connection."""
    service = IntegrationsService()
    service._identity_store_instance = _FakeIdentityStore(lookup_error=RuntimeError("database down"))

    assert await service._token_status("42", "jira", SimpleNamespace(app={"authdb": object()})) == "connected"


@pytest.mark.asyncio
async def test_manager_is_fallback_when_server_store_unavailable() -> None:
    """Core-only deployments probe the provider manager with the principal key."""
    provider = MagicMock()
    provider.provider_id = "jira"
    provider.manager.is_connected = AsyncMock(return_value=False)
    OAuth2ProviderRegistry().register(provider)

    status = await IntegrationsService()._token_status("42", "jira", SimpleNamespace(app={}))

    assert status == "needs_reconnect"
    provider.manager.is_connected.assert_awaited_once_with("web", "42")


@pytest.mark.asyncio
async def test_manager_fallback_error_fails_open() -> None:
    """A manager probe failure is not evidence that the grant is broken."""
    provider = MagicMock()
    provider.provider_id = "jira"
    provider.manager.is_connected = AsyncMock(side_effect=RuntimeError("redis down"))
    OAuth2ProviderRegistry().register(provider)

    assert await IntegrationsService()._token_status("42", "jira", SimpleNamespace(app={})) == "connected"
