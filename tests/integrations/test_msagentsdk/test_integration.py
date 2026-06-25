"""
End-to-end integration test for the MS Agent SDK flow.

Simulates the full path: Activity JSON -> wrapper -> ParrotM365Agent -> mock
bot -> response, using mocked SDK internals so no real Azure connection is
required.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from aiohttp import web


class TestEndToEndMessageFlow:
    """Full pipeline: Activity arrives at wrapper, agent replies."""

    @pytest.mark.asyncio
    async def test_message_routes_to_agent_and_back(self):
        """POST Activity -> ParrotM365Agent.on_turn() -> mock bot -> response."""
        from parrot.integrations.msagentsdk.agent import ParrotM365Agent

        # Set up mock bot
        mock_bot = AsyncMock()
        mock_bot.ask = AsyncMock(return_value=MagicMock(content="42 is the answer"))

        # Set up bridge agent directly (no SDK needed for this layer)
        bridge = ParrotM365Agent(parrot_agent=mock_bot, welcome_message="Hi!")

        # Build a fake TurnContext
        ctx = AsyncMock()
        ctx.activity = MagicMock()
        ctx.activity.from_property = MagicMock(id="user-001")
        ctx.activity.conversation = MagicMock(id="conv-001")
        ctx.activity.recipient = MagicMock(id="bot-001")
        ctx.activity.text = "What is the meaning of life?"
        ctx.send_activity = AsyncMock()

        # Simulate on_turn with a mocked ActivityTypes
        mock_at = MagicMock()
        mock_at.message = "message"
        mock_at.conversation_update = "conversationUpdate"
        ctx.activity.type = "message"

        with patch.dict(
            "sys.modules",
            {"microsoft_agents.activity": MagicMock(ActivityTypes=mock_at)},
        ):
            await bridge.on_turn(ctx)

        mock_bot.ask.assert_awaited_once_with(
            question="What is the meaning of life?",
            session_id="conv-001",
            user_id="user-001",
        )
        ctx.send_activity.assert_awaited_once_with("42 is the answer")

    @pytest.mark.asyncio
    async def test_wrapper_process_called(self):
        """MSAgentSDKWrapper.handle_request delegates to adapter.process()."""
        from parrot.integrations.msagentsdk.models import MSAgentSDKConfig

        cfg = MSAgentSDKConfig(
            name="E2EBot", chatbot_id="e2e_agent", anonymous_auth=True
        )
        app = web.Application()
        mock_bot = AsyncMock()

        mock_adapter_cls = MagicMock()
        mock_adapter = AsyncMock()
        mock_adapter.process = AsyncMock(return_value=web.Response(text="ok"))
        mock_adapter_cls.return_value = mock_adapter

        with patch.dict(
            "sys.modules",
            {
                "microsoft_agents": MagicMock(),
                "microsoft_agents.hosting": MagicMock(),
                "microsoft_agents.hosting.aiohttp": MagicMock(
                    CloudAdapter=mock_adapter_cls
                ),
            },
        ):
            from parrot.integrations.msagentsdk.wrapper import MSAgentSDKWrapper

            wrapper = MSAgentSDKWrapper(mock_bot, cfg, app)
            fake_request = MagicMock()
            response = await wrapper.handle_request(fake_request)

        mock_adapter.process.assert_awaited_once_with(
            fake_request, wrapper.m365_agent
        )
        assert response.text == "ok"

    @pytest.mark.asyncio
    async def test_conversation_update_sends_welcome(self):
        """New member joining triggers welcome message end-to-end."""
        from parrot.integrations.msagentsdk.agent import ParrotM365Agent

        mock_bot = AsyncMock()
        bridge = ParrotM365Agent(
            parrot_agent=mock_bot, welcome_message="Welcome aboard!"
        )

        ctx = AsyncMock()
        ctx.activity = MagicMock()
        ctx.activity.type = "conversationUpdate"
        ctx.activity.recipient = MagicMock(id="bot-001")
        new_member = MagicMock(id="new-user-999")
        ctx.activity.members_added = [new_member]
        ctx.send_activity = AsyncMock()

        mock_at = MagicMock()
        mock_at.message = "message"
        mock_at.conversation_update = "conversationUpdate"

        with patch.dict(
            "sys.modules",
            {"microsoft_agents.activity": MagicMock(ActivityTypes=mock_at)},
        ):
            await bridge.on_turn(ctx)

        ctx.send_activity.assert_awaited_once_with("Welcome aboard!")

    @pytest.mark.asyncio
    async def test_unknown_activity_type_ignored(self):
        """Unknown activity type doesn't crash and doesn't call ask()."""
        from parrot.integrations.msagentsdk.agent import ParrotM365Agent

        mock_bot = AsyncMock()
        mock_bot.ask = AsyncMock()
        bridge = ParrotM365Agent(parrot_agent=mock_bot)

        ctx = AsyncMock()
        ctx.activity = MagicMock()
        ctx.activity.type = "deleteUserData"
        ctx.send_activity = AsyncMock()

        mock_at = MagicMock()
        mock_at.message = "message"
        mock_at.conversation_update = "conversationUpdate"

        with patch.dict(
            "sys.modules",
            {"microsoft_agents.activity": MagicMock(ActivityTypes=mock_at)},
        ):
            await bridge.on_turn(ctx)

        mock_bot.ask.assert_not_called()
        ctx.send_activity.assert_not_called()
