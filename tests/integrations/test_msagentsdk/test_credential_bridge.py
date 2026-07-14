"""
Unit tests for the credential context bridge in ParrotM365Agent._handle_message.

Covers FEAT-261 Module 4 (Credential Context Bridge) and
Module 7 (Sign-in Card Emission).
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class MockFromProperty:
    def __init__(self, channel_id="user-123", aad_id=None):
        self.id = channel_id
        self.aad_object_id = aad_id
        self.name = "Test User"


class MockActivity:
    def __init__(self, text="Hello", from_id="user-123", aad_id=None, conv_id="conv-456"):
        self.type = "message"
        self.text = text
        self.from_property = MockFromProperty(from_id, aad_id)
        self.conversation = MagicMock(id=conv_id)
        self.recipient = MagicMock(id="bot-id")
        self.members_added = None


class MockTurnContext:
    def __init__(self, activity):
        self.activity = activity
        self.sent_activities = []

    async def send_activity(self, act):
        self.sent_activities.append(act)


class TestCredentialContextBridge:
    """Tests for _pctx_var and RequestContext wiring in _handle_message."""

    def _make_agent(self, bot=None):
        from parrot.integrations.msagentsdk.agent import ParrotM365Agent

        mock_bot = bot or AsyncMock()
        if not hasattr(mock_bot, "ask") or not callable(mock_bot.ask):
            mock_bot.ask = AsyncMock(return_value=MagicMock(content="reply"))
        return ParrotM365Agent(parrot_agent=mock_bot)

    @pytest.mark.asyncio
    async def test_message_passes_ctx_to_ask(self):
        """ask() receives ctx=RequestContext(user_id=..., session_id=...)."""
        from parrot.integrations.msagentsdk.agent import ParrotM365Agent
        from parrot.utils.helpers import RequestContext

        mock_bot = AsyncMock()
        captured_kwargs = {}

        async def capturing_ask(**kwargs):
            captured_kwargs.update(kwargs)
            return MagicMock(content="reply")

        mock_bot.ask = capturing_ask
        agent = ParrotM365Agent(parrot_agent=mock_bot)

        activity = MockActivity(
            text="What is my schedule?",
            aad_id="00000000-0000-0000-0000-000000000001",
            conv_id="session-abc",
        )
        ctx = MockTurnContext(activity)

        import sys
        from unittest.mock import patch, MagicMock as MM

        mock_am = MM()
        mock_am.ActivityTypes.message = "message"
        mock_am.ActivityTypes.conversation_update = "conversationUpdate"
        mock_am.Activity = MM(return_value=MM(type="message", text=None, text_format=None))
        mock_am.TextFormatTypes.plain = "plain"

        with patch.dict(sys.modules, {"microsoft_agents.activity": mock_am}):
            await agent._handle_message(ctx)

        assert "ctx" in captured_kwargs
        assert isinstance(captured_kwargs["ctx"], RequestContext)
        assert captured_kwargs["user_id"] == "00000000-0000-0000-0000-000000000001"
        assert captured_kwargs["session_id"] == "session-abc"

    @pytest.mark.asyncio
    async def test_message_sets_pctx_var(self):
        """_handle_message sets _pctx_var with PermissionContext."""
        from parrot.integrations.msagentsdk.agent import ParrotM365Agent
        from parrot.auth.context import _pctx_var
        from parrot.auth.permission import PermissionContext

        captured_pctx = {}

        async def capturing_ask(**kwargs):
            captured_pctx["pctx"] = _pctx_var.get()
            return MagicMock(content="ok")

        mock_bot = AsyncMock()
        mock_bot.ask = capturing_ask
        agent = ParrotM365Agent(parrot_agent=mock_bot)

        activity = MockActivity(
            text="Hello",
            aad_id="entra-user-id",
        )
        ctx = MockTurnContext(activity)

        import sys
        from unittest.mock import patch, MagicMock as MM

        mock_am = MM()
        mock_am.ActivityTypes.message = "message"
        mock_am.ActivityTypes.conversation_update = "conversationUpdate"
        mock_am.Activity = MM(return_value=MM(type="message", text=None, text_format=None))
        mock_am.TextFormatTypes.plain = "plain"

        with patch.dict(sys.modules, {"microsoft_agents.activity": mock_am}):
            await agent._handle_message(ctx)

        pctx = captured_pctx.get("pctx")
        assert pctx is not None
        assert isinstance(pctx, PermissionContext)
        assert pctx.channel == "msagentsdk"
        assert pctx.user_id == "entra-user-id"

    @pytest.mark.asyncio
    async def test_pctx_var_reset_after_message(self):
        """_pctx_var is reset to None after _handle_message completes."""
        from parrot.integrations.msagentsdk.agent import ParrotM365Agent
        from parrot.auth.context import _pctx_var

        mock_bot = AsyncMock()
        mock_bot.ask = AsyncMock(return_value=MagicMock(content="ok"))
        agent = ParrotM365Agent(parrot_agent=mock_bot)

        activity = MockActivity(text="Test", aad_id="user-1")
        ctx = MockTurnContext(activity)

        # Set pctx_var to None before the call
        token = _pctx_var.set(None)

        import sys
        from unittest.mock import patch, MagicMock as MM

        mock_am = MM()
        mock_am.ActivityTypes.message = "message"
        mock_am.ActivityTypes.conversation_update = "conversationUpdate"
        mock_am.Activity = MM(return_value=MM(type="message", text=None, text_format=None))
        mock_am.TextFormatTypes.plain = "plain"

        with patch.dict(sys.modules, {"microsoft_agents.activity": mock_am}):
            await agent._handle_message(ctx)

        # After the call, _pctx_var should be back to None (reset)
        assert _pctx_var.get() is None, "_pctx_var must be reset after _handle_message"
        _pctx_var.reset(token)

    @pytest.mark.asyncio
    async def test_pctx_var_reset_on_credential_required(self):
        """_pctx_var is reset even when CredentialRequired is raised."""
        from parrot.integrations.msagentsdk.agent import ParrotM365Agent
        from parrot.auth.context import _pctx_var
        from parrot.auth.credentials import CredentialRequired

        async def ask_raises(**kwargs):
            raise CredentialRequired(
                provider="graph_sso",
                auth_url="https://login.example/consent",
                auth_kind="oauth2",
            )

        mock_bot = AsyncMock()
        mock_bot.ask = ask_raises
        agent = ParrotM365Agent(parrot_agent=mock_bot)

        activity = MockActivity(text="Show calendar", aad_id="user-1")
        ctx = MockTurnContext(activity)

        # Set _pctx_var to None before the call
        token = _pctx_var.set(None)

        import sys
        from unittest.mock import patch, MagicMock as MM

        mock_am = MM()
        mock_am.ActivityTypes.message = "message"
        mock_am.ActivityTypes.conversation_update = "conversationUpdate"
        sent_act = MM()
        mock_am.Activity = MM(return_value=sent_act)

        with patch.dict(sys.modules, {"microsoft_agents.activity": mock_am}):
            await agent._handle_message(ctx)

        # _pctx_var must be reset even after CredentialRequired was raised
        assert _pctx_var.get() is None, "_pctx_var must be reset after CredentialRequired"
        _pctx_var.reset(token)


class TestSigninCardEmission:
    """Tests for OAuthCard emission on CredentialRequired."""

    def _make_agent(self):
        from parrot.integrations.msagentsdk.agent import ParrotM365Agent

        mock_bot = AsyncMock()
        return ParrotM365Agent(parrot_agent=mock_bot)

    @pytest.mark.asyncio
    async def test_credential_required_emits_oauth_card(self):
        """CredentialRequired exception triggers OAuthCard emission."""
        from parrot.integrations.msagentsdk.agent import ParrotM365Agent
        from parrot.auth.credentials import CredentialRequired

        async def ask_raises(**kwargs):
            raise CredentialRequired(
                provider="graph_sso",
                auth_url="https://login.example/consent",
                auth_kind="oauth2",
            )

        mock_bot = AsyncMock()
        mock_bot.ask = ask_raises
        agent = ParrotM365Agent(parrot_agent=mock_bot)

        activity = MockActivity(text="Show calendar", aad_id="user-1")
        ctx = MockTurnContext(activity)

        import sys
        from unittest.mock import patch, MagicMock as MM

        mock_am = MM()
        mock_am.ActivityTypes.message = "message"
        mock_am.ActivityTypes.conversation_update = "conversationUpdate"
        sent_act = MM()
        mock_am.Activity = MM(return_value=sent_act)

        with patch.dict(sys.modules, {"microsoft_agents.activity": mock_am}):
            await agent._handle_message(ctx)

        # OAuthCard activity should have been sent
        assert len(ctx.sent_activities) == 1

    @pytest.mark.asyncio
    async def test_no_service_fallback_on_credential_required(self):
        """CredentialRequired never sends a text answer (no service fallback)."""
        from parrot.integrations.msagentsdk.agent import ParrotM365Agent
        from parrot.auth.credentials import CredentialRequired

        async def ask_raises(**kwargs):
            raise CredentialRequired(
                provider="graph_sso",
                auth_url="https://login.example/consent",
                auth_kind="oauth2",
            )

        mock_bot = AsyncMock()
        mock_bot.ask = ask_raises
        agent = ParrotM365Agent(parrot_agent=mock_bot)

        activity = MockActivity(text="Show calendar", aad_id="user-1")
        ctx = MockTurnContext(activity)

        import sys
        from unittest.mock import patch, MagicMock as MM

        mock_am = MM()
        mock_am.ActivityTypes.message = "message"
        mock_am.ActivityTypes.conversation_update = "conversationUpdate"
        mock_am.Activity = MM(return_value=MM())

        with patch.dict(sys.modules, {"microsoft_agents.activity": mock_am}):
            await agent._handle_message(ctx)

        # Exactly one activity (the OAuth card) — no error text
        assert len(ctx.sent_activities) == 1
        # The sent activity should be an OAuthCard, not a plain text "Sorry..." message
        sent = ctx.sent_activities[0]
        # It should NOT be the error message
        text = getattr(sent, "text", None) or ""
        assert "error" not in text.lower()
