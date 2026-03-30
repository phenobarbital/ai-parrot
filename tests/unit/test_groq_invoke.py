"""Unit tests for GroqClient.invoke() (TASK-485)."""
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from pydantic import BaseModel

from parrot.models.responses import InvokeResult
from parrot.exceptions import InvokeError


class ClassifyResult(BaseModel):
    """Fixture model for structured output tests."""
    category: str
    score: float


def _make_mock_response(text: str = '{"category": "sports", "score": 0.9}'):
    """Build a mock Groq chat completions response."""
    message = SimpleNamespace(content=text, tool_calls=None)
    choice = SimpleNamespace(message=message, finish_reason="stop")
    usage = SimpleNamespace(
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
        completion_time=None,
        prompt_time=None,
        queue_time=None,
        total_time=None,
    )
    return SimpleNamespace(choices=[choice], usage=usage)


def _make_client():
    """Create GroqClient without network setup."""
    from parrot.clients.groq import GroqClient
    client = GroqClient.__new__(GroqClient)
    client.model = "llama-3.3-70b-versatile"
    client._lightweight_model = "kimi-k2-instruct"
    client._fallback_model = None
    client.logger = MagicMock()
    client._tool_manager = MagicMock()
    client._tool_manager.get_tool_schemas.return_value = []
    client._tool_manager.tools = {}
    from datamodel.parsers.json import JSONContent
    client._json = JSONContent()
    return client


@pytest.fixture
def mock_groq_client():
    """GroqClient with mocked SDK."""
    client = _make_client()
    client.client = MagicMock()
    client.client.chat = MagicMock()
    client.client.chat.completions = MagicMock()
    client.client.chat.completions.create = AsyncMock(
        return_value=_make_mock_response()
    )
    return client


class TestGroqInvoke:
    """Tests for GroqClient.invoke()."""

    async def test_raw_string_output(self, mock_groq_client):
        """invoke() without output_type returns raw text."""
        mock_groq_client.client.chat.completions.create = AsyncMock(
            return_value=_make_mock_response("Hello world")
        )
        result = await mock_groq_client.invoke("Summarize")
        assert isinstance(result, InvokeResult)
        assert isinstance(result.output, str)

    async def test_lightweight_model_default(self, mock_groq_client):
        """invoke() uses _lightweight_model by default."""
        mock_groq_client.client.chat.completions.create = AsyncMock(
            return_value=_make_mock_response("ok")
        )
        result = await mock_groq_client.invoke("test")
        assert result.model == "kimi-k2-instruct"

    async def test_model_override(self, mock_groq_client):
        """Explicit model param overrides _lightweight_model."""
        mock_groq_client.client.chat.completions.create = AsyncMock(
            return_value=_make_mock_response("ok")
        )
        result = await mock_groq_client.invoke("test", model="llama-3.3-70b-versatile")
        assert result.model == "llama-3.3-70b-versatile"

    async def test_json_mode_for_structured_output(self, mock_groq_client):
        """invoke() uses JSON mode with schema for structured output."""
        mock_groq_client.client.chat.completions.create = AsyncMock(
            return_value=_make_mock_response('{"category": "sports", "score": 0.9}')
        )
        await mock_groq_client.invoke(
            "Classify this", output_type=ClassifyResult
        )
        call_kwargs = mock_groq_client.client.chat.completions.create.call_args[1]
        assert "response_format" in call_kwargs
        assert call_kwargs["response_format"]["type"] == "json_object"

    async def test_two_call_strategy(self, mock_groq_client):
        """Two-call strategy: tools first, then structured output."""
        call_count = 0
        responses = [
            _make_mock_response("Sports category with score 0.9"),
            _make_mock_response('{"category": "sports", "score": 0.9}'),
        ]

        async def mock_create(**kwargs):
            nonlocal call_count
            resp = responses[min(call_count, 1)]
            call_count += 1
            return resp

        mock_groq_client.client.chat.completions.create = mock_create
        mock_groq_client._tool_manager.get_tool_schemas.return_value = []

        result = await mock_groq_client.invoke(
            "Search and classify", output_type=ClassifyResult, use_tools=True
        )
        assert isinstance(result, InvokeResult)
        assert call_count == 2

    async def test_error_wrapped_in_invoke_error(self, mock_groq_client):
        """Provider errors wrapped in InvokeError."""
        mock_groq_client.client.chat.completions.create = AsyncMock(
            side_effect=RuntimeError("API error")
        )
        with pytest.raises(InvokeError) as exc_info:
            await mock_groq_client.invoke("test")
        assert exc_info.value.original is not None

    async def test_custom_parser_applied(self, mock_groq_client):
        """custom_parser in StructuredOutputConfig is applied to raw text."""
        from parrot.models.outputs import StructuredOutputConfig, OutputFormat

        mock_groq_client.client.chat.completions.create = AsyncMock(
            return_value=_make_mock_response("some text")
        )
        parsed = ClassifyResult(category="custom", score=1.0)
        config = StructuredOutputConfig(
            output_type=ClassifyResult,
            format=OutputFormat.JSON,
            custom_parser=lambda text: parsed,
        )
        result = await mock_groq_client.invoke("test", structured_output=config)
        assert result.output is parsed

    async def test_not_initialized_raises(self):
        """InvokeError raised when client not initialized."""
        client = _make_client()
        client.client = None
        with pytest.raises(InvokeError):
            await client.invoke("test")
