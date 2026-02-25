"""Unit tests for Slack Socket Mode handler."""
import asyncio
import sys
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# Mock slack_sdk modules before importing socket_handler
mock_socket_mode_client = MagicMock()
mock_web_client = MagicMock()
mock_socket_mode_response = MagicMock()

# Create mock modules
mock_slack_sdk = MagicMock()
mock_slack_sdk.socket_mode = MagicMock()
mock_slack_sdk.socket_mode.aiohttp = MagicMock()
mock_slack_sdk.socket_mode.aiohttp.SocketModeClient = mock_socket_mode_client
mock_slack_sdk.socket_mode.response = MagicMock()
mock_slack_sdk.socket_mode.response.SocketModeResponse = mock_socket_mode_response
mock_slack_sdk.web = MagicMock()
mock_slack_sdk.web.async_client = MagicMock()
mock_slack_sdk.web.async_client.AsyncWebClient = mock_web_client

# Patch modules
sys.modules['slack_sdk'] = mock_slack_sdk
sys.modules['slack_sdk.socket_mode'] = mock_slack_sdk.socket_mode
sys.modules['slack_sdk.socket_mode.aiohttp'] = mock_slack_sdk.socket_mode.aiohttp
sys.modules['slack_sdk.socket_mode.response'] = mock_slack_sdk.socket_mode.response
sys.modules['slack_sdk.web'] = mock_slack_sdk.web
sys.modules['slack_sdk.web.async_client'] = mock_slack_sdk.web.async_client

from parrot.integrations.slack.socket_handler import SlackSocketHandler  # noqa: E402
from parrot.integrations.slack.models import SlackAgentConfig  # noqa: E402


@pytest.fixture
def mock_config():
    """Create a mock SlackAgentConfig for Socket Mode."""
    with patch('parrot.integrations.slack.models.config.get', return_value=None):
        config = SlackAgentConfig(
            name="test",
            chatbot_id="test_bot",
            bot_token="xoxb-test-token",
            signing_secret="test_secret_123",
            app_token="xapp-test-app-token",
            connection_mode="socket",
            max_concurrent_requests=5,
        )
    return config


@pytest.fixture
def mock_wrapper(mock_config):
    """Create a mock SlackAgentWrapper for testing."""
    wrapper = MagicMock()
    wrapper.config = mock_config
    wrapper._dedup = MagicMock()
    wrapper._dedup.is_duplicate = MagicMock(return_value=False)
    wrapper._is_authorized = MagicMock(return_value=True)
    wrapper._safe_answer = AsyncMock()
    wrapper._help_text = MagicMock(return_value="Help text")
    wrapper.conversations = {}
    wrapper._background_tasks = set()
    return wrapper


@pytest.fixture
def handler(mock_wrapper):
    """Create a SlackSocketHandler for testing."""
    # Reset the mock to create fresh instance
    mock_socket_mode_client.reset_mock()
    mock_client_instance = MagicMock()
    mock_client_instance.socket_mode_request_listeners = []
    mock_client_instance.connect = AsyncMock()
    mock_client_instance.disconnect = AsyncMock()
    mock_client_instance.send_socket_mode_response = AsyncMock()
    mock_socket_mode_client.return_value = mock_client_instance

    handler = SlackSocketHandler(mock_wrapper)
    return handler


class TestSlackSocketHandlerInit:
    """Tests for socket handler initialization."""

    def test_handler_initialization(self, handler, mock_wrapper):
        """Handler initializes with wrapper reference."""
        assert handler.wrapper == mock_wrapper
        assert handler._running is False

    def test_handler_requires_app_token(self):
        """Handler requires app_token for Socket Mode."""
        with patch('parrot.integrations.slack.models.config.get', return_value=None):
            with pytest.raises(ValueError, match="Socket Mode requires app-level token"):
                SlackAgentConfig(
                    name="test",
                    chatbot_id="test_bot",
                    bot_token="xoxb-test-token",
                    connection_mode="socket",
                    # Missing app_token
                )


class TestSlackSocketHandlerLifecycle:
    """Tests for socket handler start/stop lifecycle."""

    @pytest.mark.asyncio
    async def test_start_connects_client(self, handler):
        """Start method connects the Socket Mode client."""
        # Run start in background and stop it quickly
        async def run_start():
            task = asyncio.create_task(handler.start())
            await asyncio.sleep(0.1)
            handler._running = False
            await asyncio.sleep(0.1)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        await run_start()
        handler.client.connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_disconnects_client(self, handler):
        """Stop method disconnects the Socket Mode client."""
        handler._running = True
        await handler.stop()
        handler.client.disconnect.assert_called_once()
        assert handler._running is False

    @pytest.mark.asyncio
    async def test_double_start_is_idempotent(self, handler):
        """Calling start when already running does nothing."""
        handler._running = True
        await handler.start()  # Should return immediately
        handler.client.connect.assert_not_called()


