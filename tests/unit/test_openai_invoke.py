"""Unit tests for OpenAIClient.invoke() (TASK-483)."""
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from pydantic import BaseModel

from parrot.models.responses import InvokeResult
from parrot.exceptions import InvokeError


class SentimentResult(BaseModel):
    """Fixture model for structured output tests."""
    sentiment: str
    confidence: float


def _make_mock_response(text: str = '{"sentiment": "positive", "confidence": 0.9}'):
    """Build a mock OpenAI chat completions response."""
    message = SimpleNamespace(content=text, tool_calls=None)
    choice = SimpleNamespace(message=message, finish_reason="stop")
    usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    return SimpleNamespace(choices=[choice], usage=usage)


def _make_client():
    """Create OpenAIClient without network setup."""
    from parrot.clients.gpt import OpenAIClient
    client = OpenAIClient.__new__(OpenAIClient)
    client.model = "gpt-4o"
    client._lightweight_model = "gpt-4.1"
    client._fallback_model = None
    client.logger = MagicMock()
    client._tool_manager = MagicMock()
    client._tool_manager.get_tool_schemas.return_value = []
    client._tool_manager.tools = {}
    from datamodel.parsers.json import JSONContent
    client._json = JSONContent()
    return client


@pytest.fixture
def mock_openai_client():
    """OpenAIClient with mocked SDK."""
    client = _make_client()
    client.client = MagicMock()
    client.client.chat = MagicMock()
    client.client.chat.completions = MagicMock()
    client.client.chat.completions.create = AsyncMock(
        return_value=_make_mock_response()
    )
    return client


class TestOpenAIInvoke:
    """Tests for OpenAIClient.invoke()."""

    async def test_raw_string_output(self, mock_openai_client):
        """invoke() without output_type returns raw text."""
        mock_openai_client.client.chat.completions.create = AsyncMock(
            return_value=_make_mock_response("Hello world")
        )
        result = await mock_openai_client.invoke("Summarize this")
        assert isinstance(result, InvokeResult)
        assert isinstance(result.output, str)
        assert result.output == "Hello world"

    async def test_lightweight_model_default(self, mock_openai_client):
        """invoke() uses _lightweight_model by default."""
        mock_openai_client.client.chat.completions.create = AsyncMock(
            return_value=_make_mock_response("ok")
        )
        result = await mock_openai_client.invoke("test")
        assert result.model == "gpt-4.1"

    async def test_model_override(self, mock_openai_client):
        """Explicit model param overrides _lightweight_model."""
        mock_openai_client.client.chat.completions.create = AsyncMock(
            return_value=_make_mock_response("ok")
        )
        result = await mock_openai_client.invoke("test", model="gpt-4o-mini")
        assert result.model == "gpt-4o-mini"

    async def test_native_json_schema_response_format(self, mock_openai_client):
        """invoke() sets response_format for structured output."""
        mock_openai_client.client.chat.completions.create = AsyncMock(
            return_value=_make_mock_response(
                '{"sentiment": "positive", "confidence": 0.9}'
            )
        )
        await mock_openai_client.invoke(
            "Classify sentiment", output_type=SentimentResult
        )
        call_kwargs = mock_openai_client.client.chat.completions.create.call_args[1]
        assert "response_format" in call_kwargs
        assert call_kwargs["response_format"]["type"] == "json_schema"

    async def test_system_prompt_in_messages(self, mock_openai_client):
        """System prompt included in messages as first message."""
        mock_openai_client.client.chat.completions.create = AsyncMock(
            return_value=_make_mock_response("ok")
        )
        await mock_openai_client.invoke("test", system_prompt="Be helpful")
        call_kwargs = mock_openai_client.client.chat.completions.create.call_args[1]
        messages = call_kwargs["messages"]
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "Be helpful"

    async def test_error_wrapped_in_invoke_error(self, mock_openai_client):
        """Provider errors wrapped in InvokeError."""
        mock_openai_client.client.chat.completions.create = AsyncMock(
            side_effect=RuntimeError("API failed")
        )
        with pytest.raises(InvokeError) as exc_info:
            await mock_openai_client.invoke("test")
        assert exc_info.value.original is not None

    async def test_custom_parser_applied(self, mock_openai_client):
        """custom_parser in StructuredOutputConfig is applied to raw text."""
        from parrot.models.outputs import StructuredOutputConfig, OutputFormat

        mock_openai_client.client.chat.completions.create = AsyncMock(
            return_value=_make_mock_response("some text")
        )
        parsed = SentimentResult(sentiment="neutral", confidence=0.5)
        config = StructuredOutputConfig(
            output_type=SentimentResult,
            format=OutputFormat.JSON,
            custom_parser=lambda text: parsed,
        )
        result = await mock_openai_client.invoke("test", structured_output=config)
        assert result.output is parsed

    async def test_not_initialized_raises(self):
        """RuntimeError wrapped in InvokeError when client not initialized."""
        client = _make_client()
        client.client = None
        with pytest.raises(InvokeError):
            await client.invoke("test")
