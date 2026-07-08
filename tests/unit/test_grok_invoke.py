"""Unit tests for GrokClient.invoke() (TASK-486)."""
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from pydantic import BaseModel

from parrot.models.responses import InvokeResult
from parrot.exceptions import InvokeError


class AnalysisResult(BaseModel):
    """Fixture model for structured output tests."""
    summary: str
    key_points: list


def _make_mock_response(text: str = '{"summary": "test", "key_points": ["a"]}'):
    """Build a mock xai_sdk Response object."""
    usage = SimpleNamespace(
        prompt_tokens=10, completion_tokens=5, total_tokens=15,
        reasoning_tokens=0, cached_prompt_text_tokens=0, prompt_image_tokens=0,
    )
    return SimpleNamespace(
        content=text,
        tool_calls=[],
        usage=usage,
        finish_reason="FINISH_REASON_STOP",
    )


def _make_mock_chat(response=None):
    """Build a mock stateful chat object with sample()/parse()/append()."""
    resp = response or _make_mock_response()
    chat = MagicMock()
    chat.sample = AsyncMock(return_value=resp)
    chat.parse = AsyncMock(return_value=(resp, None))
    chat.append = MagicMock(return_value=chat)
    return chat


def _make_mock_sdk_client(chat=None):
    """Build a mock xai_sdk AsyncClient."""
    mock_chat = chat or _make_mock_chat()
    sdk_client = MagicMock()
    sdk_client.chat = MagicMock()
    sdk_client.chat.create = MagicMock(return_value=mock_chat)
    return sdk_client, mock_chat


def _make_client():
    """Create GrokClient without network setup."""
    from parrot.clients.grok import GrokClient

    class _ConcreteGrokClient(GrokClient):
        """Concrete test subclass."""
        async def resume(self, *args, **kwargs):
            raise NotImplementedError

    client = _ConcreteGrokClient.__new__(_ConcreteGrokClient)
    client.model = "grok-4.3"
    client._lightweight_model = "grok-4.20-non-reasoning"
    client._fallback_model = None
    client.logger = MagicMock()
    client._tool_manager = MagicMock()
    client._tool_manager.get_tool_schemas.return_value = []
    client._tool_manager.tools = {}
    client._clients_by_loop = {}
    from datamodel.parsers.json import JSONContent
    client._json = JSONContent()
    return client


@pytest.fixture
def mock_grok_client():
    """GrokClient with mocked SDK chat interface."""
    client = _make_client()
    sdk_client, mock_chat = _make_mock_sdk_client()
    client.get_client = AsyncMock(return_value=sdk_client)
    client._mock_chat = mock_chat
    client._sdk_client = sdk_client
    return client


class TestGrokInvoke:
    """Tests for GrokClient.invoke()."""

    async def test_raw_string_output(self, mock_grok_client):
        """invoke() without output_type returns raw text."""
        mock_grok_client._mock_chat.sample = AsyncMock(
            return_value=_make_mock_response("Hello world")
        )
        result = await mock_grok_client.invoke("Hello")
        assert isinstance(result, InvokeResult)
        assert isinstance(result.output, str)

    async def test_lightweight_model_default(self, mock_grok_client):
        """invoke() uses _lightweight_model by default."""
        mock_grok_client._mock_chat.sample = AsyncMock(
            return_value=_make_mock_response("ok")
        )
        result = await mock_grok_client.invoke("test")
        assert result.model == "grok-4.20-non-reasoning"

    async def test_model_override(self, mock_grok_client):
        """Explicit model param overrides _lightweight_model."""
        mock_grok_client._mock_chat.sample = AsyncMock(
            return_value=_make_mock_response("ok")
        )
        result = await mock_grok_client.invoke("test", model="grok-4.3")
        assert result.model == "grok-4.3"

    async def test_pydantic_structured_output_uses_parse(self, mock_grok_client):
        """invoke() with Pydantic output_type uses chat.parse()."""
        parsed = AnalysisResult(summary="test", key_points=["a"])
        resp = _make_mock_response('{"summary": "test", "key_points": ["a"]}')
        mock_grok_client._mock_chat.parse = AsyncMock(return_value=(resp, parsed))
        result = await mock_grok_client.invoke(
            "Analyze this", output_type=AnalysisResult
        )
        mock_grok_client._mock_chat.parse.assert_awaited_once()
        assert result.output is parsed

    async def test_error_wrapped_in_invoke_error(self, mock_grok_client):
        """Provider errors wrapped in InvokeError."""
        mock_grok_client._mock_chat.sample = AsyncMock(
            side_effect=RuntimeError("API failed")
        )
        with pytest.raises(InvokeError) as exc_info:
            await mock_grok_client.invoke("test")
        assert exc_info.value.original is not None

    async def test_custom_parser_applied(self, mock_grok_client):
        """custom_parser in StructuredOutputConfig is applied."""
        from parrot.models.outputs import StructuredOutputConfig, OutputFormat

        mock_grok_client._mock_chat.sample = AsyncMock(
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
        client.get_client = AsyncMock(side_effect=RuntimeError("no client"))
        with pytest.raises(InvokeError):
            await client.invoke("test")
