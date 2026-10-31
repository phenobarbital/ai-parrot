"""One O365 record for device code and 3LO (FEAT-777 AC-8)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.auth.o365_oauth import O365OAuthManager
from parrot.auth.oauth2.registry import OAuth2ProviderRegistry
from parrot.auth.oauth2.service import IntegrationsService
from parrot.auth.principal import Principal

from .test_connections_isolation_matrix import FakeCredentialStore, MemRedis

pytestmark = pytest.mark.asyncio


class _AllowAuthorizer:
    """Allow provider listing for the principal under test."""

    async def authorize(self, principal: Principal, action: str, provider_id: str | None, scopes: list[str]) -> bool:
        """Allow the explicitly scoped integration operation."""
        del principal, action, provider_id, scopes
        return True


class _Provider:
    """Minimal registered provider exposing the real O365 manager."""

    provider_id = "o365"
    display_name = "Microsoft 365"
    icon = "mdi:microsoft"
    default_scopes = ["User.Read"]
    manager: O365OAuthManager


async def test_e2e_o365_device_and_web_share_record(monkeypatch: pytest.MonkeyPatch) -> None:
    """Device-code storage is listed once and a later 3LO callback replaces its origin."""
    OAuth2ProviderRegistry._reset()
    store = FakeCredentialStore()
    redis = MemRedis()
    manager = O365OAuthManager(
        "client",
        "secret",
        "https://app.example.com/oauth/callback",
        redis_client=redis,
        credential_store=store,
    )
    manager._discover_identity = AsyncMock(
        side_effect=[
            {"id": "account-device", "displayName": "Device User", "userPrincipalName": "device@example.com"},
            {"id": "account-web", "displayName": "Web User", "userPrincipalName": "web@example.com"},
        ]
    )
    manager._exchange_code = AsyncMock(
        return_value={
            "access_token": "web-access",
            "refresh_token": "web-refresh",
            "expires_in": 3600,
            "scope": "User.Read offline_access",
        }
    )
    provider = _Provider()
    provider.manager = manager
    OAuth2ProviderRegistry().register(provider)
    principal = Principal(user_id="1042", channel="cli", channel_user_id="device@example.com")
    rows = {}

    async def persist_row(
        service: IntegrationsService,
        user_id: str,
        provider_id: str,
        token_set: object,
        *,
        channel: str,
        canonical_identity=None,
    ):
        """Persist the same descriptor metadata consumed by list_for_principal."""
        del service, canonical_identity
        from parrot.auth.oauth2.models import UsersIntegrationRow

        row = UsersIntegrationRow(
            user_id=user_id,
            provider=provider_id,
            account_id=token_set.account_id,
            display_name=token_set.display_name,
            email=token_set.email,
            scopes=token_set.scopes,
            scopes_granted=token_set.scopes,
            channels=[channel],
            connected_at=datetime.now(tz=timezone.utc),
            grant_origin=token_set.grant_origin,
        )
        rows[(user_id, provider_id)] = row
        return row

    async def list_rows(user_id: str):
        """Return the principal's one shared O365 row."""
        return [row for (row_user, _), row in rows.items() if row_user == user_id]

    monkeypatch.setattr(IntegrationsService, "persist_credential", persist_row)
    monkeypatch.setattr("parrot.auth.oauth2.service.list_users_integrations", list_rows)
    monkeypatch.setattr(O365OAuthManager, "_publish", AsyncMock())
    with patch("parrot.services.vault_token_sync.VaultTokenSync", MagicMock(side_effect=AssertionError)):
        device = await manager.store_device_grant(
            principal,
            {
                "access_token": "device-access",
                "refresh_token": "device-refresh",
                "expires_in": 3600,
                "scope": "User.Read offline_access",
            },
            channel="cli",
        )
        assert device.grant_origin == "device_code"
        listed_device = await IntegrationsService(authorizer=_AllowAuthorizer()).list_for_principal(
            "1042", principal=principal
        )
        assert listed_device[0].status == "connected"
        assert listed_device[0].grant_origin == "device_code"

        _, state = await manager.create_authorization_url("web", "1042", principal=principal)
        web_token, _ = await manager.handle_callback("code-1", state)
        await IntegrationsService().persist_credential("1042", "o365", web_token, channel="web")
        assert web_token.grant_origin == "authorization_code"

    assert store.rows[("1042", "o365")]["access_token"] == "web-access"
    listed_web = await IntegrationsService(authorizer=_AllowAuthorizer()).list_for_principal("1042", principal=principal)
    assert listed_web[0].status == "connected"
    assert listed_web[0].grant_origin == "authorization_code"
    assert listed_web[0].account_id == "account-web"
