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
    client._clients_by_loop = {}
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
    import asyncio
    client = _make_client()
    mock_models = MagicMock()
    mock_models.generate_content = AsyncMock(
        return_value=_make_mock_response()
    )
    sdk_client = MagicMock()
    sdk_client.aio = MagicMock()
    sdk_client.aio.models = mock_models
    
    # Redefine the client property to bypass loop cache entirely in testing
    type(client).client = property(lambda self: sdk_client, lambda self, val: None)
    
    async def mock_ensure_client(model=None, **hints):
        return sdk_client
        
    client._ensure_client = mock_ensure_client
    
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
        """invoke() uses _lightweight_model when the caller selected no model.

        ``AbstractClient.__init__`` sets ``self.model`` only from an explicit
        ``model=`` kwarg, so ``None`` is the ``LLMFactory.create("google")``
        case — the one the lightweight default exists for.
        """
        mock_google_client.model = None
        mock_google_client.client.aio.models.generate_content = AsyncMock(
            return_value=_make_mock_response("ok")
        )
        result = await mock_google_client.invoke("test")
        assert result.model == "gemini-3-flash-lite"

    async def test_selected_model_outranks_lightweight(self, mock_google_client):
        """A model selected at construction beats _lightweight_model.

        The fixture's ``self.model`` stands in for
        ``LLMFactory.create("google:gemini-2.5-flash")``; invoke() must run
        that, not the cheap default.
        """
        mock_google_client.client.aio.models.generate_content = AsyncMock(
            return_value=_make_mock_response("ok")
        )
        result = await mock_google_client.invoke("test")
        assert result.model == "gemini-2.5-flash"

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
        # The fixture selects gemini-2.5-flash explicitly, which outranks
        # _lightweight_model; this test is about the config, not the model.
        assert result.model == "gemini-2.5-flash"
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

    async def test_warn_free_safe_extract_text_with_function_call(self, mock_google_client):
        """_safe_extract_text avoids accessing .text on responses with function calls."""
        part = SimpleNamespace(function_call=SimpleNamespace(name="my_tool", args={}))
        content = SimpleNamespace(parts=[part])
        candidate = SimpleNamespace(content=content, finish_reason="STOP")
        
        class WarningProneResponse:
            def __init__(self):
                self.candidates = [candidate]
            
            @property
            def text(self) -> str:
                raise AssertionError("Accessed .text property on response with function call!")

        resp = WarningProneResponse()
        extracted = mock_google_client._safe_extract_text(resp)
        assert extracted == ""  # No text part in response

    async def test_warn_free_from_gemini_with_function_call(self):
        """AIMessageFactory.from_gemini avoids accessing .text on responses with function calls."""
        from parrot.models.responses import AIMessageFactory
        
        part = SimpleNamespace(function_call=SimpleNamespace(name="my_tool", args={}))
        content = SimpleNamespace(parts=[part])
        candidate = SimpleNamespace(content=content, finish_reason="STOP")
        usage_metadata = SimpleNamespace(
            prompt_token_count=10,
            candidates_token_count=5,
            total_token_count=15,
        )
        
        class WarningProneResponse:
            def __init__(self):
                self.candidates = [candidate]
                self.usage_metadata = usage_metadata
            
            @property
            def text(self) -> str:
                raise AssertionError("Accessed .text property on response with function call!")

        resp = WarningProneResponse()
        
        # 1. When text_response is provided (even if empty)
        msg1 = AIMessageFactory.from_gemini(
            response=resp,
            input_text="prompt",
            model="gemini-2.5-flash",
            text_response=""
        )
        assert msg1.output == ""

        # 2. When text_response is NOT provided (fallback path)
        msg2 = AIMessageFactory.from_gemini(
            response=resp,
            input_text="prompt",
            model="gemini-2.5-flash",
            text_response=None
        )
        assert msg2.output == ""



def _make_extractable_response(text: str, finish_reason: str = "STOP"):
    """A mock response whose text ``_safe_extract_text`` can actually read.

    The shared ``_make_mock_response`` builds parts as bare ``SimpleNamespace``
    objects with no ``thought`` attribute. ``_safe_extract_text`` evaluates
    ``part.thought is True`` inside a guarded block, so that raises and the
    extractor returns ``""`` — which is why tests built on it never exercise
    real parsing. Giving the part ``thought``/``function_call`` fixes that.
    """
    part = SimpleNamespace(text=text, thought=False, function_call=None)
    content = SimpleNamespace(parts=[part])
    candidate = SimpleNamespace(content=content, finish_reason=finish_reason)
    usage_metadata = SimpleNamespace(
        prompt_token_count=10, candidates_token_count=5, total_token_count=15
    )
    return SimpleNamespace(candidates=[candidate], text=text, usage_metadata=usage_metadata)


