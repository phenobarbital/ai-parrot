"""Tests for the Jira ChannelNotifier adapter (FEAT-773 TASK-4953).

Slack and Teams no longer have Jira-specific adapters: they use the provider-agnostic
``SlackConnectionNotifier`` (FEAT-777) and ``MSTeamsConnectionNotifier`` (FEAT-775).
"""

from unittest.mock import AsyncMock, Mock

import pytest

from parrot.auth.oauth2.events import ConnectionEvent
from parrot.integrations.core.auth.notifiers import TelegramJiraNotifierAdapter


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
async def test_telegram_adapter_delegates() -> None:
    """The Telegram adapter stamps the session and forwards completion data."""
    telegram_notifier = Mock()
    telegram_notifier.notify_connected = AsyncMock()
    telegram_notifier.notify_failure = AsyncMock()
    stamp = Mock()
    app = {
        "telegram_jira_session_stamper": stamp,
        "jira_oauth_notifier": telegram_notifier,
    }
    state = {
        "user_id": "123",
        "extra": {"chat_id": "456"},
        "connection_meta": {"site_url": "https://example.atlassian.net", "cloud_id": "cloud-1"},
    }

    await TelegramJiraNotifierAdapter(app).notify(_event("connection.completed"), state)

    stamp.assert_called_once()
    assert stamp.call_args.args[0] == "123"
    assert stamp.call_args.args[1].account_id == "jira-account"
    telegram_notifier.notify_connected.assert_awaited_once_with(456, "Jira User", "https://example.atlassian.net")


@pytest.mark.asyncio
async def test_telegram_adapter_failure_and_non_jira_are_safe() -> None:
    """Failure events notify known users and other providers are ignored."""
    notifier = Mock()
    notifier.notify_failure = AsyncMock()
    app = {"jira_oauth_notifier": notifier}
    state = {"extra": {"chat_id": "456"}}

    await TelegramJiraNotifierAdapter(app).notify(_event("connection.refresh_failed"), state)
    assert notifier.notify_failure.await_count == 1

    await TelegramJiraNotifierAdapter(app).notify(_event("connection.completed", provider="o365"), state)
    assert notifier.notify_failure.await_count == 1
