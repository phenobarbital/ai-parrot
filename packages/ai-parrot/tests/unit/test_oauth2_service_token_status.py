"""Unit tests for ``IntegrationsService._token_status`` (FEAT-735 / TASK-4670).

The integrations badge used to be computed from the Session Vault — the one
copy of the Jira credential that a refresh never updated. FEAT-735 moved the
Jira probe onto the Identity Vault, its durable owner, and left every other
provider on the vault. These tests pin both halves of that branch, and the
fail-open contract that must survive it: a store outage reports ``connected``,
never a spurious re-connect prompt.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.auth.oauth2.service import IntegrationsService


class _FakeIdentityStore:
    """IdentityStore double: one row, and a controllable decrypt outcome."""

    def __init__(self, identity: Any = "identity-row", decrypt_error: Optional[Exception] = None) -> None:
        self._identity = identity
        self._decrypt_error = decrypt_error
        self.get_calls: list[tuple] = []

    async def get_by_provider(self, user_id: Any, provider: str):
        self.get_calls.append((user_id, provider))
        return self._identity

    def decrypt_credential(self, identity: Any):
        """Synchronous, exactly like the real store."""
        if self._decrypt_error is not None:
            raise self._decrypt_error
        return SimpleNamespace(access_token="at")


def _service(identity_store: Any = None, vault_sync: Any = None) -> IntegrationsService:
    """A service with both backends pre-injected, so no app/pool is needed."""
    service = IntegrationsService()
    service._identity_store_instance = identity_store
    service._vault_token_sync = vault_sync
    return service


def _request() -> Any:
    """A request whose ``.app`` carries an authdb pool."""
    return SimpleNamespace(app={"authdb": object(), "redis": None})


def _vault(status: str) -> MagicMock:
    sync = MagicMock()
    sync.read_tokens_result = AsyncMock(return_value=SimpleNamespace(status=status))
    return sync


class TestJiraReadsTheOwner:
    @pytest.mark.asyncio
    async def test_status_connected_from_owner(self) -> None:
        """AC-1, AC-2 — an openable identity row is ``connected``; no vault read."""
        store = _FakeIdentityStore()
        vault = _vault("missing")  # would say needs_reconnect if consulted
        service = _service(identity_store=store, vault_sync=vault)

        status = await service._token_status("42", "jira", _request())

        assert status == "connected"
        assert store.get_calls == [("42", "jira")]
        vault.read_tokens_result.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_status_needs_reconnect_on_credential_error(self) -> None:
        """AC-3 — the owner's equivalent of the vault's ``unreadable``."""
        from navigator_auth.identity.store import IdentityCredentialError

        store = _FakeIdentityStore(decrypt_error=IdentityCredentialError("jira", "access_token", "sealed token will not open"))
        service = _service(identity_store=store, vault_sync=_vault("ok"))

        assert await service._token_status("42", "jira", _request()) == "needs_reconnect"

    @pytest.mark.asyncio
    async def test_status_needs_reconnect_without_row(self) -> None:
        """AC-3 — never linked, or the row was deleted."""
        service = _service(identity_store=_FakeIdentityStore(identity=None), vault_sync=_vault("ok"))

        assert await service._token_status("42", "jira", _request()) == "needs_reconnect"

    @pytest.mark.asyncio
    async def test_status_fails_open_when_store_raises(self) -> None:
        """AC-4 — an outage must never hide a working integration."""
        store = _FakeIdentityStore(decrypt_error=RuntimeError("postgres is down"))
        service = _service(identity_store=store, vault_sync=_vault("ok"))

        assert await service._token_status("42", "jira", _request()) == "connected"

    @pytest.mark.asyncio
    async def test_status_fails_open_without_authdb(self) -> None:
        """AC-4 — no pool to probe with is not evidence of a broken grant."""
        service = _service(identity_store=None, vault_sync=_vault("ok"))
        request = SimpleNamespace(app={})

        assert await service._token_status("42", "jira", request) == "connected"


class TestOtherProvidersKeepTheVault:
    @pytest.mark.asyncio
    async def test_non_jira_provider_still_uses_vault(self) -> None:
        """AC-5 — fireflies and friends are untouched by FEAT-735."""
        store = _FakeIdentityStore()
        vault = _vault("ok")
        service = _service(identity_store=store, vault_sync=vault)

        status = await service._token_status("42", "fireflies", _request())

        assert status == "connected"
        vault.read_tokens_result.assert_awaited_once_with("42", "fireflies")
        assert store.get_calls == []

    @pytest.mark.asyncio
    async def test_non_jira_unreadable_still_needs_reconnect(self) -> None:
        """AC-5, AC-6 — the vault branch keeps its exact vocabulary."""
        vault = _vault("unreadable")
        service = _service(identity_store=_FakeIdentityStore(), vault_sync=vault)

        assert await service._token_status("42", "fireflies", _request()) == "needs_reconnect"
