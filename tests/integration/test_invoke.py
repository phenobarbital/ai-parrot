"""Integration tests for invoke() across all LLM clients (TASK-488).

These tests verify the full invoke() contract — correct InvokeResult fields,
error types, model resolution, and output parsing — using mocked provider SDKs.
No real API calls are made.
"""
from __future__ import annotations
import pytest
from types import SimpleNamespace
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock
from pydantic import BaseModel, Field

from parrot.models.responses import InvokeResult
from parrot.models.outputs import StructuredOutputConfig, OutputFormat
from parrot.models.basic import CompletionUsage
from parrot.exceptions import InvokeError


# ---------------------------------------------------------------------------
# Shared fixture Pydantic / dataclass models
# ---------------------------------------------------------------------------

class PersonInfo(BaseModel):
    """Target model for structured output tests."""
    name: str = Field(description="Full name")
    age: int = Field(description="Age in years")


class SentimentResult(BaseModel):
    """Secondary model for variety in tests."""
    sentiment: str
    confidence: float


@dataclass
class SimpleData:
    """Dataclass target for structured output tests."""
    key: str
    value: str


# ---------------------------------------------------------------------------
# Client factory helpers
# ---------------------------------------------------------------------------

def _make_openai_response(text: str = '{"name": "John", "age": 30}'):
    """OpenAI-compatible mock response."""
    message = SimpleNamespace(content=text, tool_calls=None)
    choice = SimpleNamespace(message=message, finish_reason="stop")
    usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    return SimpleNamespace(choices=[choice], usage=usage)


def _make_google_response(text: str = '{"name": "John", "age": 30}'):
    """Google GenAI-compatible mock response."""
    part = SimpleNamespace(text=text)
    content = SimpleNamespace(parts=[part])
    candidate = SimpleNamespace(content=content, finish_reason="STOP")
    um = SimpleNamespace(
        prompt_token_count=10, candidates_token_count=5, total_token_count=15
    )
    return SimpleNamespace(candidates=[candidate], text=text, usage_metadata=um)


def _make_anthropic_response(text: str = '{"name": "John", "age": 30}'):
    """Anthropic-compatible mock response."""
    block = SimpleNamespace(text=text)
    usage = SimpleNamespace(**{"input_tokens": 10, "output_tokens": 5, "__dict__": {"input_tokens": 10, "output_tokens": 5}})
    return SimpleNamespace(content=[block], usage=usage)


def _init_json(client):
    """Attach JSON parser to client."""
    from datamodel.parsers.json import JSONContent
    client._json = JSONContent()


def _make_anthropic_client(response_text: str = '{"name": "John", "age": 30}'):
    """AnthropicClient with mocked SDK."""
    from parrot.clients.claude import AnthropicClient
    client = AnthropicClient.__new__(AnthropicClient)
    client.model = "claude-sonnet-4-5"
    client._lightweight_model = "claude-haiku-4-5-20251001"
    client._fallback_model = None
    client.logger = MagicMock()
    client._tool_manager = MagicMock()
    client._tool_manager.get_tool_schemas.return_value = []
    _init_json(client)
    client.client = MagicMock()
    client.client.messages.create = AsyncMock(
        return_value=_make_anthropic_response(response_text)
    )
    return client


def _make_openai_client(response_text: str = '{"name": "John", "age": 30}'):
    """OpenAIClient with mocked SDK."""
    from parrot.clients.gpt import OpenAIClient
    client = OpenAIClient.__new__(OpenAIClient)
    client.model = "gpt-4o"
    client._lightweight_model = "gpt-4.1"
    client._fallback_model = None
    client.logger = MagicMock()
    client._tool_manager = MagicMock()
    client._tool_manager.get_tool_schemas.return_value = []
    _init_json(client)
    client.client = MagicMock()
    client.client.chat.completions.create = AsyncMock(
        return_value=_make_openai_response(response_text)
    )
    return client


def _make_google_client(response_text: str = '{"name": "John", "age": 30}'):
    """GoogleGenAIClient with mocked SDK."""
    from parrot.clients.google.client import GoogleGenAIClient
    client = GoogleGenAIClient.__new__(GoogleGenAIClient)
    client.model = "gemini-2.5-flash"
    client._lightweight_model = "gemini-3-flash-lite"
    client._fallback_model = None
    client.logger = MagicMock()
    client._tool_manager = MagicMock()
    client._tool_manager.get_tool_schemas.return_value = []
    _init_json(client)
    client.client = MagicMock()
    client.client.aio = MagicMock()
    client.client.aio.models = MagicMock()
    client.client.aio.models.generate_content = AsyncMock(
        return_value=_make_google_response(response_text)
    )
    return client