class TestSlackSocketHandlerRequestRouting:
    """Tests for Socket Mode request routing."""

    @pytest.mark.asyncio
    async def test_acknowledges_request(self, handler):
        """Requests are acknowledged immediately."""
        mock_client = AsyncMock()
        mock_req = MagicMock()
        mock_req.envelope_id = "env_123"
        mock_req.type = "events_api"
        mock_req.payload = {"event": {"type": "other"}}

        # Reset the mock response class
        mock_socket_mode_response.reset_mock()
        mock_socket_mode_response.return_value = MagicMock()

        await handler._handle_request(mock_client, mock_req)
        mock_client.send_socket_mode_response.assert_called_once()

    @pytest.mark.asyncio
    async def test_routes_events_api(self, handler):
        """events_api requests are routed to _handle_event."""
        mock_client = AsyncMock()
        mock_req = MagicMock()
        mock_req.envelope_id = "env_123"
        mock_req.type = "events_api"
        mock_req.payload = {"event_id": "evt_123", "event": {"type": "message"}}

        with patch.object(handler, '_handle_event', new_callable=AsyncMock) as mock_handle:
            await handler._handle_request(mock_client, mock_req)
            mock_handle.assert_called_once_with(mock_req.payload)

    @pytest.mark.asyncio
    async def test_routes_slash_commands(self, handler):
        """slash_commands requests are routed to _handle_slash_command."""
        mock_client = AsyncMock()
        mock_req = MagicMock()
        mock_req.envelope_id = "env_123"
        mock_req.type = "slash_commands"
        mock_req.payload = {"channel_id": "C123", "text": "hello"}

        with patch.object(handler, '_handle_slash_command', new_callable=AsyncMock) as mock_handle:
            await handler._handle_request(mock_client, mock_req)
            mock_handle.assert_called_once_with(mock_req.payload)

    @pytest.mark.asyncio
    async def test_routes_interactive(self, handler):
        """interactive requests are routed to _handle_interactive."""
        mock_client = AsyncMock()
        mock_req = MagicMock()
        mock_req.envelope_id = "env_123"
        mock_req.type = "interactive"
        mock_req.payload = {"type": "block_actions"}

        with patch.object(handler, '_handle_interactive', new_callable=AsyncMock) as mock_handle:
            await handler._handle_request(mock_client, mock_req)
            mock_handle.assert_called_once_with(mock_req.payload)


class TestSlackSocketHandlerEvents:
    """Tests for event handling."""

    @pytest.mark.asyncio
    async def test_routes_message_event(self, handler, mock_wrapper):
        """Message events are routed to _safe_answer."""
        payload = {
            "event_id": "evt_123",
            "event": {
                "type": "message",
                "channel": "C123",
                "user": "U456",
                "text": "Hello",
                "ts": "123.456",
            }
        }

        await handler._handle_event(payload)
        await asyncio.sleep(0.1)  # Allow task to start

        mock_wrapper._safe_answer.assert_called_once()
        call_kwargs = mock_wrapper._safe_answer.call_args[1]
        assert call_kwargs["channel"] == "C123"
        assert call_kwargs["user"] == "U456"
        assert call_kwargs["text"] == "Hello"

    @pytest.mark.asyncio
    async def test_routes_app_mention_event(self, handler, mock_wrapper):
        """app_mention events are routed to _safe_answer."""
        payload = {
            "event_id": "evt_124",
            "event": {
                "type": "app_mention",
                "channel": "C123",
                "user": "U456",
                "text": "<@U123> Hello bot",
                "ts": "123.456",
            }
        }

        await handler._handle_event(payload)
        await asyncio.sleep(0.1)

        mock_wrapper._safe_answer.assert_called_once()

    @pytest.mark.asyncio
    async def test_deduplicates_events(self, handler, mock_wrapper):
        """Duplicate events are not processed."""
        mock_wrapper._dedup.is_duplicate = MagicMock(return_value=True)

        payload = {"event_id": "evt_123", "event": {"type": "message"}}

        await handler._handle_event(payload)

        mock_wrapper._safe_answer.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_bot_messages(self, handler, mock_wrapper):
        """Bot messages are not processed."""
        payload = {
            "event_id": "evt_123",
            "event": {
                "type": "message",
                "subtype": "bot_message",
                "channel": "C123",
            }
        }

        await handler._handle_event(payload)

        mock_wrapper._safe_answer.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_messages_with_bot_id(self, handler, mock_wrapper):
        """Messages with bot_id are not processed."""
        payload = {
            "event_id": "evt_123",
            "event": {
                "type": "message",
                "bot_id": "B123",
                "channel": "C123",
            }
        }

        await handler._handle_event(payload)

        mock_wrapper._safe_answer.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_unauthorized_channels(self, handler, mock_wrapper):
        """Messages from unauthorized channels are not processed."""
        mock_wrapper._is_authorized = MagicMock(return_value=False)

        payload = {
            "event_id": "evt_123",
            "event": {
                "type": "message",
                "channel": "C_UNAUTHORIZED",
                "user": "U456",
                "text": "Hello",
            }
        }

        await handler._handle_event(payload)

        mock_wrapper._safe_answer.assert_not_called()


