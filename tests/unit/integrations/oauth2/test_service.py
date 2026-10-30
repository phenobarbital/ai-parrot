"""Unit tests for the principal-scoped OAuth2 integrations service."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.auth.oauth2.models import UsersIntegrationRow
from parrot.auth.oauth2.registry import OAuth2ProviderRegistry
from parrot.auth.oauth2.service import IntegrationsService
from parrot.auth.principal import Principal


@pytest.fixture(autouse=True)
def reset_registry() -> None:
    """Ensure every test has an isolated provider registry."""
    OAuth2ProviderRegistry._reset()
    yield
    OAuth2ProviderRegistry._reset()


@pytest.fixture
def provider() -> MagicMock:
    """Register a provider with async manager operations."""
    item = MagicMock()
    item.provider_id = "jira"
    item.display_name = "Jira"
    item.icon = "mdi:jira"
    item.default_scopes = ["read:jira-work", "offline_access"]
    item.manager.create_authorization_url = AsyncMock(return_value=("https://idp/authorize", "nonce"))
    item.manager.is_connected = AsyncMock(return_value=True)
    item.manager.revoke = AsyncMock()
    OAuth2ProviderRegistry().register(item)
    return item


def allow_request(allowed: bool = True) -> SimpleNamespace:
    """Build a request carrying a controllable PBAC evaluator."""
    abac = SimpleNamespace(is_allowed=AsyncMock(return_value=allowed))
    return SimpleNamespace(app={"abac": abac})


def integration_row(
    *,
    channels: list[str] | None = None,
    account_id: str = "account-1",
    connected_at: datetime | None = None,
    updated_at: datetime | None = None,
) -> UsersIntegrationRow:
    """Build a durable integration row for descriptor and reconnect tests."""
    connected = connected_at or datetime(2026, 1, 1, tzinfo=timezone.utc)
    return UsersIntegrationRow(
        user_id="42",
        provider="jira",
        channels=channels or ["web"],
        account_id=account_id,
        display_name="Test User",
        email="test@example.com",
        scopes=["read:jira-work"],
        scopes_granted=["read:jira-work"],
        connected_at=connected,
        updated_at=updated_at or connected,
    )


def token_set(account_id: str = "account-1") -> SimpleNamespace:
    """Build a provider-neutral token-set double."""
    return SimpleNamespace(
        account_id=account_id,
        display_name="Test User",
        email="test@example.com",
        scopes=["read:jira-work"],
        scopes_granted=["read:jira-work"],
        expires_at=1_800_000_000.0,
        cloud_id="cloud-1",
        site_url="https://example.atlassian.net",
    )


@pytest.mark.asyncio
async def test_list_for_user_is_principal_alias(provider: MagicMock) -> None:
    """The legacy agent route ignores agent identity and returns principal rows."""
    row = integration_row(channels=["telegram"])
    request = allow_request()
    with (
        patch("parrot.auth.oauth2.service.list_users_integrations", AsyncMock(return_value=[row])),
        patch.object(IntegrationsService, "_token_status", AsyncMock(return_value="connected")),
    ):
        descriptors = await IntegrationsService().list_for_user("42", "agent-ignored", request=request)

    assert descriptors[0].provider == "jira"
    assert descriptors[0].channels == ["telegram"]
    assert descriptors[0].updated_at == row.updated_at


@pytest.mark.asyncio
async def test_list_for_principal_fails_closed_without_pdp(provider: MagicMock) -> None:
    """A missing PDP returns no connection metadata."""
    with patch("parrot.auth.oauth2.service.list_users_integrations", AsyncMock()) as list_rows:
        assert await IntegrationsService().list_for_principal("42", request=None) == []
    list_rows.assert_not_awaited()


@pytest.mark.asyncio
async def test_service_pbac_on_connect_and_disconnect(provider: MagicMock) -> None:
    """Connect and disconnect deny before manager state or persistence changes."""
    service = IntegrationsService()
    denied = allow_request(False)
    principal = Principal(user_id="42", channel="telegram", channel_user_id="tg-7")

    with pytest.raises(PermissionError):
        await service.start_connect(
            "42",
            "jira",
            channel="telegram",
            principal=principal,
            scopes=["read:jira-work"],
            request=denied,
        )
    with patch("parrot.auth.oauth2.service.delete_users_integration", AsyncMock()) as delete_row:
        with pytest.raises(PermissionError):
            await service.disconnect("42", "jira", request=denied)
    provider.manager.create_authorization_url.assert_not_awaited()
    provider.manager.revoke.assert_not_awaited()
    delete_row.assert_not_awaited()

    contexts = [call.args[1] for call in denied.app["abac"].is_allowed.await_args_list]
    assert contexts == [
        {"action": "integration:connect", "provider": "jira", "scopes": ["read:jira-work"]},
        {
            "action": "integration:disconnect",
            "provider": "jira",
            "scopes": provider.default_scopes,
        },
    ]


@pytest.mark.asyncio
async def test_start_connect_passes_principal_and_channel(provider: MagicMock) -> None:
    """A non-web connection forwards the bound principal and signed extra state."""
    principal = Principal(user_id="42", channel="telegram", channel_user_id="tg-7")
    response = await IntegrationsService().start_connect(
        "42",
        "jira",
        channel="telegram",
        principal=principal,
        request=allow_request(),
        extra_state={"chat_id": "chat-9"},
    )

    assert response.state == "nonce"
    provider.manager.create_authorization_url.assert_awaited_once_with(
        channel="telegram",
        user_id="42",
        extra_state={
            "channel": "telegram",
            "provider_id": "jira",
            "return_origin": None,
            "chat_id": "chat-9",
        },
        principal=principal,
    )


@pytest.mark.asyncio
async def test_web_connect_requires_allowed_origin_after_pbac(provider: MagicMock) -> None:
    """Web origin validation runs after authorization and before nonce creation."""
    with patch("parrot.auth.oauth2.service._get_allowed_origins", return_value=["https://app.example.com"]):
        with pytest.raises(ValueError, match="not in the list"):
            await IntegrationsService().start_connect(
                "42",
                "jira",
                "https://evil.example",
                request=allow_request(),
            )
    provider.manager.create_authorization_url.assert_not_awaited()


@pytest.mark.asyncio
async def test_service_list_for_principal_cross_channel(provider: MagicMock) -> None:
    """A Telegram metadata row is returned through the principal listing."""
    stored: list[UsersIntegrationRow] = []

    async def save(row: UsersIntegrationRow) -> None:
        stored[:] = [row]

    with (
        patch("parrot.auth.oauth2.service.get_users_integration", AsyncMock(return_value=None)),
        patch("parrot.auth.oauth2.service.upsert_users_integration", side_effect=save),
    ):
        await IntegrationsService().persist_credential("42", "jira", token_set(), channel="telegram")

    with (
        patch("parrot.auth.oauth2.service.list_users_integrations", AsyncMock(return_value=stored)),
        patch.object(IntegrationsService, "_token_status", AsyncMock(return_value="connected")),
    ):
        descriptors = await IntegrationsService().list_for_principal("42", request=allow_request())

    assert descriptors[0].channels == ["telegram"]
    assert descriptors[0].status == "connected"


@pytest.mark.asyncio
async def test_descriptor_updated_at_bumps_on_reconnect() -> None:
    """Same-account reconnect preserves connected_at and advances updated_at."""
    first_time = datetime.now(tz=timezone.utc) - timedelta(minutes=5)
    existing = integration_row(connected_at=first_time, updated_at=first_time)
    with (
        patch("parrot.auth.oauth2.service.get_users_integration", AsyncMock(return_value=existing)),
        patch("parrot.auth.oauth2.service.upsert_users_integration", AsyncMock()),
    ):
        row = await IntegrationsService().persist_credential(
            "42",
            "jira",
            token_set(),
            channel="telegram",
            canonical_identity="person@example.com",
        )

    assert row.connected_at == first_time
    assert row.updated_at is not None and row.updated_at > first_time
    assert row.channels == ["web", "telegram"]
    assert row.canonical_identity == "person@example.com"


@pytest.mark.asyncio
async def test_reconnect_with_different_account_resets_connected_at() -> None:
    """Replace-on-reconnect starts a new connection timestamp for a new account."""
    existing = integration_row(account_id="old-account")
    with (
        patch("parrot.auth.oauth2.service.get_users_integration", AsyncMock(return_value=existing)),
        patch("parrot.auth.oauth2.service.upsert_users_integration", AsyncMock()),
    ):
        row = await IntegrationsService().persist_credential(
            "42", "jira", token_set("new-account"), channel="web"
        )

    assert row.connected_at > existing.connected_at
    assert row.account_id == "new-account"


def test_confirm_enable_removed_enable_route_noop() -> None:
    """The per-agent mutation API is a hard cut from the service."""
    assert not hasattr(IntegrationsService, "confirm_enable")