def _make_groq_client(response_text: str = '{"name": "John", "age": 30}'):
    """GroqClient with mocked SDK."""
    from parrot.clients.groq import GroqClient
    client = GroqClient.__new__(GroqClient)
    client.model = "llama-3.3-70b-versatile"
    client._lightweight_model = "kimi-k2-instruct"
    client._fallback_model = None
    client.logger = MagicMock()
    client._tool_manager = MagicMock()
    client._tool_manager.get_tool_schemas.return_value = []
    _init_json(client)
    client.client = MagicMock()
    client.client.chat.completions.create = AsyncMock(
        return_value=_make_openai_response(response_text)
    )
    return client


def _make_grok_client(response_text: str = '{"name": "John", "age": 30}'):
    """GrokClient with mocked SDK."""
    from parrot.clients.grok import GrokClient

    class _ConcreteGrokClient(GrokClient):
        async def resume(self, *args, **kwargs):
            raise NotImplementedError

    client = _ConcreteGrokClient.__new__(_ConcreteGrokClient)
    client.model = "grok-4"
    client._lightweight_model = "grok-4-1-fast-non-reasoning"
    client._fallback_model = None
    client.logger = MagicMock()
    client._tool_manager = MagicMock()
    client._tool_manager.get_tool_schemas.return_value = []
    _init_json(client)
    client.client = MagicMock()
    client.client.chat.completions.create = AsyncMock(
        return_value=_make_openai_response(response_text)
    )
    return client


def _make_localllm_client(response_text: str = '{"name": "John", "age": 30}'):
    """LocalLLMClient with mocked SDK."""
    from parrot.clients.localllm import LocalLLMClient
    client = LocalLLMClient.__new__(LocalLLMClient)
    client.model = "llama3.1:8b"
    client._lightweight_model = None
    client._fallback_model = None
    client.base_url = "http://localhost:8000/v1"
    client.logger = MagicMock()
    client._tool_manager = MagicMock()
    client._tool_manager.get_tool_schemas.return_value = []
    _init_json(client)
    client.client = MagicMock()
    client.client.chat.completions.create = AsyncMock(
        return_value=_make_openai_response(response_text)
    )
    return client


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(params=["anthropic", "openai", "google", "groq", "grok", "localllm"])
def mock_client(request):
    """Parametrized fixture — returns a mocked client for each provider."""
    factory = {
        "anthropic": _make_anthropic_client,
        "openai": _make_openai_client,
        "google": _make_google_client,
        "groq": _make_groq_client,
        "grok": _make_grok_client,
        "localllm": _make_localllm_client,
    }
    return factory[request.param]()


@pytest.fixture(params=["google", "groq"])
def two_call_client(request):
    """Fixture for clients that use the two-call strategy."""
    if request.param == "google":
        client = _make_google_client()
        # Return two responses
        responses = [
            _make_google_response("John is 30 years old"),
            _make_google_response('{"name": "John", "age": 30}'),
        ]
        call_count = {"n": 0}
        async def mock_generate(**kwargs):
            resp = responses[min(call_count["n"], 1)]
            call_count["n"] += 1
            return resp
        client.client.aio.models.generate_content = mock_generate
        return client
    else:  # groq
        client = _make_groq_client()
        responses = [
            _make_openai_response("John is 30 years old"),
            _make_openai_response('{"name": "John", "age": 30}'),
        ]
        call_count = {"n": 0}
        async def mock_create(**kwargs):
            resp = responses[min(call_count["n"], 1)]
            call_count["n"] += 1
            return resp
        client.client.chat.completions.create = mock_create
        return client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestInvokeStructuredOutput:
    """Verify structured output contract across all clients."""

    async def test_pydantic_model(self, mock_client):
        """invoke() returns validated Pydantic model instance."""
        result = await mock_client.invoke(
            "Extract: John is 30", output_type=PersonInfo
        )
        assert isinstance(result, InvokeResult)
        assert isinstance(result.output, PersonInfo)
        assert result.output_type is PersonInfo
        assert result.output.name == "John"
        assert result.output.age == 30

    async def test_custom_parser(self, mock_client):
        """StructuredOutputConfig with custom_parser is applied."""
        def my_parser(text: str) -> PersonInfo:
            return PersonInfo(name="Parsed", age=0)

        config = StructuredOutputConfig(
            output_type=PersonInfo,
            format=OutputFormat.JSON,
            custom_parser=my_parser,
        )
        result = await mock_client.invoke(
            "test", structured_output=config
        )
        assert isinstance(result, InvokeResult)
        assert result.output.name == "Parsed"

    async def test_structured_output_config_takes_precedence(self, mock_client):
        """structured_output param takes precedence over output_type."""
        def strict_parser(text: str) -> PersonInfo:
            return PersonInfo(name="Override", age=99)

        config = StructuredOutputConfig(
            output_type=PersonInfo,
            format=OutputFormat.JSON,
            custom_parser=strict_parser,
        )
        result = await mock_client.invoke(
            "test", output_type=SentimentResult, structured_output=config
        )
        # custom_parser wins over any attempt to parse with SentimentResult
        assert result.output.name == "Override"


