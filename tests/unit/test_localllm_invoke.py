"""Unit tests for LocalLLMClient.invoke() (TASK-487)."""
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from pydantic import BaseModel

from parrot.models.responses import InvokeResult
from parrot.exceptions import InvokeError


class SimpleResult(BaseModel):
    """Fixture Pydantic model."""
    answer: str


def _make_mock_response(text: str = '{"answer": "42"}'):
    """Build a mock OpenAI-compatible response."""
    message = SimpleNamespace(content=text, tool_calls=None)
    choice = SimpleNamespace(message=message, finish_reason="stop")
    usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    return SimpleNamespace(choices=[choice], usage=usage)


def _make_client(model: str = "llama3.1:8b"):
    """Create LocalLLMClient without network setup."""
    from parrot.clients.localllm import LocalLLMClient
    client = LocalLLMClient.__new__(LocalLLMClient)
    client.model = model
    client._lightweight_model = None
    client._fallback_model = None
    client.base_url = "http://localhost:8000/v1"
    client.logger = MagicMock()
    client._tool_manager = MagicMock()
    client._tool_manager.get_tool_schemas.return_value = []
    client._tool_manager.tools = {}
    from datamodel.parsers.json import JSONContent
    client._json = JSONContent()
    return client


@pytest.fixture
def mock_localllm_client():
    """LocalLLMClient with mocked SDK."""
    client = _make_client()
    client.client = MagicMock()
    client.client.chat = MagicMock()
    client.client.chat.completions = MagicMock()
    client.client.chat.completions.create = AsyncMock(
        return_value=_make_mock_response()
    )
    return client


class TestLocalLLMInvoke:
    """Tests for LocalLLMClient.invoke()."""

    async def test_openai_compat_structured(self, mock_localllm_client):
        """invoke() uses OpenAI-compatible response_format for structured output."""
        mock_localllm_client.client.chat.completions.create = AsyncMock(
            return_value=_make_mock_response('{"answer": "42"}')
        )
        result = await mock_localllm_client.invoke(
            "Answer this", output_type=SimpleResult
        )
        assert isinstance(result, InvokeResult)
        # Verify response_format was set
        call_kwargs = mock_localllm_client.client.chat.completions.create.call_args[1]
        assert "response_format" in call_kwargs
        assert call_kwargs["response_format"]["type"] == "json_schema"

    async def test_no_lightweight_model(self, mock_localllm_client):
        """Uses self.model when _lightweight_model is None."""
        mock_localllm_client.client.chat.completions.create = AsyncMock(
            return_value=_make_mock_response("ok")
        )
        result = await mock_localllm_client.invoke("Hello")
        assert result.model == mock_localllm_client.model

    async def test_raw_string(self, mock_localllm_client):
        """invoke() without output_type returns raw text."""
        mock_localllm_client.client.chat.completions.create = AsyncMock(
            return_value=_make_mock_response("This is a summary")
        )
        result = await mock_localllm_client.invoke("Summarize")
        assert isinstance(result.output, str)
        assert result.output == "This is a summary"

    async def test_error_wrapped(self, mock_localllm_client):
        """Provider errors wrapped in InvokeError."""
        mock_localllm_client.client.chat.completions.create = AsyncMock(
            side_effect=RuntimeError("Connection refused")
        )
        with pytest.raises(InvokeError):
            await mock_localllm_client.invoke("test")

    async def test_fallback_to_schema_in_prompt(self, mock_localllm_client):
        """Falls back to schema-in-prompt when server rejects response_format."""
        call_count = 0
        responses = [
            RuntimeError("response_format not supported"),
            _make_mock_response('{"answer": "fallback answer"}'),
        ]

        async def mock_create(**kwargs):
            nonlocal call_count
            result = responses[min(call_count, 1)]
            call_count += 1
            if isinstance(result, Exception):
                raise result
            return result

        mock_localllm_client.client.chat.completions.create = mock_create
        result = await mock_localllm_client.invoke(
            "Answer this", output_type=SimpleResult
        )
        assert isinstance(result, InvokeResult)
        assert call_count == 2  # Two calls were made

    async def test_model_override(self, mock_localllm_client):
        """Explicit model param overrides self.model."""
        mock_localllm_client.client.chat.completions.create = AsyncMock(
            return_value=_make_mock_response("ok")
        )
        result = await mock_localllm_client.invoke(
            "test", model="mistral:7b"
        )
        assert result.model == "mistral:7b"

    async def test_not_initialized_raises(self):
        """InvokeError raised when client not initialized."""
        client = _make_client()
        client.client = None
        with pytest.raises(InvokeError):
            await client.invoke("test")

    async def test_custom_parser_applied(self, mock_localllm_client):
        """custom_parser in StructuredOutputConfig is applied."""
        from parrot.models.outputs import StructuredOutputConfig, OutputFormat

        mock_localllm_client.client.chat.completions.create = AsyncMock(
            return_value=_make_mock_response("some text")
        )
        parsed = SimpleResult(answer="custom")
        config = StructuredOutputConfig(
            output_type=SimpleResult,
            format=OutputFormat.JSON,
            custom_parser=lambda text: parsed,
        )
        result = await mock_localllm_client.invoke("test", structured_output=config)
        assert result.output is parsed
