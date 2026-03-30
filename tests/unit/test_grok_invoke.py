"""Unit tests for GrokClient.invoke() (TASK-486)."""
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from pydantic import BaseModel

from parrot.models.responses import InvokeResult
from parrot.exceptions import InvokeError


class AnalysisResult(BaseModel):
    """Fixture model for structured output tests."""
    summary: str
    key_points: list


def _make_mock_response(text: str = '{"summary": "test", "key_points": ["a"]}'):
    """Build a mock xAI response."""
    message = SimpleNamespace(content=text, tool_calls=None)
    choice = SimpleNamespace(message=message, finish_reason="stop")
    usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    return SimpleNamespace(choices=[choice], usage=usage)


def _make_client():
    """Create GrokClient without network setup."""
    from parrot.clients.grok import GrokClient

    class _ConcreteGrokClient(GrokClient):
        """Concrete test subclass."""
        async def resume(self, *args, **kwargs):
            raise NotImplementedError

    client = _ConcreteGrokClient.__new__(_ConcreteGrokClient)
    client.model = "grok-4"
    client._lightweight_model = "grok-4-1-fast-non-reasoning"
    client._fallback_model = None
    client.logger = MagicMock()
    client._tool_manager = MagicMock()
    client._tool_manager.get_tool_schemas.return_value = []
    client._tool_manager.tools = {}
    from datamodel.parsers.json import JSONContent
    client._json = JSONContent()
    return client


@pytest.fixture
def mock_grok_client():
    """GrokClient with mocked SDK."""
    client = _make_client()
    client.client = MagicMock()
    client.client.chat = MagicMock()
    client.client.chat.completions = MagicMock()
    client.client.chat.completions.create = AsyncMock(
        return_value=_make_mock_response()
    )
    return client


class TestGrokInvoke:
    """Tests for GrokClient.invoke()."""

    async def test_raw_string_output(self, mock_grok_client):
        """invoke() without output_type returns raw text."""
        mock_grok_client.client.chat.completions.create = AsyncMock(
            return_value=_make_mock_response("Hello world")
        )
        result = await mock_grok_client.invoke("Hello")
        assert isinstance(result, InvokeResult)
        assert isinstance(result.output, str)

    async def test_lightweight_model_default(self, mock_grok_client):
        """invoke() uses _lightweight_model by default."""
        mock_grok_client.client.chat.completions.create = AsyncMock(
            return_value=_make_mock_response("ok")
        )
        result = await mock_grok_client.invoke("test")
        assert result.model == "grok-4-1-fast-non-reasoning"

    async def test_model_override(self, mock_grok_client):
        """Explicit model param overrides _lightweight_model."""
        mock_grok_client.client.chat.completions.create = AsyncMock(
            return_value=_make_mock_response("ok")
        )
        result = await mock_grok_client.invoke("test", model="grok-4")
        assert result.model == "grok-4"

    async def test_native_json_schema_response_format(self, mock_grok_client):
        """invoke() sets json_schema response_format for structured output."""
        mock_grok_client.client.chat.completions.create = AsyncMock(
            return_value=_make_mock_response(
                '{"summary": "test", "key_points": ["a"]}'
            )
        )
        await mock_grok_client.invoke(
            "Analyze this", output_type=AnalysisResult
        )
        call_kwargs = mock_grok_client.client.chat.completions.create.call_args[1]
        assert "response_format" in call_kwargs
        assert call_kwargs["response_format"]["type"] == "json_schema"
        assert call_kwargs["response_format"]["json_schema"]["strict"] is True

    async def test_error_wrapped_in_invoke_error(self, mock_grok_client):
        """Provider errors wrapped in InvokeError."""
        mock_grok_client.client.chat.completions.create = AsyncMock(
            side_effect=RuntimeError("API failed")
        )
        with pytest.raises(InvokeError) as exc_info:
            await mock_grok_client.invoke("test")
        assert exc_info.value.original is not None

    async def test_custom_parser_applied(self, mock_grok_client):
        """custom_parser in StructuredOutputConfig is applied."""
        from parrot.models.outputs import StructuredOutputConfig, OutputFormat

        mock_grok_client.client.chat.completions.create = AsyncMock(
            return_value=_make_mock_response("some text")
        )
        parsed = AnalysisResult(summary="Parsed", key_points=["p1"])
        config = StructuredOutputConfig(
            output_type=AnalysisResult,
            format=OutputFormat.JSON,
            custom_parser=lambda text: parsed,
        )
        result = await mock_grok_client.invoke("test", structured_output=config)
        assert result.output is parsed

    async def test_not_initialized_raises(self):
        """InvokeError raised when client not initialized."""
        client = _make_client()
        client.client = None
        with pytest.raises(InvokeError):
            await client.invoke("test")
