"""Unit tests for SlackAssistantHandler.

Tests the Slack Agents & AI Apps integration including:
- Thread started event handling
- Context changed event handling
- User message processing
- Loading status management
- Suggested prompts
- Streaming responses
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# Mock wrapper and config for testing
@pytest.fixture
def mock_config():
    """Create mock SlackAgentConfig."""
    config = MagicMock()
    config.bot_token = "xoxb-test-token"
    config.enable_assistant = True
    config.welcome_message = "Hello! How can I help?"
    config.suggested_prompts = [
        {"title": "Test Prompt", "message": "Test message"},
    ]
    return config


@pytest.fixture
def mock_agent():
    """Create mock agent."""
    agent = MagicMock(spec=[])  # Empty spec to prevent auto-attributes
    agent.ask = AsyncMock(return_value="Test response")
    # Don't set ask_stream at all - we want hasattr to return False
    return agent


@pytest.fixture
def mock_wrapper(mock_config, mock_agent):
    """Create mock SlackAgentWrapper."""
    wrapper = MagicMock()
    wrapper.config = mock_config
    wrapper.agent = mock_agent
    wrapper._get_or_create_memory = MagicMock(return_value=MagicMock())
    wrapper._build_blocks = MagicMock(return_value=[
        {"type": "section", "text": {"type": "mrkdwn", "text": "Test response"}}
    ])
    return wrapper


@pytest.fixture
def assistant_handler(mock_wrapper):
    """Create SlackAssistantHandler instance."""
    from parrot.integrations.slack.assistant import SlackAssistantHandler
    return SlackAssistantHandler(mock_wrapper)


@pytest.fixture
def mock_aiohttp_session():
    """Create mock aiohttp ClientSession for API calls."""
    mock_response = MagicMock()
    mock_response.json = AsyncMock(return_value={"ok": True})
    mock_response.status = 200

    mock_context = MagicMock()
    mock_context.__aenter__ = AsyncMock(return_value=mock_response)
    mock_context.__aexit__ = AsyncMock(return_value=None)

    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=mock_context)

    session_context = MagicMock()
    session_context.__aenter__ = AsyncMock(return_value=mock_session)
    session_context.__aexit__ = AsyncMock(return_value=None)

    return session_context


class TestSlackAssistantHandlerInit:
    """Tests for SlackAssistantHandler initialization."""

    def test_init_sets_wrapper(self, assistant_handler, mock_wrapper):
        """Test that wrapper is set correctly."""
        assert assistant_handler.wrapper is mock_wrapper

    def test_init_sets_config(self, assistant_handler, mock_config):
        """Test that config is set from wrapper."""
        assert assistant_handler.config is mock_config

    def test_init_empty_thread_contexts(self, assistant_handler):
        """Test that thread contexts dict is empty initially."""
        assert assistant_handler._thread_contexts == {}

    def test_headers_property(self, assistant_handler):
        """Test that _headers returns proper authorization header."""
        headers = assistant_handler._headers
        assert headers["Authorization"] == "Bearer xoxb-test-token"
        assert headers["Content-Type"] == "application/json; charset=utf-8"


class TestHandleThreadStarted:
    """Tests for handle_thread_started method."""

    @pytest.mark.asyncio
    async def test_sends_welcome_message(self, assistant_handler, mock_aiohttp_session):
        """Test that welcome message is sent on thread start."""
        event = {
            "assistant_thread": {
                "channel_id": "C123",
                "thread_ts": "1234567890.123456",
                "context": {"channel_id": "C456"},
            }
        }

        with patch("parrot.integrations.slack.assistant.ClientSession", return_value=mock_aiohttp_session):
            await assistant_handler.handle_thread_started(event, {})

        # Verify context was stored
        assert "1234567890.123456" in assistant_handler._thread_contexts

    @pytest.mark.asyncio
    async def test_stores_thread_context(self, assistant_handler, mock_aiohttp_session):
        """Test that thread context is stored."""
        event = {
            "assistant_thread": {
                "channel_id": "C123",
                "thread_ts": "1234567890.123456",
                "context": {"channel_id": "C456", "team_id": "T789"},
            }
        }

        with patch("parrot.integrations.slack.assistant.ClientSession", return_value=mock_aiohttp_session):
            await assistant_handler.handle_thread_started(event, {})

        context = assistant_handler._thread_contexts.get("1234567890.123456")
        assert context == {"channel_id": "C456", "team_id": "T789"}

    @pytest.mark.asyncio
    async def test_missing_channel_returns_early(self, assistant_handler, mock_aiohttp_session):
        """Test that missing channel causes early return."""
        event = {
            "assistant_thread": {
                "thread_ts": "1234567890.123456",
            }
        }

        with patch("parrot.integrations.slack.assistant.ClientSession", return_value=mock_aiohttp_session) as mock_cls:
            await assistant_handler.handle_thread_started(event, {})

        # Should not have made any API calls
        mock_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_thread_ts_returns_early(self, assistant_handler, mock_aiohttp_session):
        """Test that missing thread_ts causes early return."""
        event = {
            "assistant_thread": {
                "channel_id": "C123",
            }
        }

        with patch("parrot.integrations.slack.assistant.ClientSession", return_value=mock_aiohttp_session) as mock_cls:
            await assistant_handler.handle_thread_started(event, {})

        # Should not have made any API calls
        mock_cls.assert_not_called()


class TestHandleContextChanged:
    """Tests for handle_context_changed method."""

    @pytest.mark.asyncio
    async def test_updates_thread_context(self, assistant_handler):
        """Test that context is updated for existing thread."""
        # Set initial context
        assistant_handler._thread_contexts["1234567890.123456"] = {"old": "context"}

        event = {
            "assistant_thread": {
                "thread_ts": "1234567890.123456",
                "context": {"new": "context", "channel_id": "C789"},
            }
        }

        await assistant_handler.handle_context_changed(event)

        assert assistant_handler._thread_contexts["1234567890.123456"] == {
            "new": "context",
            "channel_id": "C789",
        }

    @pytest.mark.asyncio
    async def test_creates_new_context_entry(self, assistant_handler):
        """Test that new context entry is created if thread not tracked."""
        event = {
            "assistant_thread": {
                "thread_ts": "9999999999.999999",
                "context": {"brand": "new"},
            }
        }

        await assistant_handler.handle_context_changed(event)

        assert assistant_handler._thread_contexts["9999999999.999999"] == {"brand": "new"}

    @pytest.mark.asyncio
    async def test_missing_thread_ts_does_nothing(self, assistant_handler):
        """Test that missing thread_ts is handled gracefully."""
        event = {
            "assistant_thread": {
                "context": {"some": "data"},
            }
        }

        initial_contexts = dict(assistant_handler._thread_contexts)
        await assistant_handler.handle_context_changed(event)

        assert assistant_handler._thread_contexts == initial_contexts


class TestHandleUserMessage:
    """Tests for handle_user_message method."""

    @pytest.mark.asyncio
    async def test_processes_message_with_agent(self, assistant_handler, mock_aiohttp_session):
        """Test that user message is processed through agent."""
        event = {
            "channel": "D123",
            "thread_ts": "1234567890.123456",
            "text": "Hello, assistant!",
            "user": "U456",
            "team": "T789",
        }

        with patch("parrot.integrations.slack.assistant.ClientSession", return_value=mock_aiohttp_session):
            with patch("parrot.integrations.slack.assistant.parse_response") as mock_parse:
                mock_parse.return_value = MagicMock(text="Response")
                await assistant_handler.handle_user_message(event)

        # Verify agent.ask was called
        assistant_handler.wrapper.agent.ask.assert_called_once()

    @pytest.mark.asyncio
    async def test_empty_text_returns_early(self, assistant_handler, mock_aiohttp_session):
        """Test that empty text causes early return."""
        event = {
            "channel": "D123",
            "text": "",
            "user": "U456",
        }

        with patch("parrot.integrations.slack.assistant.ClientSession", return_value=mock_aiohttp_session):
            await assistant_handler.handle_user_message(event)

        # Agent should not have been called
        assistant_handler.wrapper.agent.ask.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_channel_returns_early(self, assistant_handler, mock_aiohttp_session):
        """Test that missing channel causes early return."""
        event = {
            "text": "Hello",
            "user": "U456",
        }

        with patch("parrot.integrations.slack.assistant.ClientSession", return_value=mock_aiohttp_session):
            await assistant_handler.handle_user_message(event)

        # Agent should not have been called
        assistant_handler.wrapper.agent.ask.assert_not_called()

    @pytest.mark.asyncio
    async def test_sets_thread_title(self, assistant_handler, mock_aiohttp_session):
        """Test that thread title is set from message text."""
        event = {
            "channel": "D123",
            "thread_ts": "1234567890.123456",
            "text": "What is the weather today?",
            "user": "U456",
        }

        with patch("parrot.integrations.slack.assistant.ClientSession", return_value=mock_aiohttp_session) as mock_cls:
            with patch("parrot.integrations.slack.assistant.parse_response") as mock_parse:
                mock_parse.return_value = MagicMock(text="Response")
                await assistant_handler.handle_user_message(event)

        # Verify setTitle was called (one of the API calls)
        mock_session = await mock_cls().__aenter__()
        calls = mock_session.post.call_args_list
        assert len(calls) >= 1

    @pytest.mark.asyncio
    async def test_handles_agent_error(self, assistant_handler, mock_aiohttp_session):
        """Test that agent errors are handled gracefully."""
        event = {
            "channel": "D123",
            "thread_ts": "1234567890.123456",
            "text": "Cause an error",
            "user": "U456",
        }

        assistant_handler.wrapper.agent.ask = AsyncMock(
            side_effect=Exception("Agent error")
        )

        with patch("parrot.integrations.slack.assistant.ClientSession", return_value=mock_aiohttp_session):
            # Should not raise
            await assistant_handler.handle_user_message(event)


class TestStreamResponse:
    """Tests for _stream_response method."""

    @pytest.mark.asyncio
    async def test_fallback_without_slack_sdk(self, assistant_handler, mock_aiohttp_session):
        """Test fallback to non-streaming when slack-sdk not installed."""
        with patch("parrot.integrations.slack.assistant.ClientSession", return_value=mock_aiohttp_session):
            with patch("parrot.integrations.slack.assistant.parse_response") as mock_parse:
                mock_parse.return_value = MagicMock(text="Response")

                # Simulate ImportError for slack_sdk
                with patch.dict('sys.modules', {'slack_sdk': None, 'slack_sdk.web.async_client': None}):
                    await assistant_handler._stream_response(
                        channel="D123",
                        thread_ts="1234567890.123456",
                        text="Hello",
                        user="U456",
                        team="T789",
                        memory=MagicMock(),
                        session_id="test-session",
                    )

        # Should have called agent.ask (non-streaming fallback)
        assistant_handler.wrapper.agent.ask.assert_called()


class TestSlackAPIHelpers:
    """Tests for Slack API helper methods."""

    @pytest.mark.asyncio
    async def test_set_status(self, assistant_handler, mock_aiohttp_session):
        """Test _set_status makes correct API call."""
        with patch("parrot.integrations.slack.assistant.ClientSession", return_value=mock_aiohttp_session) as mock_cls:
            await assistant_handler._set_status(
                channel="C123",
                thread_ts="1234567890.123456",
                status="is thinking...",
                loading_messages=["Processing..."],
            )

        mock_session = await mock_cls().__aenter__()
        mock_session.post.assert_called()

        # Check the URL
        call_args = mock_session.post.call_args
        assert call_args[0][0] == "https://slack.com/api/assistant.threads.setStatus"

    @pytest.mark.asyncio
    async def test_clear_status(self, assistant_handler, mock_aiohttp_session):
        """Test _clear_status sets empty status."""
        with patch("parrot.integrations.slack.assistant.ClientSession", return_value=mock_aiohttp_session) as mock_cls:
            await assistant_handler._clear_status("C123", "1234567890.123456")

        mock_session = await mock_cls().__aenter__()
        call_args = mock_session.post.call_args
        payload = json.loads(call_args[1]["data"])
        assert payload["status"] == ""

    @pytest.mark.asyncio
    async def test_set_title(self, assistant_handler, mock_aiohttp_session):
        """Test _set_title makes correct API call."""
        with patch("parrot.integrations.slack.assistant.ClientSession", return_value=mock_aiohttp_session) as mock_cls:
            await assistant_handler._set_title(
                channel="C123",
                thread_ts="1234567890.123456",
                title="Test Title",
            )

        mock_session = await mock_cls().__aenter__()
        call_args = mock_session.post.call_args
        assert call_args[0][0] == "https://slack.com/api/assistant.threads.setTitle"

    @pytest.mark.asyncio
    async def test_set_title_truncates_long_title(self, assistant_handler, mock_aiohttp_session):
        """Test _set_title truncates title to 255 chars."""
        long_title = "x" * 300

        with patch("parrot.integrations.slack.assistant.ClientSession", return_value=mock_aiohttp_session) as mock_cls:
            await assistant_handler._set_title(
                channel="C123",
                thread_ts="1234567890.123456",
                title=long_title,
            )

        mock_session = await mock_cls().__aenter__()
        call_args = mock_session.post.call_args
        payload = json.loads(call_args[1]["data"])
        assert len(payload["title"]) == 255

    @pytest.mark.asyncio
    async def test_set_suggested_prompts(self, assistant_handler, mock_aiohttp_session):
        """Test _set_suggested_prompts makes correct API call."""
        prompts = [
            {"title": "Prompt 1", "message": "Message 1"},
            {"title": "Prompt 2", "message": "Message 2"},
        ]

        with patch("parrot.integrations.slack.assistant.ClientSession", return_value=mock_aiohttp_session) as mock_cls:
            await assistant_handler._set_suggested_prompts(
                channel="C123",
                thread_ts="1234567890.123456",
                prompts=prompts,
            )

        mock_session = await mock_cls().__aenter__()
        call_args = mock_session.post.call_args
        assert call_args[0][0] == "https://slack.com/api/assistant.threads.setSuggestedPrompts"

    @pytest.mark.asyncio
    async def test_post_message(self, assistant_handler, mock_aiohttp_session):
        """Test _post_message makes correct API call."""
        with patch("parrot.integrations.slack.assistant.ClientSession", return_value=mock_aiohttp_session) as mock_cls:
            await assistant_handler._post_message(
                channel="C123",
                text="Hello",
                blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": "Hello"}}],
                thread_ts="1234567890.123456",
            )

        mock_session = await mock_cls().__aenter__()
        call_args = mock_session.post.call_args
        assert call_args[0][0] == "https://slack.com/api/chat.postMessage"
        payload = json.loads(call_args[1]["data"])
        assert payload["channel"] == "C123"
        assert payload["text"] == "Hello"
        assert payload["thread_ts"] == "1234567890.123456"


class TestDefaultPrompts:
    """Tests for _default_prompts method."""

    def test_returns_list_of_prompts(self, assistant_handler):
        """Test that default prompts returns a list."""
        prompts = assistant_handler._default_prompts()
        assert isinstance(prompts, list)
        assert len(prompts) == 3

    def test_prompts_have_required_keys(self, assistant_handler):
        """Test that each prompt has title and message keys."""
        prompts = assistant_handler._default_prompts()
        for prompt in prompts:
            assert "title" in prompt
            assert "message" in prompt


class TestGetThreadContext:
    """Tests for get_thread_context method."""

    def test_returns_context_if_exists(self, assistant_handler):
        """Test that stored context is returned."""
        assistant_handler._thread_contexts["123"] = {"test": "context"}
        assert assistant_handler.get_thread_context("123") == {"test": "context"}

    def test_returns_none_if_not_exists(self, assistant_handler):
        """Test that None is returned for unknown thread."""
        assert assistant_handler.get_thread_context("unknown") is None


class TestWrapperIntegration:
    """Tests for wrapper integration with assistant handler."""

    @pytest.fixture
    def wrapper_config_enabled(self):
        """Create config with assistant enabled and all required fields."""
        config = MagicMock()
        config.name = "test-bot"
        config.chatbot_id = "test-chatbot"
        config.bot_token = "xoxb-test-token"
        config.signing_secret = "test-secret"
        config.enable_assistant = True
        config.max_concurrent_requests = 10
        config.webhook_path = None
        config.allowed_channel_ids = None
        return config

    @pytest.fixture
    def wrapper_config_disabled(self):
        """Create config with assistant disabled and all required fields."""
        config = MagicMock()
        config.name = "test-bot"
        config.chatbot_id = "test-chatbot"
        config.bot_token = "xoxb-test-token"
        config.signing_secret = "test-secret"
        config.enable_assistant = False
        config.max_concurrent_requests = 10
        config.webhook_path = None
        config.allowed_channel_ids = None
        return config

    @pytest.mark.asyncio
    async def test_wrapper_initializes_handler_when_enabled(self, wrapper_config_enabled, mock_agent):
        """Test that wrapper creates assistant handler when enabled."""
        from aiohttp import web

        app = web.Application()

        with patch("parrot.integrations.slack.wrapper.SlackAssistantHandler") as mock_handler_cls:
            from parrot.integrations.slack.wrapper import SlackAgentWrapper
            wrapper = SlackAgentWrapper(mock_agent, wrapper_config_enabled, app)

            mock_handler_cls.assert_called_once_with(wrapper)
            assert wrapper._assistant_handler is not None

    @pytest.mark.asyncio
    async def test_wrapper_no_handler_when_disabled(self, wrapper_config_disabled, mock_agent):
        """Test that wrapper does not create handler when disabled."""
        from aiohttp import web

        app = web.Application()

        from parrot.integrations.slack.wrapper import SlackAgentWrapper
        wrapper = SlackAgentWrapper(mock_agent, wrapper_config_disabled, app)

        assert wrapper._assistant_handler is None
