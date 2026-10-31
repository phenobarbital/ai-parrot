"""IntegrationsService CLI endpoints (FEAT-774 M3)."""

from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, MagicMock

import pytest

from parrot.auth.credentials import AuthRequiredPayload
from parrot.auth.oauth2.models import NotConnected, PulledToken
from parrot.auth.oauth2.service import IntegrationsService


def provider_with_manager() -> MagicMock:
    """Build a registered-provider double with CLI manager operations."""
    provider = MagicMock()
    provider.default_scopes = ["read:jira-work"]
    provider.manager.get_valid_token = AsyncMock()
    provider.manager._publish = AsyncMock()
    return provider


@pytest.mark.asyncio
async def test_whoami_reads_session_identity_and_claims() -> None:
    """Who-am-I preserves server tenancy and reads bearer claims without inventing a tenant."""
    service = IntegrationsService()
    request = {
        "session": {
            "tenant_id": "tenant-1",
            "userinfo": {
                "email": "person@example.com",
                "roles": ["connections:read"],
            },
            "token_claims": {"scope": "openid connections:use"},
        }
    }

    result = await service.whoami("user-1", request)

    assert result.model_dump() == {
        "user_id": "user-1",
        "tenant_id": "tenant-1",
        "canonical_identity": "person@example.com",
        "email": "person@example.com",
        "roles": ["connections:read"],
        "scopes": ["openid", "connections:use"],
    }
    assert (await service.whoami("user-2")).tenant_id is None


@pytest.mark.asyncio
async def test_pull_access_token_never_returns_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    """Token pulls expose only the access-token wire model and emit an audit event."""
    provider = provider_with_manager()
    token = SimpleNamespace(
        access_token="access-secret",
        refresh_token="refresh-secret",
        expires_at=1_800_000_000.0,
        scopes=["read:jira-work"],
        account_id="account-1",
    )
    provider.manager.get_valid_token.return_value = token
    monkeypatch.setattr("parrot.auth.oauth2.service.OAuth2ProviderRegistry.get", lambda _self, _provider_id: provider)
    service = IntegrationsService()
    service._check_pbac = AsyncMock(return_value=True)

    result = await service.pull_access_token("user-1", "jira", request=MagicMock())

    assert isinstance(result, PulledToken)
    assert set(result.model_dump()) == {"provider", "access_token", "expires_at", "scopes", "account_id"}
    assert "refresh_token" not in result.model_dump()
    provider.manager.get_valid_token.assert_awaited_once_with("cli", "user-1")
    publish_args = provider.manager._publish.await_args.args
    assert publish_args[0] == "connection.token_pulled"
    assert publish_args[2] is token
    assert "access-secret" not in repr(publish_args[:2])
    assert "refresh-secret" not in repr(publish_args[:2])


@pytest.mark.asyncio
async def test_pull_token_not_connected_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing provider credential returns an actionable auth-required payload."""
    provider = provider_with_manager()
    provider.manager.get_valid_token.return_value = None
    monkeypatch.setattr("parrot.auth.oauth2.service.OAuth2ProviderRegistry.get", lambda _self, _provider_id: provider)
    service = IntegrationsService()
    service._check_pbac = AsyncMock(return_value=True)
    service.start_connect = AsyncMock(return_value=SimpleNamespace(auth_url="https://idp.example/authorize"))

    with pytest.raises(NotConnected) as caught:
        await service.pull_access_token("user-1", "jira", request=MagicMock())

    assert isinstance(caught.value.payload, AuthRequiredPayload)
    assert caught.value.payload.model_dump() == {
        "provider": "jira",
        "auth_url": "https://idp.example/authorize",
        "scopes": ["read:jira-work"],
        "tool_name": None,
        "message": "not_connected",
        "auth_kind": "oauth2",
        "user_code": None,
        "verification_uri": None,
        "expires_in": None,
    }
    service.start_connect.assert_awaited_once()
    provider.manager._publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_pull_token_pbac_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    """PBAC denial fails closed before credential access or audit publication."""
    provider = provider_with_manager()
    monkeypatch.setattr("parrot.auth.oauth2.service.OAuth2ProviderRegistry.get", lambda _self, _provider_id: provider)
    service = IntegrationsService()
    service._check_pbac = AsyncMock(return_value=False)

    with pytest.raises(PermissionError, match="Not permitted"):
        await service.pull_access_token("user-1", "jira", request=MagicMock())

    service._check_pbac.assert_awaited_once_with(
        ANY,
        "integration:use",
        "jira",
        ["read:jira-work"],
    )
    provider.manager.get_valid_token.assert_not_awaited()
    provider.manager._publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_complete_connect_state_mismatch_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Paste completion consumes only a nonce minted for the authenticated user."""
    provider = provider_with_manager()
    provider.manager._nonce_key.return_value = "oauth:nonce"
    provider.manager.redis.get = AsyncMock(return_value='{"nav_user_id": "another-user"}')
    provider.manager.handle_callback = AsyncMock(
        return_value=(SimpleNamespace(), {"canonical_identity": "person@example.com"})
    )
    monkeypatch.setattr("parrot.auth.oauth2.service.OAuth2ProviderRegistry.get", lambda _self, _provider_id: provider)
    service = IntegrationsService()
    service._check_pbac = AsyncMock(return_value=True)
    service.persist_credential = AsyncMock()
    descriptor = MagicMock()
    service.status = AsyncMock(return_value=descriptor)

    with pytest.raises(ValueError, match="Invalid or expired state nonce"):
        await service.complete_connect("user-1", "jira", code="code", state="state", channel="cli")
    provider.manager.handle_callback.assert_not_awaited()

    provider.manager.redis.get.return_value = None
    with pytest.raises(ValueError, match="Invalid or expired state nonce"):
        await service.complete_connect("user-1", "jira", code="code", state="state", channel="cli")
    provider.manager.handle_callback.assert_not_awaited()

    provider.manager.redis.get.return_value = b'{"nav_user_id": "user-1"}'
    result = await service.complete_connect(
        "user-1",
        "jira",
        code="code",
        state="state",
        channel="cli",
        request="request",
    )

    assert result is descriptor
    provider.manager.handle_callback.assert_awaited_once_with("code", "state")
    service.persist_credential.assert_awaited_once_with(
        "user-1",
        "jira",
        provider.manager.handle_callback.return_value[0],
        channel="cli",
        canonical_identity="person@example.com",
    )
    service.status.assert_awaited_once_with("user-1", "jira", "request")


@pytest.mark.asyncio
async def test_complete_connect_denied_without_pbac(monkeypatch: pytest.MonkeyPatch) -> None:
    """Paste completion checks PBAC integration:connect before touching the nonce (fail closed)."""
    provider = provider_with_manager()
    provider.manager.redis.get = AsyncMock(return_value=b'{"nav_user_id": "user-1"}')
    provider.manager.handle_callback = AsyncMock()
    monkeypatch.setattr("parrot.auth.oauth2.service.OAuth2ProviderRegistry.get", lambda _self, _provider_id: provider)
    service = IntegrationsService()
    service._check_pbac = AsyncMock(return_value=False)

    with pytest.raises(PermissionError, match="Not permitted to connect"):
        await service.complete_connect("user-1", "jira", code="code", state="state", channel="cli", request="r")

    service._check_pbac.assert_awaited_once_with("r", "integration:connect", "jira", ANY)
    provider.manager.redis.get.assert_not_awaited()
    provider.manager.handle_callback.assert_not_awaited()
