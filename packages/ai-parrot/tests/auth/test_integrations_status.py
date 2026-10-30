"""FEAT-099 (TASK-082): integration status reflects whether stored tokens are usable.

Two credential owners are covered (FEAT-780):

* Session Vault — every provider not in ``_IDENTITY_OWNED_PROVIDERS``, probed
  through ``VaultTokenSync.read_tokens_result`` (exercised here with ``o365``).
* Identity Vault — ``jira`` since TASK-4670, probed through navigator-auth's
  ``IdentityStore`` (``get_by_provider`` + ``decrypt_credential``).
"""
from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from navigator_auth.identity.store import IdentityCredentialError

from parrot.auth.oauth2.models import IntegrationDescriptor
from parrot.auth.oauth2.service import _IDENTITY_OWNED_PROVIDERS, IntegrationsService


def make_provider(provider_id: str, display_name: str) -> SimpleNamespace:
    return SimpleNamespace(
        provider_id=provider_id,
        display_name=display_name,
        icon=None,
        default_scopes=["read"],
    )


SESSION_PROVIDER = make_provider("o365", "Office 365")
IDENTITY_PROVIDER = make_provider("jira", "Jira")
ROW = SimpleNamespace(account_id="acc-1", display_name="Account", email="a@b.c", connected_at=None)


class FakeRead:
    def __init__(self, status):
        self.status = status
        self.tokens = {"access_token": "tok"} if status == "ok" else None


class FakeSync:
    def __init__(self, status="ok", error=None):
        self._status = status
        self._error = error
        self.calls = 0

    async def read_tokens_result(self, user_id, provider):
        self.calls += 1
        if self._error:
            raise self._error
        return FakeRead(self._status)


class FakeIdentityStore:
    """Stand-in for navigator-auth's ``IdentityStore`` (async lookup, sync decrypt)."""

    def __init__(self, identity=None, lookup_error=None, decrypt_error=None):
        self._identity = identity
        self._lookup_error = lookup_error
        self._decrypt_error = decrypt_error
        self.lookups = 0
        self.decrypts = 0

    async def get_by_provider(self, user_id, provider_id):
        self.lookups += 1
        if self._lookup_error:
            raise self._lookup_error
        return self._identity

    def decrypt_credential(self, identity):
        self.decrypts += 1
        if self._decrypt_error:
            raise self._decrypt_error
        return {"access_token": "tok"}


@contextmanager
def patch_registry(provider):
    """Patch the provider registry and the agent-toolkit lookup for one provider."""
    with patch("parrot.auth.oauth2.service.OAuth2ProviderRegistry") as registry, patch(
        "parrot.auth.oauth2.service.list_user_agent_toolkits",
        new=AsyncMock(return_value=[]),
    ):
        registry.return_value.all.return_value = [provider]
        yield


@pytest.fixture
def session_registry():
    with patch_registry(SESSION_PROVIDER):
        yield


@pytest.fixture
def identity_registry():
    with patch_registry(IDENTITY_PROVIDER):
        yield


async def list_one(
    service: IntegrationsService, row: SimpleNamespace | None = ROW, request: object | None = None
) -> IntegrationDescriptor:
    if request is None:
        request = SimpleNamespace(app={})
    with patch(
        "parrot.auth.oauth2.service.get_users_integration", new=AsyncMock(return_value=row)
    ), patch.object(IntegrationsService, "_check_pbac", new=AsyncMock(return_value=True)):
        items = await service.list_for_user("user-1", "agent-1", request=request)
    return items[0]


def test_provider_ownership_assumptions():
    assert SESSION_PROVIDER.provider_id not in _IDENTITY_OWNED_PROVIDERS
    assert IDENTITY_PROVIDER.provider_id in _IDENTITY_OWNED_PROVIDERS


