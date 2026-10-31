"""Tests for Jira ChannelNotifier adapters (FEAT-773 TASK-4953)."""

from unittest.mock import AsyncMock, Mock

import pytest

from parrot.auth.oauth2.events import ConnectionEvent
from parrot.integrations.core.auth.notifiers import (
    MSTeamsJiraNotifierAdapter,
    SlackJiraNotifierAdapter,
)


def _event(kind: str, *, provider: str = "jira") -> ConnectionEvent:
    return ConnectionEvent(
        kind=kind,
        user_id="42",
        provider=provider,
        account_id="jira-account",
        display_name="Jira User",
        channel="telegram",
        occurred_at=1.0,
        reason="expired grant",
    )


@pytest.mark.asyncio
async def test_notifier_adapters_delegate() -> None:
    """Slack and Teams adapters forward completion data and preserve identity guards."""
    slack_notifier = Mock()
    slack_notifier.notify_connected = AsyncMock()
    slack_notifier.notify_failure = AsyncMock()
    teams_notifier = Mock()
    teams_notifier.notify_connected = AsyncMock()
    teams_notifier.notify_failure = AsyncMock()
    identity = Mock()
    identity.upsert_identity = AsyncMock()
    app = {
        "slack_jira_oauth_notifier": slack_notifier,
        "msteams_jira_oauth_notifier": teams_notifier,
        "identity_mapping_service": identity,
    }

    state = {
        "user_id": "123",
        "extra": {
            "chat_id": "456",
            "team_id": "T1",
            "slack_user_id": "U1",
            "nav_user_id": "42",
            "conversation_reference": {"conversation": {"tenantId": "tenant-1"}},
        },
        "connection_meta": {"site_url": "https://example.atlassian.net", "cloud_id": "cloud-1"},
    }

    await SlackJiraNotifierAdapter(app).notify(_event("connection.completed"), state)
    await MSTeamsJiraNotifierAdapter(app).notify(_event("connection.completed"), state)

    slack_notifier.notify_connected.assert_awaited_once_with(
        team_id="T1", slack_user_id="U1", display_name="Jira User", site_url="https://example.atlassian.net"
    )
    teams_notifier.notify_connected.assert_awaited_once_with(
        conversation_ref_dict={"conversation": {"tenantId": "tenant-1"}},
        display_name="Jira User",
        site_url="https://example.atlassian.net",
    )
    assert identity.upsert_identity.await_count == 2
    assert identity.upsert_identity.call_args_list[0].kwargs["provider_user_id"] == "U1"
    assert identity.upsert_identity.call_args_list[1].kwargs["provider_user_id"] == "123"


@pytest.mark.asyncio
async def test_notifier_adapters_failure_and_non_jira_are_safe() -> None:
    """Failure events notify known channel users and other providers are ignored."""
    notifier = Mock()
    notifier.notify_failure = AsyncMock()
    app = {
        "slack_jira_oauth_notifier": notifier,
        "msteams_jira_oauth_notifier": notifier,
    }
    state = {
        "extra": {
            "chat_id": "456",
            "team_id": "T1",
            "slack_user_id": "U1",
            "conversation_reference": {"id": "conversation"},
        }
    }

    await SlackJiraNotifierAdapter(app).notify(_event("connection.revoked"), state)
    await MSTeamsJiraNotifierAdapter(app).notify(_event("connection.refresh_failed"), state)
    assert notifier.notify_failure.await_count == 2

    await SlackJiraNotifierAdapter(app).notify(_event("connection.completed", provider="o365"), state)
    assert notifier.notify_failure.await_count == 2


@pytest.mark.asyncio
async def test_identity_guards_are_preserved() -> None:
    """Slack composite ids and non-numeric Teams ids never become Navigator ids."""
    identity = Mock()
    identity.upsert_identity = AsyncMock()
    app = {"identity_mapping_service": identity}
    slack_state = {
        "user_id": "team:user",
        "extra": {
            "team_id": "T1",
            "slack_user_id": "U1",
            "conversation_reference": {},
            "user_id": "teams-guid",
        },
    }
    teams_state = {
        "user_id": "teams-guid",
        "extra": {
            "conversation_reference": {},
            "nav_user_id": "not-a-number",
        },
    }

    await SlackJiraNotifierAdapter(app).notify(_event("connection.completed"), slack_state)
    await MSTeamsJiraNotifierAdapter(app).notify(_event("connection.completed"), teams_state)
    identity.upsert_identity.assert_not_awaited()
