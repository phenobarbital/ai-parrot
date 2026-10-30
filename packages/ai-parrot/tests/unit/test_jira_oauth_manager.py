"""Tests for Jira's descriptor-backed OAuth manager."""

from __future__ import annotations

import time
from typing import Any, Optional
from unittest.mock import AsyncMock

import pytest
from aiohttp import web

from parrot.auth.jira_oauth import JIRA_DESCRIPTOR, JiraOAuthManager, JiraTokenSet
from parrot.auth.oauth2.descriptor import RefreshPolicy, StandardOAuth2Manager


class _FakeRedis:
    """Small async Redis fake used by the migration test."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.deleted: list[str] = []

    async def get(self, key: str) -> Optional[str]:
        """Return a stored value."""
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: Optional[int] = None) -> bool:
        """Store a value, ignoring TTL in this deterministic fake."""
        del ex
        self.store[key] = value
        return True

    async def delete(self, *keys: str) -> int:
        """Delete keys and record each deletion."""
        for key in keys:
            self.store.pop(key, None)
            self.deleted.append(key)
        return len(keys)

    def lock(self, *args: Any, **kwargs: Any) -> Any:
        """Return an async lock accepted by the standard engine."""
        del args, kwargs
        lock = type("Lock", (), {})()
        lock.acquire = AsyncMock(return_value=True)
        lock.release = AsyncMock(return_value=None)
        return lock


class _CredentialStore:
    """Credential store fake which records the migrated principal payload."""

    def __init__(self) -> None:
        self.saved: list[tuple[str, str, dict[str, Any]]] = []

    async def load(self, user_id: str, provider: str) -> None:
        """No principal credential is initially present."""
        del user_id, provider
        return None

    async def save(
        self,
        user_id: str,
        provider: str,
        payload: dict[str, Any],
        *,
        minted: bool,
        principal: Any,
        state_payload: Optional[dict[str, Any]],
    ) -> None:
        """Record a durable migration write."""
        del minted, principal, state_payload
        self.saved.append((user_id, provider, payload))

    async def delete(self, user_id: str, provider: str) -> None:
        """The migration path does not delete the destination credential."""
        del user_id, provider


def _legacy_token() -> JiraTokenSet:
    """Return a valid legacy Jira token."""
    return JiraTokenSet(
        access_token="access",
        refresh_token="refresh",
        expires_at=time.time() + 3600,
        cloud_id="cloud-1",
        site_url="https://example.atlassian.net",
        account_id="account-1",
        display_name="Jira User",
    )


def test_jira_manager_is_standard_subclass_public_api() -> None:
    """Jira retains its public manager API while using the standard engine."""
    assert issubclass(JiraOAuthManager, StandardOAuth2Manager)
    for method_name in (
        "create_authorization_url",
        "handle_callback",
        "get_valid_token",
        "validate_token",
        "is_connected",
        "revoke",
    ):
        assert callable(getattr(JiraOAuthManager, method_name))


def test_jira_descriptor_refresh_policy() -> None:
    """The descriptor captures Atlassian's rotating 90-day refresh policy."""
    assert JIRA_DESCRIPTOR.pkce == "none"
    assert JIRA_DESCRIPTOR.extra_authorize_params == {"audience": "api.atlassian.com", "prompt": "consent"}
    assert JIRA_DESCRIPTOR.refresh_policy == RefreshPolicy(rotating=True, sliding=True, refresh_lifetime_s=7776000)


def test_jira_setup_preserves_callback_and_manager_slots() -> None:
    """Jira retains its callback route while exposing the standard manager slot."""
    app = web.Application()
    manager = JiraOAuthManager(
        client_id="client",
        client_secret="secret",
        redirect_uri="https://example.test/api/auth/jira/callback",
        app=app,
    )

    manager.setup()

    assert app["jira_oauth_manager"] is manager
    assert app["oauth2_manager_jira"] is manager
    assert any(route.resource.canonical == "/api/auth/jira/callback" for route in app.router.routes())
    manager.setup()


@pytest.mark.asyncio
async def test_jira_legacy_key_dual_read_bound_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """A bound principal migrates one historical Jira key; absent keys stay absent."""
    fake_redis = _FakeRedis()
    credential_store = _CredentialStore()
    manager = JiraOAuthManager(
        client_id="client",
        client_secret="secret",
        redirect_uri="https://example.test/api/auth/jira/callback",
        redis_client=fake_redis,
        credential_store=credential_store,
    )
    fake_redis.store["jira:oauth:telegram:channel-user"] = _legacy_token().model_dump_json()

    async def _missing_generic_legacy(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise KeyError

    monkeypatch.setattr("parrot.auth.oauth2_base.retrieve_vault_credential", _missing_generic_legacy)
    migrated = await manager._read_legacy_token("telegram", "channel-user", "42")

    assert migrated is not None
    assert migrated.cloud_id == "cloud-1"
    assert credential_store.saved == [("42", "jira", migrated.model_dump(mode="json"))]
    assert JiraTokenSet.model_validate_json(fake_redis.store["oauth2:jira:42"]) == migrated
    assert "jira:oauth:telegram:channel-user" in fake_redis.deleted

    fake_redis.store["jira:oauth:telegram:unbound-user"] = _legacy_token().model_dump_json()
    monkeypatch.setattr("parrot.auth.jira_oauth.resolve_principal", AsyncMock(return_value=None))
    assert await manager.validate_token("telegram", "unbound-user") is None
    assert "jira:oauth:telegram:unbound-user" in fake_redis.store
