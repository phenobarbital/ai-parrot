"""Slack and MS Teams Jira commands resolve the platform principal (FEAT-773, TASK-4956).

Bound users connect, see status and disconnect against the principal key
(the Navigator ``user_id``); unbound users get the link-first reply and no
OAuth state is created.
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.auth.principal import Principal, set_principal_resolver
from parrot.integrations.msteams.commands.jira_commands import (
    connect_jira_handler as teams_connect,
    disconnect_jira_handler as teams_disconnect,
    jira_status_handler as teams_status,
)
from parrot.integrations.slack.commands.jira_commands import (
    _LINK_FIRST as SLACK_LINK_FIRST,
    connect_jira_handler as slack_connect,
    disconnect_jira_handler as slack_disconnect,
    jira_status_handler as slack_status,
)

NAV_USER_ID = "42"
SLACK_KEY = "T0001:U1234"
TEAMS_AAD_ID = "aad-obj-123"


class FakeResolver:
    """In-memory principal resolver keyed by ``(channel, channel_user_id)``."""

    def __init__(self, bindings: Dict[Tuple[str, str], str]) -> None:
        self._bindings = bindings

    async def resolve(self, channel: str, channel_user_id: str) -> Optional[Principal]:
        """Return the bound principal or ``None`` (fail closed)."""
        nav_id = self._bindings.get((channel, channel_user_id))
        if nav_id is None:
            return None
        return Principal(user_id=nav_id, channel=channel, channel_user_id=channel_user_id)


@pytest.fixture(autouse=True)
def _reset_resolver():
    """Restore the default process-wide resolver after every test."""
    yield
    set_principal_resolver(None)


@pytest.fixture
def bind_slack():
    """Bind the Slack composite id to the Navigator user."""
    set_principal_resolver(FakeResolver({("slack", SLACK_KEY): NAV_USER_ID}))


@pytest.fixture
def bind_teams():
    """Bind the Teams AAD id to the Navigator user."""
    set_principal_resolver(FakeResolver({("msteams", TEAMS_AAD_ID): NAV_USER_ID}))


@pytest.fixture
def oauth_manager():
    """JiraOAuthManager double with async methods."""
    manager = MagicMock()
    manager.validate_token = AsyncMock(return_value=None)
    manager.create_authorization_url = AsyncMock(
        return_value=("https://auth.atlassian.com/authorize?x=1", "nonce-abc")
    )
    manager.revoke = AsyncMock(return_value=None)
    return manager


@pytest.fixture
def slack_payload():
    """Slack slash-command payload for the composite key ``T0001:U1234``."""
    return {"team_id": "T0001", "user_id": "U1234", "channel_id": "C5678"}


def _teams_turn(aad_object_id: str = TEAMS_AAD_ID):
    """Build a minimal Bot Framework turn context double."""
    ctx = MagicMock()
    ctx.activity.from_property.id = "teams-user-456"
    ctx.activity.from_property.aad_object_id = aad_object_id
    ctx.send_activity = AsyncMock()
    return ctx


def _sent_text(ctx: MagicMock) -> str:
    """Return the text of the single activity sent on a turn double."""
    assert ctx.send_activity.await_count == 1
    return ctx.send_activity.await_args.args[0].text


# ---------------------------------------------------------------------------
# Slack
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_slack_connect_unbound_user_gets_link_first(oauth_manager, slack_payload):
    """An unlinked Slack user gets the link-first reply and no OAuth state."""
    result = await slack_connect(slack_payload, oauth_manager)

    assert result["text"] == SLACK_LINK_FIRST
    oauth_manager.validate_token.assert_not_awaited()
    oauth_manager.create_authorization_url.assert_not_awaited()


@pytest.mark.asyncio
async def test_slack_connect_bound_user_creates_url_for_principal(bind_slack, oauth_manager, slack_payload):
    """A linked Slack user gets a connect button; the URL is minted for the principal."""
    result = await slack_connect(slack_payload, oauth_manager)

    assert "blocks" in result
    oauth_manager.validate_token.assert_awaited_once_with("slack", SLACK_KEY)
    args, kwargs = oauth_manager.create_authorization_url.await_args
    assert args == ("slack", SLACK_KEY)
    assert kwargs["principal"].user_id == NAV_USER_ID
    assert kwargs["principal"].channel_user_id == SLACK_KEY
    assert kwargs["extra_state"] == {
        "channel": "slack",
        "team_id": "T0001",
        "slack_user_id": "U1234",
    }


@pytest.mark.asyncio
async def test_slack_status_unbound_user_gets_link_first(oauth_manager, slack_payload):
    """An unlinked Slack user asking for status is told to link first."""
    result = await slack_status(slack_payload, oauth_manager)

    assert result["text"] == SLACK_LINK_FIRST
    oauth_manager.validate_token.assert_not_awaited()


@pytest.mark.asyncio
async def test_slack_status_bound_user_reports_connection(bind_slack, oauth_manager, slack_payload):
    """A linked Slack user with a live token sees the connected reply."""
    token = MagicMock(display_name="Ada", site_url="https://ada.atlassian.net")
    oauth_manager.validate_token.return_value = token

    result = await slack_status(slack_payload, oauth_manager)

    oauth_manager.validate_token.assert_awaited_once_with("slack", SLACK_KEY)
    assert "Connected to Jira as *Ada*" in result["text"]


@pytest.mark.asyncio
async def test_slack_disconnect_unbound_user_gets_link_first(oauth_manager, slack_payload):
    """An unlinked Slack user cannot disconnect anything."""
    result = await slack_disconnect(slack_payload, oauth_manager)

    assert result["text"] == SLACK_LINK_FIRST
    oauth_manager.revoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_slack_disconnect_bound_user_revokes_principal_key(bind_slack, oauth_manager, slack_payload):
    """A linked Slack user is revoked against the Navigator principal, not the raw id."""
    result = await slack_disconnect(slack_payload, oauth_manager)

    oauth_manager.revoke.assert_awaited_once_with("slack", NAV_USER_ID, channel_user_id=SLACK_KEY)
    assert result["text"] == "Your Jira account has been disconnected."


# ---------------------------------------------------------------------------
# MS Teams
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_teams_connect_unbound_user_gets_link_first(oauth_manager):
    """An unlinked Teams user gets the link-first reply and no authorization URL."""
    ctx = _teams_turn()

    await teams_connect(ctx, oauth_manager)

    assert "Link your Teams account" in _sent_text(ctx)
    oauth_manager.validate_token.assert_not_awaited()
    oauth_manager.create_authorization_url.assert_not_awaited()


@pytest.mark.asyncio
async def test_teams_connect_bound_user_passes_principal(bind_teams, oauth_manager):
    """A linked Teams user gets the connect card; the URL is minted with the principal."""
    ctx = _teams_turn()

    await teams_connect(ctx, oauth_manager)

    oauth_manager.validate_token.assert_awaited_once_with("msteams", TEAMS_AAD_ID)
    args, kwargs = oauth_manager.create_authorization_url.await_args
    assert args == ("msteams", TEAMS_AAD_ID)
    assert kwargs["principal"].user_id == NAV_USER_ID
    assert kwargs["extra_state"]["channel"] == "msteams"


@pytest.mark.asyncio
async def test_teams_status_uses_principal_key(bind_teams, oauth_manager):
    """A linked Teams user's status is checked through the bound principal."""
    oauth_manager.validate_token.return_value = MagicMock(
        display_name="Ada", site_url="https://ada.atlassian.net"
    )
    ctx = _teams_turn()

    await teams_status(ctx, oauth_manager)

    oauth_manager.validate_token.assert_awaited_once_with("msteams", TEAMS_AAD_ID)
    assert "Connected to Jira as **Ada**" in _sent_text(ctx)


@pytest.mark.asyncio
async def test_teams_status_unbound_user_gets_link_first(oauth_manager):
    """An unlinked Teams user asking for status is told to link first."""
    ctx = _teams_turn()

    await teams_status(ctx, oauth_manager)

    assert "Link your Teams account" in _sent_text(ctx)
    oauth_manager.validate_token.assert_not_awaited()


@pytest.mark.asyncio
async def test_teams_disconnect_bound_user_revokes_principal_key(bind_teams, oauth_manager):
    """A linked Teams user is revoked against the Navigator principal, not the AAD id."""
    ctx = _teams_turn()

    await teams_disconnect(ctx, oauth_manager)

    oauth_manager.revoke.assert_awaited_once_with("msteams", NAV_USER_ID, channel_user_id=TEAMS_AAD_ID)
    assert _sent_text(ctx) == "Your Jira account has been disconnected."


@pytest.mark.asyncio
async def test_teams_disconnect_unbound_user_gets_link_first(oauth_manager):
    """An unlinked Teams user cannot disconnect anything."""
    ctx = _teams_turn()

    await teams_disconnect(ctx, oauth_manager)

    assert "Link your Teams account" in _sent_text(ctx)
    oauth_manager.revoke.assert_not_awaited()
