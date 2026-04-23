"""Unit tests for FEAT-120 attachment passthrough in _invoke_agent.

Tests verify that:
- _invoke_agent accepts and forwards an optional `attachments` parameter
- handle_photo's else-branch uses _invoke_agent instead of agent.ask directly
- Debug logs are emitted when attachments are present
- Existing callers without attachments are unaffected (backward compat)
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call


def _make_wrapper(singleton_agent: bool = True):
    """Create a minimal TelegramAgentWrapper mock for testing."""
    from parrot.integrations.telegram.wrapper import TelegramAgentWrapper
    from parrot.integrations.telegram.models import TelegramAgentConfig

    config = TelegramAgentConfig(
        name="test-bot",
        chatbot_id="testbot",
        singleton_agent=singleton_agent,
    )

    agent = MagicMock()
    agent.ask = AsyncMock(return_value="agent response")
    agent.tool_manager = MagicMock()
    agent.tool_manager.tool_count = MagicMock(return_value=0)
    agent.enable_tools = False

    bot = MagicMock()

    wrapper = TelegramAgentWrapper.__new__(TelegramAgentWrapper)
    wrapper.config = config
    wrapper.agent = agent
    wrapper.bot = bot
    wrapper.logger = MagicMock()
    wrapper._agent_lock = asyncio.Lock()
    wrapper._user_sessions = {}
    wrapper.conversations = {}
    wrapper._message_id_cache = {}
    return wrapper, agent


def _make_session():
    """Create a minimal TelegramUserSession mock."""
    session = MagicMock()
    session.user_id = "user123"
    session.session_id = "sess456"
    session.telegram_id = 99999
    return session


@pytest.mark.asyncio
class TestInvokeAgentAttachments:
    """Tests for the attachments parameter on _invoke_agent."""

    async def test_invoke_agent_forwards_attachments(self):
        """attachments kwarg reaches agent.ask() in per-user mode."""
        wrapper, agent = _make_wrapper(singleton_agent=False)
        session = _make_session()
        memory = MagicMock()

        # Patch internal helpers
        wrapper._resolve_agent_for_request = AsyncMock(return_value=(agent, None))
        wrapper._build_permission_context = MagicMock(return_value={})
        wrapper._enrich_question = MagicMock(side_effect=lambda q, s: q)

        await wrapper._invoke_agent(
            session,
            "Test question",
            memory=memory,
            attachments=["/tmp/photo.jpg"],
        )

        agent.ask.assert_awaited_once()
        call_kwargs = agent.ask.call_args.kwargs
        assert call_kwargs.get("attachments") == ["/tmp/photo.jpg"]

    async def test_invoke_agent_no_attachments_default(self):
        """When no attachments passed, agent.ask() receives attachments=None (backward compat)."""
        wrapper, agent = _make_wrapper(singleton_agent=False)
        session = _make_session()
        memory = MagicMock()

        wrapper._resolve_agent_for_request = AsyncMock(return_value=(agent, None))
        wrapper._build_permission_context = MagicMock(return_value={})
        wrapper._enrich_question = MagicMock(side_effect=lambda q, s: q)

        await wrapper._invoke_agent(
            session,
            "Test question",
            memory=memory,
        )

        agent.ask.assert_awaited_once()
        call_kwargs = agent.ask.call_args.kwargs
        # attachments should be None (not omitted to avoid breaking callers)
        assert call_kwargs.get("attachments") is None

    async def test_invoke_agent_logs_attachment_paths(self):
        """Debug log entries include attachment file paths when attachments provided."""
        wrapper, agent = _make_wrapper(singleton_agent=False)
        session = _make_session()
        memory = MagicMock()

        wrapper._resolve_agent_for_request = AsyncMock(return_value=(agent, None))
        wrapper._build_permission_context = MagicMock(return_value={})
        wrapper._enrich_question = MagicMock(side_effect=lambda q, s: q)

        await wrapper._invoke_agent(
            session,
            "Test question",
            memory=memory,
            attachments=["/tmp/photo.jpg"],
        )

        # At least one debug call should reference the attachment path
        debug_calls = [str(c) for c in wrapper.logger.debug.call_args_list]
        assert any("/tmp/photo.jpg" in dc for dc in debug_calls), (
            f"Expected debug log with attachment path, got: {debug_calls}"
        )

    async def test_invoke_agent_no_log_without_attachments(self):
        """No attachment debug log when attachments is None."""
        wrapper, agent = _make_wrapper(singleton_agent=False)
        session = _make_session()
        memory = MagicMock()

        wrapper._resolve_agent_for_request = AsyncMock(return_value=(agent, None))
        wrapper._build_permission_context = MagicMock(return_value={})
        wrapper._enrich_question = MagicMock(side_effect=lambda q, s: q)
        wrapper.logger.debug = MagicMock()

        await wrapper._invoke_agent(
            session,
            "Test question",
            memory=memory,
        )

        # No debug calls about attachments
        debug_calls_str = str(wrapper.logger.debug.call_args_list)
        assert "attachments" not in debug_calls_str


@pytest.mark.asyncio
class TestHandlePhotoRefactor:
    """Tests for handle_photo refactor — else-branch uses _invoke_agent."""

    async def _make_photo_message(self, chat_id: int = 12345, caption: str = "test"):
        """Create a mock photo Message."""
        message = MagicMock()
        message.chat.id = chat_id
        message.caption = caption
        message.message_id = 100
        message.from_user.id = 999

        photo = MagicMock()
        photo.file_id = "file_id_abc"
        message.photo = [photo]
        message.answer = AsyncMock()
        return message

    async def test_handle_photo_uses_invoke_agent(self):
        """Photo handler (non-multimodal path) calls _invoke_agent with attachments."""
        from parrot.integrations.telegram.wrapper import TelegramAgentWrapper
        from parrot.integrations.telegram.models import TelegramAgentConfig
        import tempfile
        from pathlib import Path

        config = TelegramAgentConfig(name="test-bot", chatbot_id="testbot")
        agent = MagicMock()
        # No ask_with_image → goes to else branch
        del agent.ask_with_image
        agent.ask = AsyncMock(return_value="response")

        bot = MagicMock()
        file_obj = MagicMock()
        file_obj.file_path = "photos/test.jpg"
        bot.get_file = AsyncMock(return_value=file_obj)
        bot.download_file = AsyncMock()
        bot.send_chat_action = AsyncMock()

        wrapper = TelegramAgentWrapper.__new__(TelegramAgentWrapper)
        wrapper.config = config
        wrapper.agent = agent
        wrapper.bot = bot
        wrapper.logger = MagicMock()
        wrapper._agent_lock = asyncio.Lock()
        wrapper._user_sessions = {}
        wrapper.conversations = {}
        wrapper._message_id_cache = {}

        message = await self._make_photo_message()
        memory = MagicMock()
        session = _make_session()

        wrapper._is_authorized = MagicMock(return_value=True)
        wrapper._check_authentication = AsyncMock(return_value=True)
        wrapper._get_or_create_memory = MagicMock(return_value=memory)
        wrapper._get_user_session = MagicMock(return_value=session)
        wrapper._invoke_agent = AsyncMock(return_value="agent_response")
        wrapper._parse_response = MagicMock(return_value=MagicMock())
        wrapper._send_parsed_response = AsyncMock()

        await wrapper.handle_photo(message)

        # _invoke_agent should have been called (not agent.ask directly)
        wrapper._invoke_agent.assert_awaited_once()
        call_kwargs = wrapper._invoke_agent.call_args.kwargs
        assert call_kwargs.get("attachments") is not None
        assert len(call_kwargs["attachments"]) == 1

    async def test_handle_photo_ask_with_image_still_works(self):
        """Photo handler multimodal path still calls ask_with_image directly."""
        from parrot.integrations.telegram.wrapper import TelegramAgentWrapper
        from parrot.integrations.telegram.models import TelegramAgentConfig

        config = TelegramAgentConfig(name="test-bot", chatbot_id="testbot")
        agent = MagicMock()
        # ask_with_image IS present → multimodal branch
        agent.ask_with_image = AsyncMock(return_value="multimodal response")

        bot = MagicMock()
        file_obj = MagicMock()
        file_obj.file_path = "photos/test.jpg"
        bot.get_file = AsyncMock(return_value=file_obj)
        bot.download_file = AsyncMock()
        bot.send_chat_action = AsyncMock()

        wrapper = TelegramAgentWrapper.__new__(TelegramAgentWrapper)
        wrapper.config = config
        wrapper.agent = agent
        wrapper.bot = bot
        wrapper.logger = MagicMock()
        wrapper._agent_lock = asyncio.Lock()
        wrapper._user_sessions = {}
        wrapper.conversations = {}
        wrapper._message_id_cache = {}

        message = await self._make_photo_message()
        memory = MagicMock()
        session = _make_session()

        wrapper._is_authorized = MagicMock(return_value=True)
        wrapper._check_authentication = AsyncMock(return_value=True)
        wrapper._get_or_create_memory = MagicMock(return_value=memory)
        wrapper._get_user_session = MagicMock(return_value=session)
        wrapper._enrich_question = MagicMock(side_effect=lambda q, s: q)
        wrapper._parse_response = MagicMock(return_value=MagicMock())
        wrapper._send_parsed_response = AsyncMock()

        await wrapper.handle_photo(message)

        # ask_with_image MUST have been called
        agent.ask_with_image.assert_awaited_once()
        call_kwargs = agent.ask_with_image.call_args.kwargs
        assert "image_path" in call_kwargs
        assert "attachments" in call_kwargs
