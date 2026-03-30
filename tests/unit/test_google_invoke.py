"""Unit tests for GoogleGenAIClient.invoke() (TASK-484)."""
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from pydantic import BaseModel

from parrot.models.responses import InvokeResult
from parrot.exceptions import InvokeError


class ExtractedData(BaseModel):
    """Fixture Pydantic model."""
    entities: list
    count: int


def _make_mock_response(text: str = '{"entities": ["Alice"], "count": 1}'):
    """Build a mock Google GenAI response."""
    part = SimpleNamespace(text=text)
    content = SimpleNamespace(parts=[part])
    candidate = SimpleNamespace(content=content, finish_reason="STOP")
    usage_metadata = SimpleNamespace(
        prompt_token_count=10,
        candidates_token_count=5,
        total_token_count=15,
    )
    return SimpleNamespace(
        candidates=[candidate],
        text=text,
        usage_metadata=usage_metadata,
    )


def _make_client():
    """Create GoogleGenAIClient without network setup."""
    from parrot.clients.google.client import GoogleGenAIClient
    client = GoogleGenAIClient.__new__(GoogleGenAIClient)
    client.model = "gemini-2.5-flash"
    client._lightweight_model = "gemini-3-flash-lite"
    client._fallback_model = None
    client.logger = MagicMock()
    client._tool_manager = MagicMock()
    client._tool_manager.get_tool_schemas.return_value = []
    client._tool_manager.tools = {}
    from datamodel.parsers.json import JSONContent
    client._json = JSONContent()
    return client


@pytest.fixture
def mock_google_client():
    """GoogleGenAIClient with mocked SDK."""
    client = _make_client()
    mock_models = MagicMock()
    mock_models.generate_content = AsyncMock(
        return_value=_make_mock_response()
    )
    client.client = MagicMock()
    client.client.aio = MagicMock()
    client.client.aio.models = mock_models
    return client


class TestGoogleInvoke:
    """Tests for GoogleGenAIClient.invoke()."""

    async def test_raw_string_output(self, mock_google_client):
        """invoke() without output_type returns raw text."""
        mock_google_client.client.aio.models.generate_content = AsyncMock(
            return_value=_make_mock_response("Summarized text")
        )
        result = await mock_google_client.invoke("Summarize")
        assert isinstance(result, InvokeResult)
        assert isinstance(result.output, str)

    async def test_lightweight_model_default(self, mock_google_client):
        """invoke() uses _lightweight_model by default."""
        mock_google_client.client.aio.models.generate_content = AsyncMock(
            return_value=_make_mock_response("ok")
        )
        result = await mock_google_client.invoke("test")
        assert result.model == "gemini-3-flash-lite"

    async def test_model_override(self, mock_google_client):
        """Explicit model param overrides _lightweight_model."""
        mock_google_client.client.aio.models.generate_content = AsyncMock(
            return_value=_make_mock_response("ok")
        )
        result = await mock_google_client.invoke("test", model="gemini-2.5-pro")
        assert result.model == "gemini-2.5-pro"

    async def test_structured_output_generation_config(self, mock_google_client):
        """invoke() uses generation_config with response_schema for structured output."""
        mock_google_client.client.aio.models.generate_content = AsyncMock(
            return_value=_make_mock_response('{"entities": ["Alice"], "count": 1}')
        )
        result = await mock_google_client.invoke(
            "Extract entities", output_type=ExtractedData
        )
        assert isinstance(result, InvokeResult)
        assert result.model == "gemini-3-flash-lite"
        # Verify generation_config was set
        call_kwargs = mock_google_client.client.aio.models.generate_content.call_args[1]
        config_obj = call_kwargs.get("config")
        assert config_obj is not None

    async def test_two_call_strategy_when_tools_and_output_type(self, mock_google_client):
        """Two-call strategy: first call with tools, second with structured output."""
        call_count = 0
        responses = [
            _make_mock_response("Alice is 30 years old"),
            _make_mock_response('{"entities": ["Alice"], "count": 1}'),
        ]

        async def mock_generate(**kwargs):
            nonlocal call_count
            resp = responses[min(call_count, 1)]
            call_count += 1
            return resp

        mock_google_client.client.aio.models.generate_content = mock_generate
        # Return empty list so GenerateContentConfig doesn't fail with invalid tool dicts
        mock_google_client._tool_manager.get_tool_schemas.return_value = []

        result = await mock_google_client.invoke(
            "Search and extract", output_type=ExtractedData, use_tools=True
        )
        assert isinstance(result, InvokeResult)
        assert call_count == 2  # Two calls were made

    async def test_error_wrapped_in_invoke_error(self, mock_google_client):
        """Provider errors wrapped in InvokeError."""
        mock_google_client.client.aio.models.generate_content = AsyncMock(
            side_effect=RuntimeError("API quota exceeded")
        )
        with pytest.raises(InvokeError) as exc_info:
            await mock_google_client.invoke("test")
        assert exc_info.value.original is not None

    async def test_not_initialized_raises(self):
        """RuntimeError wrapped in InvokeError when client not initialized."""
        client = _make_client()
        client.client = None
        with pytest.raises(InvokeError):
            await client.invoke("test")

    async def test_custom_parser_applied(self, mock_google_client):
        """custom_parser in StructuredOutputConfig is applied to raw text."""
        from parrot.models.outputs import StructuredOutputConfig, OutputFormat

        mock_google_client.client.aio.models.generate_content = AsyncMock(
            return_value=_make_mock_response("some text")
        )
        parsed = ExtractedData(entities=["Parsed"], count=1)
        config = StructuredOutputConfig(
            output_type=ExtractedData,
            format=OutputFormat.JSON,
            custom_parser=lambda text: parsed,
        )
        result = await mock_google_client.invoke("test", structured_output=config)
        assert result.output is parsed
