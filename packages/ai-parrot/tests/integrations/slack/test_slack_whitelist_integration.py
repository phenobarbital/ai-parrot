"""Integration tests for Slack whitelist full flow (TASK-254).

Tests the full event/command processing flow through _handle_events
and _handle_command with various whitelist configurations.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import web

from parrot.integrations.slack.models import SlackAgentConfig


def _make_config(**kwargs) -> SlackAgentConfig:
    """Create a SlackAgentConfig with defaults and overrides."""
    defaults = {
        "name": "test",
        "chatbot_id": "bot1",
        "bot_token": "xoxb-fake",
        "signing_secret": "fake-secret",
    }
    defaults.update(kwargs)
    with patch("parrot.integrations.slack.models.config") as mock_config:
        mock_config.get = lambda key, **kw: None
        return SlackAgentConfig(**defaults)


def _make_wrapper(config):
    """Create a SlackAgentWrapper with mocked internals."""
    with patch(
        "parrot.integrations.slack.wrapper.SlackAgentWrapper.__init__",
        return_value=None,
    ):
        from parrot.integrations.slack.wrapper import SlackAgentWrapper

        wrapper = SlackAgentWrapper.__new__(SlackAgentWrapper)
        wrapper.config = config
        wrapper.logger = MagicMock()
        wrapper.conversations = {}
        wrapper._background_tasks = set()
        wrapper._safe_answer = AsyncMock()
        wrapper._bot_user_id = "B001"
        wrapper._web_client = MagicMock()
        wrapper.enable_assistant = False
        # Mock deduplicator
        wrapper._dedup = MagicMock()
        wrapper._dedup.is_duplicate = MagicMock(return_value=False)
        # Mock assistant handler (None = disabled)
        wrapper._assistant_handler = None
    return wrapper


def _make_event_request(channel: str, user: str, text: str = "hello"):
    """Create a mock aiohttp request with a Slack event payload."""
    payload = {
        "type": "event_callback",
        "event": {
            "type": "message",
            "channel": channel,
            "user": user,
            "text": text,
            "ts": "1234567890.123456",
        },
        "event_id": "Ev123",
    }
    raw_body = json.dumps(payload).encode()
    request = MagicMock()
    request.read = AsyncMock(return_value=raw_body)
    headers_data = {
        "X-Slack-Signature": "v0=fake",
        "X-Slack-Request-Timestamp": "0",
    }
    request.headers = MagicMock()
    request.headers.get = lambda key, default=None: headers_data.get(key, default)
    return request


def _make_command_request(channel: str, user: str, text: str = "help"):
    """Create a mock aiohttp request for a Slack slash command."""
    form_data = {
        "channel_id": channel,
        "user_id": user,
        "text": text,
        "command": "/ask",
    }
    request = MagicMock(spec=web.Request)
    request.post = AsyncMock(return_value=form_data)
    return request


class TestSlackEventWhitelistIntegration:
    """Full-flow tests for Slack event handling with whitelists."""

    @pytest.mark.asyncio
    async def test_event_blocked_by_user_whitelist(self):
        """Event with unauthorized user is silently ignored."""
        config = _make_config(
            allowed_channel_ids=["C001"],
            allowed_user_ids=["U001"],
        )
        wrapper = _make_wrapper(config)

        request = _make_event_request(
            channel="C001", user="U999", text="hello"
        )

        with patch(
            "parrot.integrations.slack.wrapper.verify_slack_signature_raw",
            return_value=True,
        ):
            response = await wrapper._handle_events(request)

        # Should return ok but NOT process the message
        body = json.loads(response.body)
        assert body["ok"] is True
        wrapper._safe_answer.assert_not_called()

    @pytest.mark.asyncio
    async def test_event_allowed_with_both_whitelists(self):
        """Authorized channel + user processes the message normally."""
        config = _make_config(
            allowed_channel_ids=["C001"],
            allowed_user_ids=["U001"],
        )
        wrapper = _make_wrapper(config)

        request = _make_event_request(
            channel="C001", user="U001", text="process this"
        )

        with patch(
            "parrot.integrations.slack.wrapper.verify_slack_signature_raw",
            return_value=True,
        ):
            response = await wrapper._handle_events(request)

        body = json.loads(response.body)
        assert body["ok"] is True
        # Message should be processed (background task created)
        wrapper._safe_answer.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_user_whitelist_allows_all_users(self):
        """Only channel whitelist, any user in that channel passes."""
        config = _make_config(
            allowed_channel_ids=["C001"],
            # No allowed_user_ids — all users allowed
        )
        wrapper = _make_wrapper(config)

        request = _make_event_request(
            channel="C001", user="U-anyone", text="hi"
        )

        with patch(
            "parrot.integrations.slack.wrapper.verify_slack_signature_raw",
            return_value=True,
        ):
            response = await wrapper._handle_events(request)

        body = json.loads(response.body)
        assert body["ok"] is True
        wrapper._safe_answer.assert_called_once()


class TestSlackCommandWhitelistIntegration:
    """Full-flow tests for Slack slash command handling with whitelists."""

    @pytest.mark.asyncio
    async def test_command_blocked_by_user_whitelist(self):
        """Slash command from unauthorized user returns ephemeral error."""
        config = _make_config(
            allowed_channel_ids=["C001"],
            allowed_user_ids=["U001"],
        )
        wrapper = _make_wrapper(config)

        request = _make_command_request(
            channel="C001", user="U999", text="ask something"
        )

        response = await wrapper._handle_command(request)

        body = json.loads(response.body)
        assert body["response_type"] == "ephemeral"
        assert "unauthorized" in body["text"].lower()
        wrapper._safe_answer.assert_not_called()