@pytest.mark.asyncio
class TestSessionVaultStatus:
    async def test_readable_tokens_are_connected(self, session_registry):
        sync = FakeSync("ok")
        item = await list_one(IntegrationsService(vault_token_sync=sync))
        assert item.status == "connected" and item.connected is True
        assert item.account_id == "acc-1"
        assert sync.calls == 1

    @pytest.mark.parametrize("status", ["unreadable", "missing"])
    async def test_unusable_tokens_need_reconnect(self, session_registry, status):
        sync = FakeSync(status)
        item = await list_one(IntegrationsService(vault_token_sync=sync))
        assert item.status == "needs_reconnect" and item.connected is False
        # metadata is still shown so the UI can render the account row
        assert item.account_id == "acc-1"
        assert sync.calls == 1

    async def test_no_row_is_disconnected(self, session_registry):
        sync = FakeSync("ok")
        item = await list_one(IntegrationsService(vault_token_sync=sync), row=None)
        assert item.status == "disconnected" and item.connected is False
        assert sync.calls == 0  # no vault probe without a credential row

    async def test_vault_outage_does_not_hide_integrations(self, session_registry):
        sync = FakeSync(status="unavailable")
        item = await list_one(IntegrationsService(vault_token_sync=sync))
        assert item.status == "connected"
        assert sync.calls == 1

    async def test_probe_failure_is_swallowed(self, session_registry):
        sync = FakeSync(error=RuntimeError("redis down"))
        item = await list_one(IntegrationsService(vault_token_sync=sync))
        assert item.status == "connected"
        assert sync.calls == 1

    async def test_probe_skipped_without_app(self, session_registry):
        service = IntegrationsService()
        with patch(
            "parrot.auth.oauth2.service.get_users_integration", new=AsyncMock(return_value=ROW)
        ), patch.object(IntegrationsService, "_check_pbac", new=AsyncMock(return_value=True)):
            items = await service.list_for_user("user-1", "agent-1", request=None)
        assert items[0].status == "connected"


@pytest.mark.asyncio
class TestIdentityVaultStatus:
    @staticmethod
    def service_with(store):
        sync = FakeSync("missing")  # would say needs_reconnect if it were (wrongly) consulted
        service = IntegrationsService(vault_token_sync=sync)
        service._identity_store_instance = store
        return service, sync

    async def test_readable_credential_is_connected(self, identity_registry):
        store = FakeIdentityStore(identity=object())
        service, sync = self.service_with(store)
        item = await list_one(service)
        assert item.status == "connected" and item.connected is True
        assert store.lookups == 1 and store.decrypts == 1
        assert sync.calls == 0  # jira never touches the Session Vault

    async def test_no_identity_row_needs_reconnect(self, identity_registry):
        store = FakeIdentityStore(identity=None)
        service, sync = self.service_with(store)
        item = await list_one(service)
        assert item.status == "needs_reconnect" and item.connected is False
        assert item.account_id == "acc-1"
        assert store.decrypts == 0
        assert sync.calls == 0

    async def test_unreadable_credential_needs_reconnect(self, identity_registry):
        store = FakeIdentityStore(identity=object(), decrypt_error=IdentityCredentialError("jira", "access_token", "InvalidTag"))
        service, sync = self.service_with(store)
        item = await list_one(service)
        assert item.status == "needs_reconnect" and item.connected is False
        assert store.decrypts == 1
        assert sync.calls == 0

    async def test_probe_error_fails_open(self, identity_registry):
        store = FakeIdentityStore(lookup_error=RuntimeError("authdb down"))
        service, sync = self.service_with(store)
        item = await list_one(service)
        assert item.status == "connected"
        assert sync.calls == 0

    async def test_no_store_fails_open(self, identity_registry):
        sync = FakeSync("missing")
        item = await list_one(IntegrationsService(vault_token_sync=sync))  # app={} → no authdb → no store
        assert item.status == "connected"
        assert sync.calls == 0


class TestDescriptorContract:
    def test_status_and_connected_stay_in_sync(self):
        assert IntegrationDescriptor(provider="p", display_name="P", connected=True).status == "connected"
        assert IntegrationDescriptor(provider="p", display_name="P").status == "disconnected"
        needs = IntegrationDescriptor(provider="p", display_name="P", status="needs_reconnect")
        assert needs.connected is False
        assert needs.model_dump(mode="json")["status"] == "needs_reconnect"

    def test_invalid_status_rejected(self):
        with pytest.raises(Exception):
            IntegrationDescriptor(provider="p", display_name="P", status="broken")
