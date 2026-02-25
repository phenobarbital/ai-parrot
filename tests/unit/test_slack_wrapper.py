"""Unit tests for Slack wrapper module."""
import asyncio
import hashlib
import hmac
import json
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from parrot.integrations.slack.wrapper import SlackAgentWrapper
from parrot.integrations.slack.models import SlackAgentConfig


def make_slack_signature(body: bytes, timestamp: str, secret: str) -> str:
    """Create a valid Slack signature for testing."""
    sig_base = f"v0:{timestamp}:{body.decode('utf-8')}"
    return "v0=" + hmac.new(
        secret.encode("utf-8"),
        sig_base.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def make_event_payload(
    event_type: str = "message",
    text: str = "Hello",
    channel: str = "C123",
    user: str = "U456",
    event_id: str = None,
    subtype: str = None,
    bot_id: str = None,
):
    """Create a Slack event payload for testing."""
    event = {
        "type": event_type,
        "text": text,
        "channel": channel,
        "user": user,
        "ts": "123.456",
    }
    if subtype:
        event["subtype"] = subtype
    if bot_id:
        event["bot_id"] = bot_id

    return {
        "type": "event_callback",
        "event_id": event_id or f"evt_{int(time.time())}",
        "event": event,
    }


@pytest.fixture
def mock_config():
    """Create a mock SlackAgentConfig."""
    with patch('parrot.integrations.slack.models.config.get', return_value=None):
        config = SlackAgentConfig(
            name="test",
            chatbot_id="test_bot",
            bot_token="xoxb-test-token",
            signing_secret="test_secret_123",
            max_concurrent_requests=5,
        )
    return config


@pytest.fixture
def mock_agent():
    """Create a mock agent."""
    agent = MagicMock()
    agent.ask = AsyncMock(return_value="Test response")
    return agent


@pytest.fixture
def mock_app():
    """Create a mock aiohttp application."""
    app = web.Application()
    app["auth"] = None
    return app


@pytest.fixture
def wrapper(mock_agent, mock_config, mock_app):
    """Create a SlackAgentWrapper instance for testing."""
    return SlackAgentWrapper(mock_agent, mock_config, mock_app)


class TestSlackWrapperSecurity:
    """Tests for signature verification and security."""

    @pytest.mark.asyncio
    async def test_unsigned_request_returns_401(self, wrapper):
        """Request without valid signature returns 401."""
        request = make_mocked_request("POST", "/", headers={})
        request.read = AsyncMock(return_value=b'{"type": "event_callback"}')

        response = await wrapper._handle_events(request)
        assert response.status == 401

    @pytest.mark.asyncio
    async def test_invalid_signature_returns_401(self, wrapper):
        """Request with invalid signature returns 401."""
        body = b'{"type": "event_callback"}'
        timestamp = str(int(time.time()))

        request = make_mocked_request("POST", "/", headers={
            "X-Slack-Request-Timestamp": timestamp,
            "X-Slack-Signature": "v0=invalid_signature",
        })
        request.read = AsyncMock(return_value=body)

        response = await wrapper._handle_events(request)
        assert response.status == 401

    @pytest.mark.asyncio
    async def test_valid_signature_accepted(self, wrapper, mock_config):
        """Request with valid signature is accepted."""
        payload = make_event_payload(event_type="app_mention")
        body = json.dumps(payload).encode()
        timestamp = str(int(time.time()))
        signature = make_slack_signature(body, timestamp, mock_config.signing_secret)

        request = make_mocked_request("POST", "/", headers={
            "X-Slack-Request-Timestamp": timestamp,
            "X-Slack-Signature": signature,
        })
        request.read = AsyncMock(return_value=body)

        with patch.object(wrapper, '_post_message', new_callable=AsyncMock):
            response = await wrapper._handle_events(request)

        assert response.status == 200


class TestSlackWrapperRetry:
    """Tests for retry header handling."""

    @pytest.mark.asyncio
    async def test_retry_returns_200_immediately(self, wrapper):
        """Requests with X-Slack-Retry-Num return 200 without processing."""
        request = make_mocked_request("POST", "/", headers={
            "X-Slack-Retry-Num": "1",
            "X-Slack-Retry-Reason": "http_timeout",
        })

        response = await wrapper._handle_events(request)

        assert response.status == 200
        data = json.loads(response.body)
        assert data["ok"] is True

    @pytest.mark.asyncio
    async def test_retry_does_not_call_agent(self, wrapper, mock_agent):
        """Retry requests don't process the message."""
        request = make_mocked_request("POST", "/", headers={
            "X-Slack-Retry-Num": "2",
            "X-Slack-Retry-Reason": "http_timeout",
        })

        await wrapper._handle_events(request)

        mock_agent.ask.assert_not_called()


class TestSlackWrapperDeduplication:
    """Tests for event deduplication."""

    @pytest.mark.asyncio
    async def test_duplicate_event_not_processed(self, wrapper, mock_config, mock_agent):
        """Same event_id twice only processes once."""
        event_id = "evt_duplicate_test_123"
        payload = make_event_payload(event_id=event_id)
        body = json.dumps(payload).encode()
        timestamp = str(int(time.time()))
        signature = make_slack_signature(body, timestamp, mock_config.signing_secret)

        headers = {
            "X-Slack-Request-Timestamp": timestamp,
            "X-Slack-Signature": signature,
        }

        with patch.object(wrapper, '_post_message', new_callable=AsyncMock):
            with patch.object(wrapper, '_send_typing_indicator', new_callable=AsyncMock):
                # First request
                request1 = make_mocked_request("POST", "/", headers=headers)
                request1.read = AsyncMock(return_value=body)
                response1 = await wrapper._handle_events(request1)
                assert response1.status == 200

                # Allow background task to start
                await asyncio.sleep(0.1)

                # Second request with same event_id
                request2 = make_mocked_request("POST", "/", headers=headers)
                request2.read = AsyncMock(return_value=body)
                response2 = await wrapper._handle_events(request2)
                assert response2.status == 200

                # Wait for any background tasks
                await asyncio.sleep(0.1)

        # Agent should only be called once
        assert mock_agent.ask.call_count == 1


class TestSlackWrapperAsync:
    """Tests for async background processing."""

    @pytest.mark.asyncio
    async def test_returns_200_before_processing(self, wrapper, mock_config, mock_agent):
        """Response returns immediately before agent processing completes."""
        # Make agent.ask take 2 seconds
        async def slow_ask(*args, **kwargs):
            await asyncio.sleep(2)
            return "Slow response"

        mock_agent.ask = slow_ask

        payload = make_event_payload()
        body = json.dumps(payload).encode()
        timestamp = str(int(time.time()))
        signature = make_slack_signature(body, timestamp, mock_config.signing_secret)

        request = make_mocked_request("POST", "/", headers={
            "X-Slack-Request-Timestamp": timestamp,
            "X-Slack-Signature": signature,
        })
        request.read = AsyncMock(return_value=body)

        with patch.object(wrapper, '_post_message', new_callable=AsyncMock):
            start = time.time()
            response = await wrapper._handle_events(request)
            elapsed = time.time() - start

        assert response.status == 200
        assert elapsed < 0.5  # Should return quickly, not wait 2 seconds

    @pytest.mark.asyncio
    async def test_timeout_sends_error_message(self, wrapper):
        """Timeout in _safe_answer sends error message to user."""
        # Create a mock that times out
        async def timeout_answer(*args, **kwargs):
            await asyncio.sleep(200)

        with patch.object(wrapper, '_answer', side_effect=timeout_answer):
            with patch.object(wrapper, '_post_message', new_callable=AsyncMock) as mock_post:
                # Use a shorter timeout for testing
                with patch('parrot.integrations.slack.wrapper.asyncio.wait_for') as mock_wait:
                    mock_wait.side_effect = asyncio.TimeoutError()

                    await wrapper._safe_answer(
                        channel="C123",
                        user="U456",
                        text="test",
                        thread_ts="123.456",
                        session_id="test",
                    )

                mock_post.assert_called_once()
                args = mock_post.call_args[0]
                assert "too long" in args[1]

    @pytest.mark.asyncio
    async def test_error_sends_error_message(self, wrapper):
        """Unhandled error in _safe_answer sends error message to user."""
        with patch.object(wrapper, '_answer', side_effect=ValueError("Test error")):
            with patch.object(wrapper, '_post_message', new_callable=AsyncMock) as mock_post:
                await wrapper._safe_answer(
                    channel="C123",
                    user="U456",
                    text="test",
                    thread_ts="123.456",
                    session_id="test",
                )

                mock_post.assert_called_once()
                args = mock_post.call_args[0]
                assert "error" in args[1].lower()


class TestSlackWrapperConcurrency:
    """Tests for concurrency limiting."""

    @pytest.mark.asyncio
    async def test_semaphore_limits_concurrent_requests(self, wrapper, mock_config):
        """Semaphore limits concurrent agent calls."""
        # Create a wrapper with max 2 concurrent requests
        mock_config.max_concurrent_requests = 2

        call_count = 0
        max_concurrent = 0
        current_concurrent = 0

        async def counting_answer(*args, **kwargs):
            nonlocal call_count, max_concurrent, current_concurrent
            current_concurrent += 1
            max_concurrent = max(max_concurrent, current_concurrent)
            call_count += 1
            await asyncio.sleep(0.1)
            current_concurrent -= 1

        with patch.object(wrapper, '_answer', side_effect=counting_answer):
            # Reset semaphore with new limit
            wrapper._concurrency_semaphore = asyncio.Semaphore(2)

            # Launch 5 concurrent tasks
            tasks = [
                wrapper._safe_answer(
                    channel="C123",
                    user="U456",
                    text=f"test {i}",
                    thread_ts="123.456",
                    session_id=f"test_{i}",
                )
                for i in range(5)
            ]

            await asyncio.gather(*tasks)

        assert call_count == 5
        assert max_concurrent <= 2  # Should never exceed semaphore limit


class TestSlackWrapperEventFiltering:
    """Tests for event filtering (bot messages, unauthorized channels, etc.)."""

    @pytest.mark.asyncio
    async def test_bot_message_ignored(self, wrapper, mock_config, mock_agent):
        """Bot messages are not processed."""
        payload = make_event_payload(subtype="bot_message")
        body = json.dumps(payload).encode()
        timestamp = str(int(time.time()))
        signature = make_slack_signature(body, timestamp, mock_config.signing_secret)

        request = make_mocked_request("POST", "/", headers={
            "X-Slack-Request-Timestamp": timestamp,
            "X-Slack-Signature": signature,
        })
        request.read = AsyncMock(return_value=body)

        response = await wrapper._handle_events(request)

        assert response.status == 200
        mock_agent.ask.assert_not_called()

    @pytest.mark.asyncio
    async def test_message_with_bot_id_ignored(self, wrapper, mock_config, mock_agent):
        """Messages with bot_id are not processed."""
        payload = make_event_payload(bot_id="B12345")
        body = json.dumps(payload).encode()
        timestamp = str(int(time.time()))
        signature = make_slack_signature(body, timestamp, mock_config.signing_secret)

        request = make_mocked_request("POST", "/", headers={
            "X-Slack-Request-Timestamp": timestamp,
            "X-Slack-Signature": signature,
        })
        request.read = AsyncMock(return_value=body)

        response = await wrapper._handle_events(request)

        assert response.status == 200
        mock_agent.ask.assert_not_called()

    @pytest.mark.asyncio
    async def test_url_verification_challenge(self, wrapper, mock_config):
        """URL verification challenge returns the challenge value."""
        payload = {
            "type": "url_verification",
            "challenge": "test_challenge_123",
        }
        body = json.dumps(payload).encode()
        timestamp = str(int(time.time()))
        signature = make_slack_signature(body, timestamp, mock_config.signing_secret)

        request = make_mocked_request("POST", "/", headers={
            "X-Slack-Request-Timestamp": timestamp,
            "X-Slack-Signature": signature,
        })
        request.read = AsyncMock(return_value=body)

        response = await wrapper._handle_events(request)

        assert response.status == 200
        data = json.loads(response.body)
        assert data["challenge"] == "test_challenge_123"


class TestSlackWrapperLifecycle:
    """Tests for start/stop lifecycle."""

    @pytest.mark.asyncio
    async def test_start_stop_lifecycle(self, wrapper):
        """Start and stop work without errors."""
        await wrapper.start()
        assert wrapper._dedup._cleanup_task is not None

        await wrapper.stop()
        assert wrapper._dedup._cleanup_task is None

    @pytest.mark.asyncio
    async def test_stop_cancels_background_tasks(self, wrapper):
        """Stop cancels any pending background tasks."""
        # Create a long-running task
        async def long_task():
            await asyncio.sleep(100)

        task = asyncio.create_task(long_task())
        wrapper._background_tasks.add(task)

        await wrapper.stop()

        assert task.cancelled() or task.done()
        assert len(wrapper._background_tasks) == 0


class TestSlackTypingIndicator:
    """Tests for typing indicator functionality."""

    @pytest.mark.asyncio
    async def test_sends_ephemeral_message(self, wrapper):
        """Typing indicator sends ephemeral message."""
        with patch('parrot.integrations.slack.wrapper.ClientSession') as mock_session_class:
            mock_response = MagicMock()
            mock_response.json = AsyncMock(
                return_value={"ok": True, "message_ts": "123.456"}
            )
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)

            mock_session = MagicMock()
            mock_session.post = MagicMock(return_value=mock_response)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)

            mock_session_class.return_value = mock_session

            result = await wrapper._send_typing_indicator("C123", "U456", "789.012")

            assert result == "123.456"
            # Verify the call was made to the correct URL
            call_args = mock_session.post.call_args
            assert "chat.postEphemeral" in call_args[0][0]
            # Verify payload
            call_data = json.loads(call_args[1]['data'])
            assert call_data["user"] == "U456"
            assert call_data["channel"] == "C123"
            assert call_data["thread_ts"] == "789.012"
            assert "Thinking" in call_data["text"]

    @pytest.mark.asyncio
    async def test_ephemeral_without_thread(self, wrapper):
        """Typing indicator works without thread_ts."""
        with patch('parrot.integrations.slack.wrapper.ClientSession') as mock_session_class:
            mock_response = MagicMock()
            mock_response.json = AsyncMock(
                return_value={"ok": True, "message_ts": "999.888"}
            )
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)

            mock_session = MagicMock()
            mock_session.post = MagicMock(return_value=mock_response)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)

            mock_session_class.return_value = mock_session

            result = await wrapper._send_typing_indicator("C123", "U456")

            assert result == "999.888"
            call_data = json.loads(mock_session.post.call_args[1]['data'])
            assert "thread_ts" not in call_data

    @pytest.mark.asyncio
    async def test_typing_indicator_error_does_not_break_flow(self, wrapper):
        """Typing indicator errors don't break the response flow."""
        with patch('parrot.integrations.slack.wrapper.ClientSession') as mock_session_class:
            mock_session_class.side_effect = Exception("Network error")

            # Should return None, not raise
            result = await wrapper._send_typing_indicator("C123", "U456")
            assert result is None

    @pytest.mark.asyncio
    async def test_assistant_status_with_loading_messages(self, wrapper):
        """Assistant status includes rotating messages."""
        wrapper.config.enable_assistant = True

        with patch('parrot.integrations.slack.wrapper.ClientSession') as mock_session_class:
            mock_response = MagicMock()
            mock_response.json = AsyncMock(return_value={"ok": True})
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)

            mock_session = MagicMock()
            mock_session.post = MagicMock(return_value=mock_response)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)

            mock_session_class.return_value = mock_session

            await wrapper._set_assistant_status(
                "C123", "789.012",
                loading_messages=["Processing...", "Almost done..."]
            )

            call_args = mock_session.post.call_args
            assert "assistant.threads.setStatus" in call_args[0][0]
            call_data = json.loads(call_args[1]['data'])
            assert "loading_messages" in call_data
            assert len(call_data["loading_messages"]) == 2
            assert call_data["channel_id"] == "C123"
            assert call_data["thread_ts"] == "789.012"

    @pytest.mark.asyncio
    async def test_assistant_status_error_does_not_break_flow(self, wrapper):
        """Assistant status errors don't break the response flow."""
        with patch('parrot.integrations.slack.wrapper.ClientSession') as mock_session_class:
            mock_session_class.side_effect = Exception("Network error")

            # Should not raise
            await wrapper._set_assistant_status("C123", "789.012")

    @pytest.mark.asyncio
    async def test_clear_assistant_status(self, wrapper):
        """Clear assistant status sets empty status."""
        with patch('parrot.integrations.slack.wrapper.ClientSession') as mock_session_class:
            mock_response = MagicMock()
            mock_response.json = AsyncMock(return_value={"ok": True})
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)

            mock_session = MagicMock()
            mock_session.post = MagicMock(return_value=mock_response)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)

            mock_session_class.return_value = mock_session

            await wrapper._clear_assistant_status("C123", "789.012")

            call_data = json.loads(mock_session.post.call_args[1]['data'])
            assert call_data["status"] == ""

    @pytest.mark.asyncio
    async def test_typing_indicator_returns_none_without_token(self, wrapper):
        """Typing indicator returns None if bot_token is not set."""
        wrapper.config.bot_token = None

        result = await wrapper._send_typing_indicator("C123", "U456")
        assert result is None


class TestSlackWrapperCommand:
    """Tests for slash command handling."""

    @pytest.mark.asyncio
    async def test_help_command(self, wrapper):
        """Help command returns help text."""
        request = make_mocked_request("POST", "/")
        request.post = AsyncMock(return_value={
            "channel_id": "C123",
            "user_id": "U456",
            "text": "help",
        })

        response = await wrapper._handle_command(request)

        assert response.status == 200
        data = json.loads(response.body)
        assert data["response_type"] == "ephemeral"
        assert "help" in data["text"].lower() or "ask" in data["text"].lower()

    @pytest.mark.asyncio
    async def test_clear_command(self, wrapper):
        """Clear command clears conversation memory."""
        # Add some memory first
        wrapper.conversations["C123:U456"] = MagicMock()

        request = make_mocked_request("POST", "/")
        request.post = AsyncMock(return_value={
            "channel_id": "C123",
            "user_id": "U456",
            "text": "clear",
        })

        response = await wrapper._handle_command(request)

        assert response.status == 200
        assert "C123:U456" not in wrapper.conversations
