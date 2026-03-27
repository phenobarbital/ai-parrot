"""Tests for AnthropicClient fallback behavior."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from anthropic import RateLimitError, APIStatusError, InternalServerError


def _make_client():
    """Create an AnthropicClient instance without full __init__."""
    from parrot.clients.claude import AnthropicClient
    client = AnthropicClient.__new__(AnthropicClient)
    client._fallback_model = 'claude-sonnet-4.5'
    return client


def _make_api_status_error(status_code: int):
    """Create an APIStatusError with the given status code."""
    mock_response = MagicMock()
    mock_response.status_code = status_code
    mock_response.headers = {}
    mock_response.text = f"{status_code} Error"
    mock_response.json.return_value = {"error": {"message": f"{status_code} Error"}}
    error = APIStatusError.__new__(APIStatusError)
    error.status_code = status_code
    error.response = mock_response
    error.body = None
    error.message = f"{status_code} Error"
    return error


def _make_rate_limit_error():
    """Create a RateLimitError."""
    mock_response = MagicMock()
    mock_response.status_code = 429
    mock_response.headers = {}
    mock_response.text = "429 Too Many Requests"
    mock_response.json.return_value = {"error": {"message": "rate limit exceeded"}}
    error = RateLimitError.__new__(RateLimitError)
    error.status_code = 429
    error.response = mock_response
    error.body = None
    error.message = "rate limit exceeded"
    return error


class TestAnthropicFallbackModel:
    """Test that AnthropicClient has the correct fallback model default."""

    def test_fallback_model_default(self):
        from parrot.clients.claude import AnthropicClient
        assert AnthropicClient._fallback_model == 'claude-sonnet-4.5'


class TestAnthropicIsCapacityError:
    """Test _is_capacity_error() with Anthropic-specific exception types."""

    def test_rate_limit_error(self):
        client = _make_client()
        error = _make_rate_limit_error()
        assert client._is_capacity_error(error) is True

    def test_api_status_error_429(self):
        client = _make_client()
        error = _make_api_status_error(429)
        assert client._is_capacity_error(error) is True

    def test_api_status_error_503(self):
        client = _make_client()
        error = _make_api_status_error(503)
        assert client._is_capacity_error(error) is True

    def test_api_status_error_529(self):
        client = _make_client()
        error = _make_api_status_error(529)
        assert client._is_capacity_error(error) is True

    def test_not_capacity_error_400(self):
        client = _make_client()
        error = _make_api_status_error(400)
        assert client._is_capacity_error(error) is False

    def test_not_capacity_error_401(self):
        client = _make_client()
        error = _make_api_status_error(401)
        assert client._is_capacity_error(error) is False

    def test_not_capacity_error_plain_exception(self):
        client = _make_client()
        error = Exception("400 Bad Request - invalid_request_error")
        assert client._is_capacity_error(error) is False

    def test_not_capacity_error_auth_plain(self):
        client = _make_client()
        error = Exception("401 Unauthorized")
        assert client._is_capacity_error(error) is False

    def test_fallback_to_base_string_matching(self):
        """Base class string matching works for generic exceptions."""
        client = _make_client()
        error = Exception("rate limit exceeded")
        assert client._is_capacity_error(error) is True

    def test_fallback_to_base_overloaded_string(self):
        client = _make_client()
        error = Exception("The model is currently overloaded")
        assert client._is_capacity_error(error) is True


class TestAnthropicAskFallback:
    """Test fallback behavior in the ask() method."""

    def _setup_client(self, model='claude-opus-4'):
        from parrot.clients.claude import AnthropicClient
        client = AnthropicClient.__new__(AnthropicClient)
        client._fallback_model = 'claude-sonnet-4.5'
        client.enable_tools = False
        client.model = model
        client._default_model = model
        client.max_tokens = 4096
        client.temperature = 0.7
        client.logger = MagicMock()
        client._prepare_conversation_context = AsyncMock(return_value=(
            [{"role": "user", "content": "Hello"}],
            [],
            "You are helpful"
        ))
        client._get_structured_config = MagicMock(return_value=MagicMock(
            format_schema_instruction=MagicMock(return_value="")
        ))
        client._update_conversation_memory = AsyncMock()
        return client

    def _mock_response(self, model="claude-sonnet-4.5"):
        mock_resp = MagicMock()
        mock_resp.model_dump.return_value = {
            "content": [{"type": "text", "text": "Hello!"}],
            "stop_reason": "end_turn",
            "model": model,
            "usage": {"input_tokens": 10, "output_tokens": 5}
        }
        return mock_resp

    @pytest.mark.asyncio
    async def test_ask_retries_with_fallback_on_capacity_error(self):
        """ask() should retry once with fallback model on capacity error."""
        client = self._setup_client()
        rate_limit_error = _make_rate_limit_error()
        mock_response = self._mock_response()

        mock_create = AsyncMock(side_effect=[rate_limit_error, mock_response])
        client.client = MagicMock()
        client.client.messages.create = mock_create

        mock_ai_message = MagicMock()
        mock_ai_message.metadata = {}
        with patch('parrot.clients.claude.AIMessageFactory') as mock_factory:
            mock_factory.from_claude.return_value = mock_ai_message
            result = await client.ask("Hello", model="claude-opus-4")

        assert mock_create.call_count == 2
        # Verify fallback metadata
        assert result.metadata['used_fallback_model'] is True
        assert result.metadata['original_model'] == 'claude-opus-4'
        assert result.metadata['fallback_model'] == 'claude-sonnet-4.5'
        # Verify logger warning was called
        client.logger.warning.assert_called_once()

    @pytest.mark.asyncio
    async def test_ask_raises_non_capacity_error(self):
        """ask() should raise non-capacity errors without fallback."""
        client = self._setup_client()
        auth_error = Exception("Authentication failed")

        client.client = MagicMock()
        client.client.messages.create = AsyncMock(side_effect=auth_error)

        with pytest.raises(Exception, match="Authentication failed"):
            await client.ask("Hello", model="claude-opus-4")

    @pytest.mark.asyncio
    async def test_ask_no_fallback_when_already_on_fallback_model(self):
        """ask() should not fallback when already using the fallback model."""
        client = self._setup_client(model='claude-sonnet-4.5')
        error = _make_rate_limit_error()

        client.client = MagicMock()
        client.client.messages.create = AsyncMock(side_effect=error)

        with pytest.raises(RateLimitError):
            await client.ask("Hello", model="claude-sonnet-4.5")

    @pytest.mark.asyncio
    async def test_ask_fallback_persists_in_tool_loop(self):
        """Once fallback triggers, subsequent tool-loop calls use fallback model."""
        client = self._setup_client()
        client.enable_tools = True

        rate_limit_error = _make_rate_limit_error()

        # First call: error → fallback, tool_use response
        tool_response = MagicMock()
        tool_response.model_dump.return_value = {
            "content": [
                {"type": "tool_use", "id": "tool_1", "name": "test_tool", "input": {}}
            ],
            "stop_reason": "tool_use",
            "model": "claude-sonnet-4.5",
            "usage": {"input_tokens": 10, "output_tokens": 5}
        }
        # Second call: final response (should still use fallback model)
        final_response = self._mock_response()

        mock_create = AsyncMock(side_effect=[rate_limit_error, tool_response, final_response])
        client.client = MagicMock()
        client.client.messages.create = mock_create

        # Mock tool execution
        client._execute_tool = AsyncMock(return_value="tool result")
        client._prepare_tools = MagicMock(return_value=[])
        client.tools = {}

        mock_ai_message = MagicMock()
        mock_ai_message.metadata = {}
        with patch('parrot.clients.claude.AIMessageFactory') as mock_factory:
            mock_factory.from_claude.return_value = mock_ai_message
            result = await client.ask("Hello", model="claude-opus-4")

        assert mock_create.call_count == 3
        # All calls after fallback should use fallback model
        # Call 2 (after fallback) and call 3 (tool loop continuation) use payload with fallback
        assert result.metadata['used_fallback_model'] is True


class TestAnthropicSdkRetries:
    """Verify SDK max_retries=2 is unchanged."""

    @pytest.mark.asyncio
    async def test_sdk_max_retries_preserved(self):
        from parrot.clients.claude import AnthropicClient
        client = AnthropicClient.__new__(AnthropicClient)
        client.api_key = "test-key"
        sdk_client = await client.get_client()
        assert sdk_client.max_retries == 2