class TestSlackSocketHandlerSlashCommands:
    """Tests for slash command handling."""

    @pytest.mark.asyncio
    async def test_slash_command_help(self, handler, mock_wrapper):
        """Help command returns help text via response_url."""
        payload = {
            "channel_id": "C123",
            "user_id": "U456",
            "text": "help",
            "response_url": "https://hooks.slack.com/response/xxx"
        }

        with patch.object(handler, '_send_response', new_callable=AsyncMock) as mock_send:
            await handler._handle_slash_command(payload)

            mock_send.assert_called_once()
            call_args = mock_send.call_args[0]
            assert call_args[0] == payload["response_url"]
            assert call_args[1]["text"] == "Help text"

    @pytest.mark.asyncio
    async def test_slash_command_clear(self, handler, mock_wrapper):
        """Clear command clears conversation memory."""
        mock_wrapper.conversations["C123:U456"] = MagicMock()

        payload = {
            "channel_id": "C123",
            "user_id": "U456",
            "text": "clear",
            "response_url": "https://hooks.slack.com/response/xxx"
        }

        with patch.object(handler, '_send_response', new_callable=AsyncMock) as mock_send:
            await handler._handle_slash_command(payload)

            assert "C123:U456" not in mock_wrapper.conversations
            mock_send.assert_called_once()
            assert "cleared" in mock_send.call_args[0][1]["text"].lower()

    @pytest.mark.asyncio
    async def test_slash_command_regular_text(self, handler, mock_wrapper):
        """Regular slash command text is processed by agent."""
        payload = {
            "channel_id": "C123",
            "user_id": "U456",
            "text": "What is the weather?",
            "response_url": "https://hooks.slack.com/response/xxx"
        }

        await handler._handle_slash_command(payload)
        await asyncio.sleep(0.1)

        mock_wrapper._safe_answer.assert_called_once()
        call_kwargs = mock_wrapper._safe_answer.call_args[1]
        assert call_kwargs["text"] == "What is the weather?"


class TestSlackSocketHandlerInteractive:
    """Tests for interactive payload handling."""

    @pytest.mark.asyncio
    async def test_routes_to_interactive_handler(self, handler, mock_wrapper):
        """Interactive payloads are routed to the interactive handler."""
        mock_handler = AsyncMock()
        mock_wrapper._interactive_handler = mock_handler

        payload = {"type": "block_actions", "actions": []}

        await handler._handle_interactive(payload)

        mock_handler.handle.assert_called_once_with(payload)

    @pytest.mark.asyncio
    async def test_no_error_without_interactive_handler(self, handler, mock_wrapper):
        """No error when interactive handler is not configured."""
        # Remove interactive handler
        if hasattr(mock_wrapper, '_interactive_handler'):
            delattr(mock_wrapper, '_interactive_handler')

        payload = {"type": "block_actions", "actions": []}

        # Should not raise
        await handler._handle_interactive(payload)


class TestSlackSocketHandlerSendResponse:
    """Tests for sending responses to Slack."""

    @pytest.mark.asyncio
    async def test_send_response_success(self, handler):
        """Response is sent to response_url."""
        with patch('parrot.integrations.slack.socket_handler.ClientSession') as MockSession:
            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)

            mock_session = MagicMock()
            mock_session.post = MagicMock(return_value=mock_response)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)

            MockSession.return_value = mock_session

            await handler._send_response(
                "https://hooks.slack.com/response/xxx",
                {"text": "Hello"}
            )

            mock_session.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_response_error_handled(self, handler):
        """Errors sending response are handled gracefully."""
        with patch('parrot.integrations.slack.socket_handler.ClientSession') as MockSession:
            MockSession.side_effect = Exception("Network error")

            # Should not raise
            await handler._send_response(
                "https://hooks.slack.com/response/xxx",
                {"text": "Hello"}
            )