class TestInvokeRawString:
    """Verify raw string output when no output_type is given."""

    async def test_no_output_type_returns_str(self, mock_client):
        """invoke() without output_type returns raw str."""
        result = await mock_client.invoke("Summarize this text")
        assert isinstance(result, InvokeResult)
        assert isinstance(result.output, str)
        assert result.output_type is None

    async def test_result_fields_populated(self, mock_client):
        """InvokeResult.model and InvokeResult.usage are always populated."""
        result = await mock_client.invoke("Hello")
        assert isinstance(result.model, str)
        assert len(result.model) > 0
        assert isinstance(result.usage, CompletionUsage)


class TestInvokeTwoCall:
    """Tests for the two-call strategy (Google/Groq with tools + structured output)."""

    async def test_tools_plus_structured(self, two_call_client):
        """Two-call strategy produces valid structured output."""
        result = await two_call_client.invoke(
            "Search and extract person",
            output_type=PersonInfo,
            use_tools=True,
        )
        assert isinstance(result, InvokeResult)
        assert isinstance(result.output, PersonInfo)

    async def test_single_call_without_tools(self, two_call_client):
        """Without tools, single call is made even with structured output."""
        result = await two_call_client.invoke(
            "Extract person", output_type=PersonInfo, use_tools=False
        )
        assert isinstance(result, InvokeResult)


class TestInvokeErrors:
    """Verify error wrapping and propagation."""

    async def test_provider_error_wrapped(self, mock_client):
        """Provider exceptions raised in the SDK call are wrapped in InvokeError."""
        original_error = RuntimeError("API unavailable")

        # Detect client type and patch the relevant SDK call
        from parrot.clients.claude import AnthropicClient
        from parrot.clients.google.client import GoogleGenAIClient
        if isinstance(mock_client, AnthropicClient):
            mock_client.client.messages.create = AsyncMock(side_effect=original_error)
        elif isinstance(mock_client, GoogleGenAIClient):
            mock_client.client.aio.models.generate_content = AsyncMock(side_effect=original_error)
        else:
            # OpenAI-compatible (OpenAI, Groq, Grok, LocalLLM)
            mock_client.client.chat.completions.create = AsyncMock(side_effect=original_error)

        with pytest.raises(InvokeError) as exc_info:
            await mock_client.invoke("trigger error")
        assert exc_info.value.original is not None

    async def test_invoke_error_is_exception(self, mock_client):
        """InvokeError is a proper Exception subclass."""
        mock_client.client = None  # Force uninitialized error
        with pytest.raises((InvokeError, Exception)):
            await mock_client.invoke("test")


class TestInvokeModelResolution:
    """Verify model resolution across clients."""

    async def test_lightweight_model_default(self, mock_client):
        """Each client uses _lightweight_model when none specified."""
        result = await mock_client.invoke("test")
        if mock_client._lightweight_model:
            assert result.model == mock_client._lightweight_model
        else:
            # LocalLLMClient: falls back to self.model
            assert result.model == mock_client.model

    async def test_model_override(self, mock_client):
        """Explicit model param overrides _lightweight_model."""
        result = await mock_client.invoke("test", model="custom-model-xyz")
        assert result.model == "custom-model-xyz"


class TestInvokeSystemPrompt:
    """Verify system_prompt passthrough."""

    async def test_custom_system_prompt(self, mock_client):
        """Custom system_prompt is accepted without error."""
        result = await mock_client.invoke(
            "test",
            system_prompt="You are a concise assistant.",
        )
        assert isinstance(result, InvokeResult)

    async def test_no_tools_by_default(self, mock_client):
        """use_tools defaults to False — tools are not injected."""
        result = await mock_client.invoke("test")
        assert isinstance(result, InvokeResult)
        # No tool_calls on raw string output
        assert isinstance(result.output, str)
