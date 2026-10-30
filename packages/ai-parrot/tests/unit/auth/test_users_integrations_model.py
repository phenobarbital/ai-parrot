"""Tests for channel-neutral OAuth2 integration persistence models."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from parrot.auth.oauth2.models import IntegrationDescriptor, UsersIntegrationRow
from parrot.auth.oauth2.persistence import list_users_integrations


CONNECTED_AT = datetime(2026, 10, 30, tzinfo=timezone.utc)


def _integration_document(provider: str, **overrides: object) -> dict[str, object]:
    """Build a valid stored integration document for a provider."""
    document: dict[str, object] = {
        "user_id": "1042",
        "provider": provider,
        "account_id": f"{provider}-account",
        "display_name": provider.title(),
        "scopes": [],
        "connected_at": CONNECTED_AT,
    }
    document.update(overrides)
    return document


def test_legacy_channel_folded_into_channels() -> None:
    """Legacy persisted channel values become a single-item channels list."""
    row = UsersIntegrationRow.model_validate(
        _integration_document("jira", channel="telegram")
    )

    assert row.channels == ["telegram"]
    assert row.updated_at is None


def test_integration_descriptor_has_channel_neutral_fields() -> None:
    """Descriptor exposes new connection state but hides legacy enablement."""
    descriptor = IntegrationDescriptor(
        provider="jira",
        display_name="Jira",
        enabled_on_agent=True,
        channels=["web", "telegram"],
        scopes_granted=["read:jira-work"],
        expires_at=1_793_232_000.0,
        updated_at=CONNECTED_AT,
    )

    assert descriptor.channels == ["web", "telegram"]
    assert descriptor.scopes_granted == ["read:jira-work"]
    assert descriptor.model_dump()["updated_at"] == CONNECTED_AT
    assert "enabled_on_agent" not in descriptor.model_dump()


@pytest.mark.asyncio
async def test_list_users_integrations_returns_valid_rows_for_principal() -> None:
    """List reads every principal row and isolates malformed stored documents."""
    db = AsyncMock()
    db.read.return_value = [
        {"_id": "jira", **_integration_document("jira", channel="web")},
        {"_id": "slack", **_integration_document("slack", channels=["telegram"])},
        {"_id": "invalid", "user_id": "1042", "provider": "bad"},
    ]
    context_manager = AsyncMock()
    context_manager.__aenter__.return_value = db
    context_manager.__aexit__.return_value = False

    with patch("parrot.auth.oauth2.persistence.DocumentDb", return_value=context_manager):
        rows = await list_users_integrations("1042")

    assert [(row.provider, row.channels) for row in rows] == [
        ("jira", ["web"]),
        ("slack", ["telegram"]),
    ]
    db.read.assert_awaited_once_with("users_integrations", {"user_id": "1042"})
