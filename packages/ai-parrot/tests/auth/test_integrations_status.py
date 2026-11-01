"""Integration descriptors expose durable-owner status and principal metadata."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from parrot.auth.oauth2.models import IntegrationDescriptor, UsersIntegrationRow
from parrot.auth.oauth2.service import IntegrationsService

PROVIDER = SimpleNamespace(
    provider_id="o365",
    display_name="Office 365",
    icon=None,
    default_scopes=["read"],
)


def request() -> SimpleNamespace:
    """Return a request with an allow-all PBAC evaluator."""
    return SimpleNamespace(app={"abac": SimpleNamespace(is_allowed=AsyncMock(return_value=True))})


def row() -> UsersIntegrationRow:
    """Return one channel-neutral persisted connection."""
    now = datetime.now(tz=timezone.utc)
    return UsersIntegrationRow(
        user_id="user-1",
        provider="o365",
        channels=["msteams", "web"],
        account_id="account-1",
        display_name="Account",
        email="a@example.com",
        scopes=["read"],
        scopes_granted=["read"],
        expires_at=1_800_000_000.0,
        connected_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_connected_descriptor_contains_channel_neutral_fields() -> None:
    """Listing maps the durable row's cross-channel metadata into the descriptor."""
    persisted = row()
    with (
        patch("parrot.auth.oauth2.service.OAuth2ProviderRegistry") as registry,
        patch("parrot.auth.oauth2.service.list_users_integrations", AsyncMock(return_value=[persisted])),
        patch.object(IntegrationsService, "_token_status", AsyncMock(return_value="connected")),
    ):
        registry.return_value.all.return_value = [PROVIDER]
        items = await IntegrationsService().list_for_principal("user-1", request=request())

    assert items == [
        IntegrationDescriptor(
            provider="o365",
            display_name="Office 365",
            icon=None,
            default_scopes=["read"],
            status="connected",
            account_id="account-1",
            display_account_name="Account",
            email="a@example.com",
            connected_at=persisted.connected_at,
            channels=["msteams", "web"],
            scopes_granted=["read"],
            expires_at=1_800_000_000.0,
            updated_at=persisted.updated_at,
        )
    ]


@pytest.mark.asyncio
async def test_disconnected_descriptor_does_not_probe_owner() -> None:
    """A provider without a metadata row is disconnected without a credential read."""
    with (
        patch("parrot.auth.oauth2.service.OAuth2ProviderRegistry") as registry,
        patch("parrot.auth.oauth2.service.list_users_integrations", AsyncMock(return_value=[])),
        patch.object(IntegrationsService, "_token_status", AsyncMock()) as token_status,
    ):
        registry.return_value.all.return_value = [PROVIDER]
        items = await IntegrationsService().list_for_principal("user-1", request=request())

    assert items[0].status == "disconnected"
    assert items[0].connected is False
    token_status.assert_not_awaited()


@pytest.mark.asyncio
async def test_needs_reconnect_preserves_account_metadata() -> None:
    """An unusable credential still identifies the account to reconnect."""
    persisted = row()
    with (
        patch("parrot.auth.oauth2.service.OAuth2ProviderRegistry") as registry,
        patch("parrot.auth.oauth2.service.list_users_integrations", AsyncMock(return_value=[persisted])),
        patch.object(IntegrationsService, "_token_status", AsyncMock(return_value="needs_reconnect")),
    ):
        registry.return_value.all.return_value = [PROVIDER]
        item = (await IntegrationsService().list_for_principal("user-1", request=request()))[0]

    assert item.status == "needs_reconnect"
    assert item.connected is False
    assert item.account_id == "account-1"


class TestDescriptorContract:
    """Keep the legacy connected flag synchronized with the status field."""

    def test_status_and_connected_stay_in_sync(self) -> None:
        """Explicit status wins and legacy connected remains derivable."""
        assert IntegrationDescriptor(provider="p", display_name="P", connected=True).status == "connected"
        assert IntegrationDescriptor(provider="p", display_name="P").status == "disconnected"
        needs = IntegrationDescriptor(provider="p", display_name="P", status="needs_reconnect")
        assert needs.connected is False
        assert needs.model_dump(mode="json")["status"] == "needs_reconnect"

    def test_invalid_status_rejected(self) -> None:
        """Unknown status values fail model validation."""
        with pytest.raises(Exception):
            IntegrationDescriptor(provider="p", display_name="P", status="broken")
