"""SlackConnectionNotifier (FEAT-777 AC-6)."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock

import pytest

from parrot.auth.oauth2.events import ConnectionEvent
from parrot.integrations.slack.notifier import SlackConnectionNotifier


def _event(kind: str, provider: str) -> ConnectionEvent:
    return ConnectionEvent(
        kind=kind, user_id="1042", provider=provider, display_name="Jesus", channel="slack", occurred_at=time.time()
    )


@pytest.fixture
def notifier() -> SlackConnectionNotifier:
    n = SlackConnectionNotifier(bot_token="xoxb-test")
    n._client = AsyncMock()
    return n


@pytest.mark.parametrize("provider", ["jira", "o365"])
@pytest.mark.parametrize("kind", ["connection.completed", "connection.revoked", "connection.refresh_failed"])
async def test_dm_any_provider(notifier: SlackConnectionNotifier, kind: str, provider: str) -> None:
    await notifier.notify(_event(kind, provider), {"extra": {"slack_user_id": "U02", "team_id": "T01"}})
    notifier._client.chat_postMessage.assert_awaited_once()
    assert notifier._client.chat_postMessage.await_args.kwargs["channel"] == "U02"


async def test_no_slack_user_is_noop(notifier: SlackConnectionNotifier) -> None:
    await notifier.notify(_event("connection.completed", "jira"), {"extra": {}})
    notifier._client.chat_postMessage.assert_not_awaited()


async def test_dm_failure_is_swallowed(notifier: SlackConnectionNotifier) -> None:
    notifier._client.chat_postMessage.side_effect = RuntimeError("boom")
    await notifier.notify(_event("connection.completed", "jira"), {"extra": {"slack_user_id": "U02"}})


async def test_never_writes_identity(notifier: SlackConnectionNotifier) -> None:
    assert not hasattr(notifier, "_app")
