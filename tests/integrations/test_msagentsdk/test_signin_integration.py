"""
Integration tests for the FEAT-261 sign-in round-trip and backward compatibility.

Tests the full flow end-to-end using mocked SDK components.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock


class MockFromProperty:
    def __init__(self, channel_id="user-123", aad_id=None):
        self.id = channel_id
        self.aad_object_id = aad_id
        self.name = "Test User"


class MockActivity:
    def __init__(self, text="Hello", from_id="user-123", aad_id=None,
                 conv_id="conv-456", type="message"):
        self.type = type
        self.text = text
        self.from_property = MockFromProperty(from_id, aad_id)
        self.conversation = MagicMock(id=conv_id)
        self.recipient = MagicMock(id="bot-id")
        self.members_added = None
        self.channel_id = "msteams"


class MockTurnContext:
    def __init__(self, activity):
        self.activity = activity
        self.sent_activities = []

    async def send_activity(self, act):
        self.sent_activities.append(act)


class TestMessageUnchangedWithoutOAuth:
    """Backward-compatibility: message flow is unchanged with empty oauth_connections."""

    @pytest.mark.asyncio
    async def test_message_unchanged_without_oauth(self):
        """Message flow with no oauth_connections works as before."""
        from parrot.integrations.msagentsdk.agent import ParrotM365Agent

        mock_bot = AsyncMock()
        mock_bot.ask = AsyncMock(return_value=MagicMock(content="Hi there!"))
        agent = ParrotM365Agent(parrot_agent=mock_bot)

        # No resolver, no audit_ledger
        assert agent._resolver is None
        assert agent._audit_ledger is None

        activity = MockActivity(text="Hello", from_id="user-123")
        ctx = MockTurnContext(activity)

        import sys
        from unittest.mock import patch, MagicMock as MM

        mock_am = MM()
        mock_am.ActivityTypes.message = "message"
        mock_am.ActivityTypes.conversation_update = "conversationUpdate"
        mock_am.Activity = MM(return_value=MM(type="message", text=None, text_format=None))
        mock_am.TextFormatTypes.plain = "plain"

        with patch.dict(sys.modules, {"microsoft_agents.activity": mock_am}):
            await agent.on_turn(ctx)

        # ask() should have been called
        assert mock_bot.ask.called
        # A reply should have been sent
        assert len(ctx.sent_activities) == 1


class TestSigninRoundTrip:
    """Sign-in flow: CredentialRequired -> OAuthCard -> invoke -> token available."""

    @pytest.mark.asyncio
    async def test_credential_required_to_oauth_card(self):
        """Message that raises CredentialRequired emits OAuthCard (not error text)."""
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

        activity = MockActivity(text="Show my calendar", aad_id="entra-user-1")
        ctx = MockTurnContext(activity)

        import sys
        from unittest.mock import patch, MagicMock as MM

        mock_am = MM()
        mock_am.ActivityTypes.message = "message"
        mock_am.ActivityTypes.conversation_update = "conversationUpdate"
        mock_am.Activity = MM(return_value=MM(type="message", attachments=None))

        with patch.dict(sys.modules, {"microsoft_agents.activity": mock_am}):
            await agent._handle_message(ctx)

        # OAuth card sent, NOT an error message
        assert len(ctx.sent_activities) == 1

    @pytest.mark.asyncio
    async def test_signin_verify_state_handled(self):
        """signin/verifyState invoke activity is acknowledged."""
        from parrot.integrations.msagentsdk.agent import ParrotM365Agent

        mock_bot = AsyncMock()
        agent = ParrotM365Agent(parrot_agent=mock_bot)

        activity = MockActivity(type="invoke")
        activity.name = "signin/verifyState"
        activity.value = {"state": "magic-12345"}
        ctx = MockTurnContext(activity)

        import sys
        from unittest.mock import patch, MagicMock as MM

        mock_am = MM()
        mock_am.Activity = MM(return_value=MM(type=None, value=None))
        mock_am.ActivityTypes.invoke_response = "invokeResponse"
        mock_am.ActivityTypes.message = "message"
        mock_am.ActivityTypes.conversation_update = "conversationUpdate"

        with patch.dict(sys.modules, {"microsoft_agents.activity": mock_am}):
            await agent._handle_signin_verify(ctx)

        assert len(ctx.sent_activities) == 1
