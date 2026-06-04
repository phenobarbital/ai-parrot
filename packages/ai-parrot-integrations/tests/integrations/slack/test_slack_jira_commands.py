"""Unit tests for SlackCommandRouter and Slack Jira command handlers (FEAT-225 / TASK-1468)."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot.integrations.slack.commands import SlackCommandRouter
from parrot.integrations.slack.commands.jira_commands import (
    connect_jira_handler,
    disconnect_jira_handler,
    jira_status_handler,
    register_jira_commands,
    _SLACK_CHANNEL,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_oauth_manager():
    """JiraOAuthManager with mocked async methods."""
    manager = MagicMock()
    manager.validate_token = AsyncMock(return_value=None)
    manager.create_authorization_url = AsyncMock(
        return_value=("https://auth.atlassian.com/authorize?foo=bar", "nonce-abc")
    )
    manager.revoke = AsyncMock(return_value=None)
    return manager


@pytest.fixture
def slack_payload():
    """Standard Slack slash-command POST payload."""
    return {
        "team_id": "T0001",
        "user_id": "U1234",
        "channel_id": "C5678",
        "text": "",
        "response_url": "https://hooks.slack.com/commands/T0001/...",
    }


# ---------------------------------------------------------------------------
# SlackCommandRouter tests
# ---------------------------------------------------------------------------

class TestSlackCommandRouter:
    def test_dispatch_registered_command(self):
        """dispatch calls the registered handler."""
        router = SlackCommandRouter()
        handler = AsyncMock(return_value={"text": "ok"})
        router.register("test_cmd", handler)
        assert "test_cmd" in router.registered_commands

    @pytest.mark.asyncio
    async def test_dispatch_unknown_returns_none(self):
        """dispatch returns None for an unregistered command."""
        router = SlackCommandRouter()

        result = await router.dispatch("unknown_cmd", {})
        assert result is None

    def test_register_normalizes_slash_prefix(self):
        """register strips leading '/' before storing."""
        router = SlackCommandRouter()
        handler = AsyncMock()
        router.register("/connect_jira", handler)
        assert "connect_jira" in router.registered_commands

    @pytest.mark.asyncio
    async def test_dispatch_calls_handler_with_payload(self):
        """dispatch passes the payload dict to the handler."""
        router = SlackCommandRouter()
        handler = AsyncMock(return_value={"text": "result"})
        router.register("my_cmd", handler)

        payload = {"team_id": "T1", "user_id": "U2"}
        result = await router.dispatch("my_cmd", payload)

        handler.assert_called_once_with(payload)
        assert result == {"text": "result"}

    @pytest.mark.asyncio
    async def test_dispatch_unknown_command_returns_none(self):
        """dispatch returns None for unknown commands."""
        router = SlackCommandRouter()
        result = await router.dispatch("does_not_exist", {})
        assert result is None

    @pytest.mark.asyncio
    async def test_dispatch_with_slash_prefix_in_command(self):
        """dispatch normalizes the command name before lookup."""
        router = SlackCommandRouter()
        handler = AsyncMock(return_value={"text": "hello"})
        router.register("greet", handler)

        result = await router.dispatch("/greet", {"text": "world"})
        assert result == {"text": "hello"}


# ---------------------------------------------------------------------------
# connect_jira_handler tests
# ---------------------------------------------------------------------------

class TestConnectJiraHandler:
    @pytest.mark.asyncio
    async def test_generates_auth_url_when_not_connected(self, mock_oauth_manager, slack_payload):
        """Returns a button message with the auth URL when not connected."""
        result = await connect_jira_handler(slack_payload, mock_oauth_manager)

        mock_oauth_manager.validate_token.assert_called_once_with(
            _SLACK_CHANNEL, "T0001:U1234"
        )
        mock_oauth_manager.create_authorization_url.assert_called_once_with(
            _SLACK_CHANNEL,
            "T0001:U1234",
            extra_state={
                "channel": _SLACK_CHANNEL,
                "team_id": "T0001",
                "slack_user_id": "U1234",
            },
        )
        assert result["response_type"] == "ephemeral"
        # Should include blocks with a button
        assert "blocks" in result or "text" in result

    @pytest.mark.asyncio
    async def test_already_connected_short_circuits(self, mock_oauth_manager, slack_payload):
        """Returns 'already connected' when validate_token returns a token."""
        token = MagicMock()
        token.display_name = "Jane Doe"
        mock_oauth_manager.validate_token = AsyncMock(return_value=token)

        result = await connect_jira_handler(slack_payload, mock_oauth_manager)

        mock_oauth_manager.create_authorization_url.assert_not_called()
        assert "already" in result["text"].lower()
        assert result["response_type"] == "ephemeral"

    @pytest.mark.asyncio
    async def test_multi_workspace_user_id_format(self, mock_oauth_manager, slack_payload):
        """user_id passed to JiraOAuthManager is '{team_id}:{slack_user_id}'."""
        await connect_jira_handler(slack_payload, mock_oauth_manager)

        # validate_token called with composite key
        args = mock_oauth_manager.validate_token.call_args[0]
        assert args[0] == _SLACK_CHANNEL
        assert args[1] == "T0001:U1234"

    @pytest.mark.asyncio
    async def test_extra_state_contains_channel(self, mock_oauth_manager, slack_payload):
        """extra_state passed to create_authorization_url includes channel='slack'."""
        await connect_jira_handler(slack_payload, mock_oauth_manager)

        _, kwargs = mock_oauth_manager.create_authorization_url.call_args
        extra = kwargs.get("extra_state") or mock_oauth_manager.create_authorization_url.call_args[1].get("extra_state")
        # Also check via positional args
        call_args = mock_oauth_manager.create_authorization_url.call_args
        if call_args.kwargs.get("extra_state"):
            extra_state = call_args.kwargs["extra_state"]
        else:
            extra_state = call_args.args[2] if len(call_args.args) > 2 else call_args.kwargs.get("extra_state")
        assert extra_state["channel"] == "slack"
        assert extra_state["team_id"] == "T0001"
        assert extra_state["slack_user_id"] == "U1234"


# ---------------------------------------------------------------------------
# disconnect_jira_handler tests
# ---------------------------------------------------------------------------

class TestDisconnectJiraHandler:
    @pytest.mark.asyncio
    async def test_revokes_token(self, mock_oauth_manager, slack_payload):
        """Calls oauth_manager.revoke with correct channel and user_id."""
        result = await disconnect_jira_handler(slack_payload, mock_oauth_manager)

        mock_oauth_manager.revoke.assert_called_once_with(_SLACK_CHANNEL, "T0001:U1234")
        assert result["response_type"] == "ephemeral"
        assert "disconnected" in result["text"].lower()

    @pytest.mark.asyncio
    async def test_revoke_called_with_composite_user_id(self, mock_oauth_manager, slack_payload):
        """revoke uses '{team_id}:{slack_user_id}' as the user_id."""
        await disconnect_jira_handler(slack_payload, mock_oauth_manager)
        args = mock_oauth_manager.revoke.call_args[0]
        assert args[0] == _SLACK_CHANNEL
        assert args[1] == "T0001:U1234"


# ---------------------------------------------------------------------------
# jira_status_handler tests
# ---------------------------------------------------------------------------

class TestJiraStatusHandler:
    @pytest.mark.asyncio
    async def test_returns_connected_status(self, mock_oauth_manager, slack_payload):
        """Returns display_name and site_url when connected."""
        token = MagicMock()
        token.display_name = "Jane Doe"
        token.site_url = "https://myco.atlassian.net"
        mock_oauth_manager.validate_token = AsyncMock(return_value=token)

        result = await jira_status_handler(slack_payload, mock_oauth_manager)

        assert result["response_type"] == "ephemeral"
        assert "Jane Doe" in result["text"]
        assert "myco.atlassian.net" in result["text"]

    @pytest.mark.asyncio
    async def test_returns_not_connected_status(self, mock_oauth_manager, slack_payload):
        """Returns 'not connected' when no token is found."""
        mock_oauth_manager.validate_token = AsyncMock(return_value=None)

        result = await jira_status_handler(slack_payload, mock_oauth_manager)

        assert result["response_type"] == "ephemeral"
        assert "not connected" in result["text"].lower()


# ---------------------------------------------------------------------------
# register_jira_commands tests
# ---------------------------------------------------------------------------

class TestRegisterJiraCommands:
    def test_registers_three_commands(self, mock_oauth_manager):
        """register_jira_commands registers connect_jira, disconnect_jira, jira_status."""
        router = SlackCommandRouter()
        register_jira_commands(router, mock_oauth_manager)

        assert "connect_jira" in router.registered_commands
        assert "disconnect_jira" in router.registered_commands
        assert "jira_status" in router.registered_commands

    @pytest.mark.asyncio
    async def test_registered_connect_dispatches(self, mock_oauth_manager, slack_payload):
        """The registered connect_jira command dispatches correctly."""
        router = SlackCommandRouter()
        register_jira_commands(router, mock_oauth_manager)

        result = await router.dispatch("connect_jira", slack_payload)
        assert result is not None
        assert result["response_type"] == "ephemeral"

    @pytest.mark.asyncio
    async def test_registered_disconnect_dispatches(self, mock_oauth_manager, slack_payload):
        """The registered disconnect_jira command dispatches correctly."""
        router = SlackCommandRouter()
        register_jira_commands(router, mock_oauth_manager)

        result = await router.dispatch("disconnect_jira", slack_payload)
        assert result is not None
        assert "disconnected" in result["text"].lower()

    @pytest.mark.asyncio
    async def test_registered_status_dispatches(self, mock_oauth_manager, slack_payload):
        """The registered jira_status command dispatches correctly."""
        router = SlackCommandRouter()
        register_jira_commands(router, mock_oauth_manager)

        result = await router.dispatch("jira_status", slack_payload)
        assert result is not None
        assert result["response_type"] == "ephemeral"


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

def test_slack_channel_constant():
    """_SLACK_CHANNEL is 'slack'."""
    assert _SLACK_CHANNEL == "slack"
