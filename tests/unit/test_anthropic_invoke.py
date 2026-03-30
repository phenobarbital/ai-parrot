"""Unit tests for AnthropicClient.invoke() (TASK-482)."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pydantic import BaseModel

from parrot.models.responses import InvokeResult
from parrot.exceptions import InvokeError


class PersonInfo(BaseModel):
    """Fixture Pydantic model."""
    name: str
    age: int


def _make_mock_response(text: str = '{"name": "Alice", "age": 30}'):
    """Build a mock Anthropic message response."""
    from types import SimpleNamespace
    block = SimpleNamespace(text=text)
    usage = SimpleNamespace(**{"input_tokens": 10, "output_tokens": 5, "__dict__": {"input_tokens": 10, "output_tokens": 5}})
    response = SimpleNamespace(content=[block], usage=usage)
    return response


def _make_client():
    """Create AnthropicClient without network setup."""
    from parrot.clients.claude import AnthropicClient
    client = AnthropicClient.__new__(AnthropicClient)
    client.model = "claude-sonnet-4-5"
    client._lightweight_model = "claude-haiku-4-5-20251001"
    client._fallback_model = None
    client.logger = MagicMock()
    client._tool_manager = MagicMock()
    client._tool_manager.get_tool_schemas.return_value = []
    client._tool_manager.tools = {}
    # Mock the internal JSON helper
    from datamodel.parsers.json import JSONContent
    client._json = JSONContent()
    return client


@pytest.fixture
def mock_claude_client():
    """AnthropicClient instance with mocked SDK."""
    client = _make_client()
    client.client = MagicMock()
    client.client.messages.create = AsyncMock(
        return_value=_make_mock_response()
    )
    return client


class TestAnthropicInvoke:
    """Tests for AnthropicClient.invoke()."""

    async def test_raw_string_output(self, mock_claude_client):
        """invoke() without output_type returns raw text."""
        mock_claude_client.client.messages.create = AsyncMock(
            return_value=_make_mock_response("Hello world")
        )
        result = await mock_claude_client.invoke("Hello")
        assert isinstance(result, InvokeResult)
        assert isinstance(result.output, str)
        assert result.output == "Hello world"

    async def test_lightweight_model_default(self, mock_claude_client):
        """invoke() uses _lightweight_model when no model param."""
        mock_claude_client.client.messages.create = AsyncMock(
            return_value=_make_mock_response("ok")
        )
        result = await mock_claude_client.invoke("test")
        assert result.model == "claude-haiku-4-5-20251001"

    async def test_model_override(self, mock_claude_client):
        """Explicit model param overrides _lightweight_model."""
        mock_claude_client.client.messages.create = AsyncMock(
            return_value=_make_mock_response("ok")
        )
        result = await mock_claude_client.invoke("test", model="claude-opus-4")
        assert result.model == "claude-opus-4"

    async def test_custom_system_prompt(self, mock_claude_client):
        """Custom system_prompt passed to SDK."""
        mock_claude_client.client.messages.create = AsyncMock(
            return_value=_make_mock_response("ok")
        )
        await mock_claude_client.invoke("test", system_prompt="Custom instructions")
        call_kwargs = mock_claude_client.client.messages.create.call_args[1]
        assert call_kwargs["system"] == "Custom instructions"

    async def test_structured_output_schema_injected(self, mock_claude_client):
        """Schema instruction injected into system prompt for structured output."""
        mock_claude_client.client.messages.create = AsyncMock(
            return_value=_make_mock_response('{"name": "Alice", "age": 30}')
        )
        result = await mock_claude_client.invoke(
            "Extract person", output_type=PersonInfo
        )
        # Verify schema was injected into system prompt
        call_kwargs = mock_claude_client.client.messages.create.call_args[1]
        assert "Schema" in call_kwargs["system"] or "schema" in call_kwargs["system"].lower()
        assert isinstance(result, InvokeResult)

    async def test_error_wrapped_in_invoke_error(self, mock_claude_client):
        """Provider errors wrapped in InvokeError with original preserved."""
        mock_claude_client.client.messages.create = AsyncMock(
            side_effect=RuntimeError("API error")
        )
        with pytest.raises(InvokeError) as exc_info:
            await mock_claude_client.invoke("test")
        assert exc_info.value.original is not None
        assert isinstance(exc_info.value.original, RuntimeError)

    async def test_not_initialized_raises(self):
        """RuntimeError raised when client not initialized."""
        client = _make_client()
        client.client = None
        with pytest.raises(InvokeError):
            await client.invoke("test")

    async def test_custom_parser_applied(self, mock_claude_client):
        """custom_parser in StructuredOutputConfig is called on raw text."""
        from parrot.models.outputs import StructuredOutputConfig, OutputFormat

        mock_claude_client.client.messages.create = AsyncMock(
            return_value=_make_mock_response("some text")
        )
        parsed = PersonInfo(name="Parsed", age=0)
        config = StructuredOutputConfig(
            output_type=PersonInfo,
            format=OutputFormat.JSON,
            custom_parser=lambda text: parsed,
        )
        result = await mock_claude_client.invoke("test", structured_output=config)
        assert result.output is parsed

    async def test_no_history_written(self, mock_claude_client):
        """invoke() does not touch conversation memory."""
        mock_claude_client.client.messages.create = AsyncMock(
            return_value=_make_mock_response("ok")
        )
        mock_claude_client.conversation_memory = MagicMock()
        await mock_claude_client.invoke("test")
        mock_claude_client.conversation_memory.add_turn.assert_not_called()
