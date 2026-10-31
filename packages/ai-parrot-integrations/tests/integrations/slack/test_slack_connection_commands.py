"""Slack generic connection commands (FEAT-777 AC-6, AC-14)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.auth.oauth2.registry import OAuth2ProviderRegistry
from parrot.auth.principal import Principal
from parrot.integrations.slack.commands import SlackCommandRouter
from parrot.integrations.slack.commands.connection_commands import register_connection_commands

PAYLOAD = {"team_id": "T01", "user_id": "U02", "channel_id": "C1", "text": "jira"}


class _Provider:
    """Minimal registry provider used by generic-command tests."""

    provider_id = "jira"


@pytest.fixture(autouse=True)
def registered_provider() -> None:
    """Register the provider IDs exercised by this module."""
    OAuth2ProviderRegistry._reset()
    OAuth2ProviderRegistry().register(_Provider())
    yield
    OAuth2ProviderRegistry._reset()


@pytest.fixture
def principal() -> Principal:
    """Return the linked platform principal for test Slack identity."""
    return Principal(user_id="1042", channel="slack", channel_user_id="T01:U02")


def _router(link_issuer: object | None = None, service: object | None = None) -> SlackCommandRouter:
    """Create a command router backed by supplied command dependencies."""
    router = SlackCommandRouter()
    register_connection_commands(router, link_issuer=link_issuer or AsyncMock(), service_factory=lambda: service)
    return router


async def test_slack_connect_unlinked_replies_login(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unlinked users receive the login instruction without OAuth state creation."""
    service = MagicMock(start_connect=AsyncMock())
    monkeypatch.setattr(
        "parrot.integrations.slack.commands.connection_commands.resolve_principal", AsyncMock(return_value=None)
    )
    result = await _router(service=service).dispatch("connect", PAYLOAD)
    assert result is not None
    assert "/login" in result["text"]
    service.start_connect.assert_not_awaited()


async def test_slack_connect_linked_starts_with_principal(
    principal: Principal, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Linked users start Slack-scoped OAuth with their resolved principal."""
    service = MagicMock(start_connect=AsyncMock(return_value=MagicMock(auth_url="https://oauth.example/connect")))
    monkeypatch.setattr(
        "parrot.integrations.slack.commands.connection_commands.resolve_principal", AsyncMock(return_value=principal)
    )
    result = await _router(service=service).dispatch("connect", PAYLOAD)
    assert result is not None
    service.start_connect.assert_awaited_once_with(
        "1042",
        "jira",
        channel="slack",
        principal=principal,
        extra_state={"team_id": "T01", "slack_user_id": "U02"},
    )
    assert result["blocks"][0]["accessory"]["url"] == "https://oauth.example/connect"


async def test_slack_jira_aliases_delegate(principal: Principal, monkeypatch: pytest.MonkeyPatch) -> None:
    """Jira aliases invoke the generic service calls with provider ``jira``."""
    service = MagicMock(
        start_connect=AsyncMock(return_value=MagicMock(auth_url="https://oauth.example/connect")),
        disconnect=AsyncMock(),
        status=AsyncMock(return_value=MagicMock(status="connected", display_account_name="Ada", display_name="Jira")),
    )
    monkeypatch.setattr(
        "parrot.integrations.slack.commands.connection_commands.resolve_principal", AsyncMock(return_value=principal)
    )
    router = _router(service=service)
    await router.dispatch("connect_jira", {**PAYLOAD, "text": ""})
    await router.dispatch("disconnect_jira", {**PAYLOAD, "text": ""})
    result = await router.dispatch("jira_status", {**PAYLOAD, "text": ""})
    assert result is not None
    service.start_connect.assert_awaited_once()
    service.disconnect.assert_awaited_once_with("1042", "jira", principal=principal)
    service.status.assert_awaited_once_with("1042", "jira", principal=principal)
    assert "Ada" in result["text"]


async def test_login_issues_team_qualified_link(monkeypatch: pytest.MonkeyPatch) -> None:
    """Login issues a link for the team-qualified Slack identity."""
    issuer = MagicMock(issue=AsyncMock(return_value="https://app.example/account/link?token=opaque"))
    monkeypatch.setattr(
        "parrot.integrations.slack.commands.connection_commands.resolve_principal", AsyncMock(return_value=None)
    )
    result = await _router(link_issuer=issuer).dispatch("login", PAYLOAD)
    assert result is not None
    issuer.issue.assert_awaited_once_with("slack", "T01:U02", {"team_id": "T01", "slack_user_id": "U02"})
    assert result["blocks"][0]["accessory"]["url"] == "https://app.example/account/link?token=opaque"


async def test_login_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unavailable issuer returns a safe configuration response."""
    issuer = MagicMock(issue=AsyncMock(side_effect=ValueError("base URL missing")))
    monkeypatch.setattr(
        "parrot.integrations.slack.commands.connection_commands.resolve_principal", AsyncMock(return_value=None)
    )
    result = await _router(link_issuer=issuer).dispatch("login", PAYLOAD)
    assert result is not None
    assert "not configured" in result["text"].lower()


@pytest.mark.parametrize("command", ["connect", "disconnect", "connections", "jira_status"])
async def test_permission_denied_discloses_nothing(
    command: str, principal: Principal, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Permission denial returns the generic response without account information."""
    service = MagicMock(
        start_connect=AsyncMock(side_effect=PermissionError()),
        disconnect=AsyncMock(side_effect=PermissionError()),
        list_for_principal=AsyncMock(side_effect=PermissionError()),
        status=AsyncMock(side_effect=PermissionError()),
    )
    monkeypatch.setattr(
        "parrot.integrations.slack.commands.connection_commands.resolve_principal", AsyncMock(return_value=principal)
    )
    result = await _router(service=service).dispatch(command, PAYLOAD)
    assert result is not None
    assert result["text"] == "You are not permitted to do that."


async def test_unknown_provider_lists_registered(principal: Principal, monkeypatch: pytest.MonkeyPatch) -> None:
    """Unknown providers enumerate registered IDs before creating state."""
    service = MagicMock(start_connect=AsyncMock())
    monkeypatch.setattr(
        "parrot.integrations.slack.commands.connection_commands.resolve_principal", AsyncMock(return_value=principal)
    )
    result = await _router(service=service).dispatch("connect", {**PAYLOAD, "text": "unknown"})
    assert result is not None
    assert "jira" in result["text"]
    service.start_connect.assert_not_awaited()