class TestGoogleInvokeReformatRecovery:
    """invoke() must never hand back a raw ``str`` for a structured request.

    ``_parse_structured_output`` returns the input text verbatim when the
    response is not valid JSON. Before this recovery existed, invoke() passed
    that string straight through as ``.output``, so a caller that asked for a
    Pydantic model received a ``str`` and crashed far from the cause. The
    recovery mirrors the streaming/tool path's ``isinstance(parsed, str)``
    fallback: reformat via a second call, and raise if that also fails.
    """

    async def test_working_model_is_untouched(self, mock_google_client):
        """A response that parses cleanly must not trigger a reformat call.

        Blast-radius guard: every model that satisfies the schema today keeps
        its exact behaviour, with no extra LLM call.
        """
        mock_google_client.client.aio.models.generate_content = AsyncMock(
            return_value=_make_extractable_response('{"entities": ["Alice"], "count": 1}')
        )
        mock_google_client._reformat_to_structured = AsyncMock(
            side_effect=AssertionError("reformat must not run when the parse succeeds")
        )
        result = await mock_google_client.invoke(
            "extract", output_type=ExtractedData, model="gemini-2.5-flash"
        )
        assert isinstance(result.output, ExtractedData)
        assert result.output.count == 1
        mock_google_client._reformat_to_structured.assert_not_called()

    async def test_raw_string_triggers_reformat_recovery(self, mock_google_client):
        """A parse that leaks a raw string is recovered via a reformat call."""
        mock_google_client.client.aio.models.generate_content = AsyncMock(
            return_value=_make_extractable_response("I could not produce JSON, sorry.")
        )
        recovered = ExtractedData(entities=["Alice"], count=1)
        mock_google_client._reformat_to_structured = AsyncMock(return_value=recovered)

        result = await mock_google_client.invoke(
            "extract", output_type=ExtractedData, model="gemini-2.5-flash"
        )

        assert result.output is recovered
        mock_google_client._reformat_to_structured.assert_awaited_once()
        # The raw model text — not the prompt — is what gets reformatted.
        assert (
            mock_google_client._reformat_to_structured.await_args.args[0]
            == "I could not produce JSON, sorry."
        )

    async def test_reformat_still_failing_raises_invoke_error(self, mock_google_client):
        """When reformat also returns text, invoke() raises instead of leaking it."""
        mock_google_client.client.aio.models.generate_content = AsyncMock(
            return_value=_make_extractable_response("still not json")
        )
        mock_google_client._reformat_to_structured = AsyncMock(
            return_value="still not json either"
        )

        with pytest.raises(InvokeError, match="even after reformat recovery"):
            await mock_google_client.invoke(
                "extract", output_type=ExtractedData, model="gemini-2.5-flash"
            )

    async def test_empty_response_does_not_trigger_reformat(self, mock_google_client):
        """A blank extraction must not burn a second call on nothing.

        An empty response also parses to ``""``, which is a ``str`` — but there
        is no text for a reformat call to work from, so recovery is skipped.
        """
        mock_google_client.client.aio.models.generate_content = AsyncMock(
            return_value=_make_extractable_response("   ")
        )
        mock_google_client._reformat_to_structured = AsyncMock(
            side_effect=AssertionError("must not reformat an empty response")
        )
        result = await mock_google_client.invoke(
            "extract", output_type=ExtractedData, model="gemini-2.5-flash"
        )
        assert isinstance(result.output, str)
        mock_google_client._reformat_to_structured.assert_not_called()

    async def test_custom_parser_path_skips_recovery(self, mock_google_client):
        """A caller-supplied custom_parser owns its own return type."""
        from parrot.models.outputs import StructuredOutputConfig

        mock_google_client.client.aio.models.generate_content = AsyncMock(
            return_value=_make_extractable_response("anything")
        )
        mock_google_client._reformat_to_structured = AsyncMock(
            side_effect=AssertionError("custom_parser results must not be reformatted")
        )
        cfg = StructuredOutputConfig(
            output_type=ExtractedData, custom_parser=lambda text: f"parsed:{text}"
        )
        result = await mock_google_client.invoke("x", structured_output=cfg)
        assert result.output == "parsed:anything"
        mock_google_client._reformat_to_structured.assert_not_called()
