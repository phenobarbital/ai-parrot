"""Unit tests for MSTeamsCommandRouter and MS Teams Jira command handlers (FEAT-225 / TASK-1471)."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_turn_context(text: str = "", aad_object_id: str = "aad-obj-123"):
    """Build a minimal mock TurnContext."""
    ctx = MagicMock()
    ctx.activity.text = text
    ctx.activity.from_property.id = "teams-user-456"
    ctx.activity.from_property.aad_object_id = aad_object_id
    ctx.activity.conversation.id = "conv-789"
    ctx.send_activity = AsyncMock()

    # Mock TurnContext.get_conversation_reference
    mock_conv_ref = MagicMock()
    mock_conv_ref.serialize = MagicMock(return_value={"conversation": {"id": "conv-789"}})
    return ctx, mock_conv_ref


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


# ---------------------------------------------------------------------------
# MSTeamsCommandRouter tests
# ---------------------------------------------------------------------------

class TestMSTeamsCommandRouter:
    @pytest.mark.asyncio
    async def test_dispatches_registered_command(self):
        """try_dispatch calls the registered handler and returns True."""
        from parrot.integrations.msteams.commands import MSTeamsCommandRouter

        router = MSTeamsCommandRouter()
        handler = AsyncMock()
        router.register("test_cmd", handler)

        ctx = MagicMock()
        ctx.send_activity = AsyncMock()
        result = await router.try_dispatch("/test_cmd", ctx)

        assert result is True
        handler.assert_called_once_with(ctx)

    @pytest.mark.asyncio
    async def test_ignores_non_command_text(self):
        """Non-command text (no leading /) returns False."""
        from parrot.integrations.msteams.commands import MSTeamsCommandRouter

        router = MSTeamsCommandRouter()
        ctx = MagicMock()
        result = await router.try_dispatch("hello world", ctx)
        assert result is False

    @pytest.mark.asyncio
    async def test_ignores_unregistered_command(self):
        """Unknown slash command returns False."""
        from parrot.integrations.msteams.commands import MSTeamsCommandRouter

        router = MSTeamsCommandRouter()
        ctx = MagicMock()
        result = await router.try_dispatch("/unknown_command", ctx)
        assert result is False

    @pytest.mark.asyncio
    async def test_empty_text_returns_false(self):
        """Empty text returns False."""
        from parrot.integrations.msteams.commands import MSTeamsCommandRouter

        router = MSTeamsCommandRouter()
        ctx = MagicMock()
        result = await router.try_dispatch("", ctx)
        assert result is False

    def test_register_normalizes_slash_prefix(self):
        """register strips leading '/' before storing."""
        from parrot.integrations.msteams.commands import MSTeamsCommandRouter

        router = MSTeamsCommandRouter()
        handler = AsyncMock()
        router.register("/connect_jira", handler)
        assert "connect_jira" in router.registered_commands

    @pytest.mark.asyncio
    async def test_register_and_dispatch_with_slash(self):
        """Commands registered with '/' are dispatched correctly."""
        from parrot.integrations.msteams.commands import MSTeamsCommandRouter

        router = MSTeamsCommandRouter()
        handler = AsyncMock()
        router.register("/my_cmd", handler)

        ctx = MagicMock()
        result = await router.try_dispatch("/my_cmd", ctx)
        assert result is True


# ---------------------------------------------------------------------------
# connect_jira_handler tests
# ---------------------------------------------------------------------------

class TestConnectJiraTeams:
    @pytest.mark.asyncio
    async def test_generates_auth_url_and_sends_card(self, mock_oauth_manager):
        """connect_jira_handler sends Adaptive Card with auth URL."""
        from parrot.integrations.msteams.commands.jira_commands import connect_jira_handler

        ctx, mock_conv_ref = _make_turn_context()

        with patch(
            "parrot.integrations.msteams.commands.jira_commands.TurnContext"
        ) as mock_tc:
            mock_tc.get_conversation_reference = MagicMock(return_value=mock_conv_ref)
            await connect_jira_handler(ctx, mock_oauth_manager)

        mock_oauth_manager.validate_token.assert_called_once()
        mock_oauth_manager.create_authorization_url.assert_called_once()
        ctx.send_activity.assert_called_once()

        # Check extra_state contains channel
        call_args = mock_oauth_manager.create_authorization_url.call_args
        extra_state = call_args.kwargs.get("extra_state", {}) or (
            call_args.args[2] if len(call_args.args) > 2 else {}
        )
        assert extra_state.get("channel") == "msteams"

    @pytest.mark.asyncio
    async def test_already_connected_sends_text_not_card(self, mock_oauth_manager):
        """When already connected, sends text reply not an Adaptive Card."""
        from parrot.integrations.msteams.commands.jira_commands import connect_jira_handler

        token = MagicMock()
        token.display_name = "Jane Doe"
        mock_oauth_manager.validate_token = AsyncMock(return_value=token)

        ctx, _ = _make_turn_context()
        await connect_jira_handler(ctx, mock_oauth_manager)

        mock_oauth_manager.create_authorization_url.assert_not_called()
        ctx.send_activity.assert_called_once()
        activity = ctx.send_activity.call_args[0][0]
        # Should be a plain text reply
        assert "already" in activity.text.lower() or "Already" in activity.text

    @pytest.mark.asyncio
    async def test_uses_aad_object_id(self, mock_oauth_manager):
        """User ID is the aad_object_id when available."""
        from parrot.integrations.msteams.commands.jira_commands import connect_jira_handler

        ctx, mock_conv_ref = _make_turn_context(aad_object_id="aad-unique-123")

        with patch(
            "parrot.integrations.msteams.commands.jira_commands.TurnContext"
        ) as mock_tc:
            mock_tc.get_conversation_reference = MagicMock(return_value=mock_conv_ref)
            await connect_jira_handler(ctx, mock_oauth_manager)

        call_args = mock_oauth_manager.validate_token.call_args[0]
        assert call_args[0] == "msteams"
        assert call_args[1] == "aad-unique-123"


# ---------------------------------------------------------------------------
# disconnect_jira_handler tests
# ---------------------------------------------------------------------------

class TestDisconnectJiraTeams:
    @pytest.mark.asyncio
    async def test_revokes_token(self, mock_oauth_manager):
        """disconnect_jira_handler calls oauth_manager.revoke."""
        from parrot.integrations.msteams.commands.jira_commands import disconnect_jira_handler

        ctx, _ = _make_turn_context()
        await disconnect_jira_handler(ctx, mock_oauth_manager)

        mock_oauth_manager.revoke.assert_called_once_with("msteams", "aad-obj-123")
        ctx.send_activity.assert_called_once()
        activity = ctx.send_activity.call_args[0][0]
        assert "disconnected" in activity.text.lower()


# ---------------------------------------------------------------------------
# jira_status_handler tests
# ---------------------------------------------------------------------------

class TestJiraStatusTeams:
    @pytest.mark.asyncio
    async def test_connected_status(self, mock_oauth_manager):
        """Returns display_name and site_url when connected."""
        from parrot.integrations.msteams.commands.jira_commands import jira_status_handler

        token = MagicMock()
        token.display_name = "Jane Doe"
        token.site_url = "https://myco.atlassian.net"
        mock_oauth_manager.validate_token = AsyncMock(return_value=token)

        ctx, _ = _make_turn_context()
        await jira_status_handler(ctx, mock_oauth_manager)

        ctx.send_activity.assert_called_once()
        activity = ctx.send_activity.call_args[0][0]
        assert "Jane Doe" in activity.text
        assert "myco.atlassian.net" in activity.text

    @pytest.mark.asyncio
    async def test_not_connected_status(self, mock_oauth_manager):
        """Returns 'not connected' message when no token."""
        from parrot.integrations.msteams.commands.jira_commands import jira_status_handler

        ctx, _ = _make_turn_context()
        await jira_status_handler(ctx, mock_oauth_manager)

        ctx.send_activity.assert_called_once()
        activity = ctx.send_activity.call_args[0][0]
        assert "not connected" in activity.text.lower()


# ---------------------------------------------------------------------------
# register_jira_commands tests
# ---------------------------------------------------------------------------

class TestRegisterJiraCommandsTeams:
    def test_registers_commands(self, mock_oauth_manager):
        """register_jira_commands registers all expected commands."""
        from parrot.integrations.msteams.commands import MSTeamsCommandRouter
        from parrot.integrations.msteams.commands.jira_commands import register_jira_commands

        router = MSTeamsCommandRouter()
        register_jira_commands(router, mock_oauth_manager)

        assert "connect_jira" in router.registered_commands
        assert "disconnect_jira" in router.registered_commands
        assert "jira_status" in router.registered_commands

    @pytest.mark.asyncio
    async def test_registered_connect_dispatches(self, mock_oauth_manager):
        """Dispatching /connect_jira calls the handler."""
        from parrot.integrations.msteams.commands import MSTeamsCommandRouter
        from parrot.integrations.msteams.commands.jira_commands import register_jira_commands

        router = MSTeamsCommandRouter()
        register_jira_commands(router, mock_oauth_manager)

        ctx, mock_conv_ref = _make_turn_context()
        with patch(
            "parrot.integrations.msteams.commands.jira_commands.TurnContext"
        ) as mock_tc:
            mock_tc.get_conversation_reference = MagicMock(return_value=mock_conv_ref)
            result = await router.try_dispatch("/connect_jira", ctx)

        assert result is True


# ---------------------------------------------------------------------------
# Menu card contract (Bug 2 regression)
# ---------------------------------------------------------------------------

class TestJiraMenuCard:
    """The discoverability menu card's buttons are Action.Submit actions that
    carry a slash-prefixed ``command`` in their ``data``. The wrapper's
    _handle_card_submission relies on this key to route the click through the
    command router (otherwise the buttons silently no-op).
    """

    def test_menu_buttons_carry_slash_command_data(self):
        from parrot.integrations.msteams.commands.jira_commands import _jira_menu_card

        card = _jira_menu_card()
        actions = card["actions"]
        assert all(a["type"] == "Action.Submit" for a in actions)

        commands = {a["data"]["command"] for a in actions}
        assert commands == {"/connect_jira", "/disconnect_jira", "/jira_status"}
        # Every command is slash-prefixed so try_dispatch (which requires a
        # leading "/") will accept it.
        assert all(c.startswith("/") for c in commands)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

def test_msteams_channel_constant():
    """_MSTEAMS_CHANNEL is 'msteams'."""
    from parrot.integrations.msteams.commands.jira_commands import _MSTEAMS_CHANNEL
    assert _MSTEAMS_CHANNEL == "msteams"
