"""
Unit tests for ParrotM365Agent invoke activity routing.

Covers FEAT-261 Module 3 (Invoke Routing).
"""
import pytest
from unittest.mock import AsyncMock, MagicMock


class MockFromProperty:
    def __init__(self, channel_id="user-123"):
        self.id = channel_id
        self.aad_object_id = None


class MockActivity:
    def __init__(self, type="invoke", name=None, value=None):
        self.type = type
        self.text = None
        self.name = name
        self.value = value or {}
        self.from_property = MockFromProperty()
        self.conversation = MagicMock(id="conv-1")
        self.recipient = MagicMock(id="bot-id")
        self.members_added = None
        self.channel_id = "msteams"


class MockTurnContext:
    def __init__(self, activity):
        self.activity = activity
        self.sent_activities = []

    async def send_activity(self, act):
        self.sent_activities.append(act)


class TestInvokeRouting:
    """Tests for invoke activity routing in on_turn."""

    def _make_agent(self):
        from parrot.integrations.msagentsdk.agent import ParrotM365Agent

        mock_bot = AsyncMock()
        mock_bot.ask = AsyncMock(return_value=MagicMock(content="reply"))
        return ParrotM365Agent(parrot_agent=mock_bot)

    @pytest.mark.asyncio
    async def test_invoke_signin_verify_state(self):
        """signin/verifyState invoke is routed to _handle_signin_verify."""
        agent = self._make_agent()
        activity = MockActivity(
            type="invoke",
            name="signin/verifyState",
            value={"state": "magic-code-12345"},
        )
        ctx = MockTurnContext(activity)

        # Mock the ActivityTypes import inside on_turn
        with MagicMock() as mock_at:
            mock_at.message = "message"
            mock_at.conversation_update = "conversationUpdate"
            mock_at.invoke_response = "invokeResponse"

            import sys
            from unittest.mock import patch, MagicMock as MM

            mock_activity_module = MM()
            mock_activity_module.ActivityTypes.message = "message"
            mock_activity_module.ActivityTypes.conversation_update = "conversationUpdate"
            mock_activity_module.ActivityTypes.invoke_response = "invokeResponse"
            mock_activity_module.Activity = MM(return_value=MM())

            with patch.dict(sys.modules, {"microsoft_agents.activity": mock_activity_module}):
                await agent.on_turn(ctx)

        # Should have sent at least one invoke response
        assert len(ctx.sent_activities) >= 1

    @pytest.mark.asyncio
    async def test_invoke_unknown_ignored(self):
        """Unknown invoke type is silently ignored (no exception)."""
        agent = self._make_agent()
        activity = MockActivity(
            type="invoke",
            name="composeExtension/query",
        )
        ctx = MockTurnContext(activity)

        import sys
        from unittest.mock import patch, MagicMock as MM

        mock_activity_module = MM()
        mock_activity_module.ActivityTypes.message = "message"
        mock_activity_module.ActivityTypes.conversation_update = "conversationUpdate"

        with patch.dict(sys.modules, {"microsoft_agents.activity": mock_activity_module}):
            await agent.on_turn(ctx)

        # Unknown invoke: no activities sent
        assert len(ctx.sent_activities) == 0

    @pytest.mark.asyncio
    async def test_handle_signin_verify_directly(self):
        """_handle_signin_verify sends an invoke response."""
        agent = self._make_agent()
        activity = MockActivity(
            type="invoke",
            name="signin/verifyState",
            value={"state": "abc"},
        )
        ctx = MockTurnContext(activity)

        import sys
        from unittest.mock import patch, MagicMock as MM

        mock_activity_module = MM()
        mock_activity_module.Activity = MM(return_value=MM(type=None, value=None))
        mock_activity_module.ActivityTypes.invoke_response = "invokeResponse"

        with patch.dict(sys.modules, {"microsoft_agents.activity": mock_activity_module}):
            await agent._handle_signin_verify(ctx)

        assert len(ctx.sent_activities) == 1

    @pytest.mark.asyncio
    async def test_handle_signin_exchange_directly(self):
        """_handle_signin_exchange sends an invoke response."""
        agent = self._make_agent()
        activity = MockActivity(
            type="invoke",
            name="signin/tokenExchange",
            value={"connectionName": "graph_sso"},
        )
        ctx = MockTurnContext(activity)

        import sys
        from unittest.mock import patch, MagicMock as MM

        mock_activity_module = MM()
        mock_activity_module.Activity = MM(return_value=MM(type=None, value=None))
        mock_activity_module.ActivityTypes.invoke_response = "invokeResponse"

        with patch.dict(sys.modules, {"microsoft_agents.activity": mock_activity_module}):
            await agent._handle_signin_exchange(ctx)

        assert len(ctx.sent_activities) == 1
