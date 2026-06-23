import pytest

from unittest.mock import AsyncMock, MagicMock, patch
from PIL import Image
from parrot.clients.google import GoogleGenAIClient
from parrot.models import AIMessage, CompletionUsage, ToolCall


@pytest.mark.asyncio
async def test_google_ask():
    # Mock the genai client
    with patch("parrot.clients.google.client.genai.Client") as mock_genai_cls:
        # Setup mock client instance
        mock_client_instance = MagicMock()
        mock_genai_cls.return_value = mock_client_instance

        # Setup mock response
        mock_response = MagicMock()
        mock_response.candidates = [MagicMock()]

        # FIX: Ensure function_call is None to avoid Pydantic validation error
        mock_part = MagicMock(text="Hello, world!")
        mock_part.function_call = None
        mock_part.executable_code = None
        mock_part.code_execution_result = None
        mock_response.candidates[0].content.parts = [mock_part]

        # FIX: The client uses chat.send_message for ask() by default (multi-turn)
        mock_chat = MagicMock()
        mock_chat.send_message = AsyncMock(return_value=mock_response)

        # Mock chats.create to return our mock chat
        mock_client_instance.aio.chats.create = MagicMock(return_value=mock_chat)

        # Initialize our client
        client = GoogleGenAIClient(api_key="fake_key")
        client.get_client = AsyncMock(return_value=mock_client_instance)
        client.logger = MagicMock()  # Mock logger to handle 'notice' calls

        # Test ask
        with patch("parrot.clients.google.client.AIMessageFactory") as mock_factory:
            # Mock the factory method
            mock_factory.from_gemini.return_value = AIMessage(
                input="Hi",
                output="Hello, world!",
                response="Hello, world!",
                model="gemini-2.5-flash",
                provider="google_genai",
                usage=CompletionUsage(),
            )

            response = await client.ask(prompt="Hi")

            assert isinstance(response, AIMessage)
            assert "Hello, world!" in response.content


def mock_stream_chunk(text):
    chunk = MagicMock()
    chunk.text = text
    chunk.candidates = [MagicMock()]  # Candidate for finish_reason check
    # Ensure no function call in chunk for basic test
    chunk_part = MagicMock()
    chunk_part.function_call = None
    chunk_part.executable_code = None
    chunk.candidates[0].content.parts = [chunk_part]
    return chunk


@pytest.mark.asyncio
async def test_google_ask_stream():
    with patch("parrot.clients.google.client.genai.Client") as mock_genai_cls:
        mock_client_instance = MagicMock()
        mock_genai_cls.return_value = mock_client_instance

        # Setup mock stream iterator (async generator)
        async def async_iter():
            yield mock_stream_chunk("Hello")
            yield mock_stream_chunk(" world")

        # Setup mock stream object
        # The code iterates directly: async for chunk in await chat.send_message_stream(...)
        mock_stream = MagicMock()
        mock_stream.__aiter__.side_effect = async_iter

        # Setup mock chat
        mock_chat = MagicMock()
        # send_message_stream is awaited, so it must be AsyncMock returning the stream
        mock_chat.send_message_stream = AsyncMock(return_value=mock_stream)

        # chats.create returns mock_chat
        mock_client_instance.aio.chats.create = MagicMock(return_value=mock_chat)

        client = GoogleGenAIClient(api_key="fake_key")
        client.get_client = AsyncMock(return_value=mock_client_instance)
        await client._ensure_client(model="gemini-2.5-flash")

        chunks = []
        async for chunk in client.ask_stream("Hi"):
            chunks.append(chunk)

        assert "".join(chunks) == "Hello world"


@pytest.mark.asyncio
async def test_google_deep_research_ask_accepts_parameters():
    """Test that Google client accepts deep_research parameters without error."""
    mock_genai = MagicMock()
    mock_client = MagicMock()
    mock_genai.Client.return_value = mock_client

    # Mock the response
    # Mock interactions.create which is used in _deep_research_ask
    mock_interactions = MagicMock()
    mock_client.interactions = mock_interactions

    # Setup mock stream (synchronous iterator)
    mock_chunk = MagicMock()
    mock_chunk.event_type = "content.delta"
    mock_chunk.delta.type = "text"
    mock_chunk.delta.text = "Research result"
    mock_chunk.event_id = "evt_123"

    # interactions.create returns a synchronous stream
    mock_interactions.create.return_value = [mock_chunk]

    with patch("parrot.clients.google.client.genai", mock_genai):
        client = GoogleGenAIClient(api_key="fake_key")
        client.get_client = AsyncMock(return_value=mock_client)
        await client._ensure_client()

        # Should not raise - falls back to standard ask
        response = await client.ask(
            "Research quantum computing",
            deep_research=True,
            background=True,
            file_search_store_names=["test-store"],
        )

        assert response is not None
        assert "Research result" in response.response


@pytest.mark.asyncio
async def test_google_deep_research_ask_stream_accepts_parameters():
    """Test that Google client ask_stream accepts deep_research parameters."""
    mock_genai = MagicMock()
    mock_client = MagicMock()
    mock_genai.Client.return_value = mock_client

    # Mock streaming response
    async def mock_text_stream():
        for chunk in ["Hello", " ", "world"]:
            yield chunk

    mock_stream = MagicMock()
    mock_stream.text_stream = mock_text_stream()
    mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
    mock_stream.__aexit__ = AsyncMock(return_value=None)

    mock_chat = MagicMock()
    mock_chat.send_message_stream.return_value = mock_stream
    mock_client.aio.chats.create.return_value = mock_chat

    with patch("parrot.clients.google.client.genai", mock_genai):
        client = GoogleGenAIClient(api_key="fake_key")
        client.get_client = AsyncMock(return_value=mock_client)
        await client._ensure_client(model="gemini-2.5-flash")

        chunks = []
        async for chunk in client.ask_stream(
            "Research AI",
            deep_research=True,
            agent_config={"thinking_summaries": "auto"},
        ):
            chunks.append(chunk)

        assert len(chunks) > 0


def test_google_tool_result_coerces_non_string_keys():
    client = GoogleGenAIClient(api_key="fake_key")
    result = {
        1: "one",
        "nested": {2: "two"},
        "items": [{3: "three"}],
    }

    output = client._process_tool_result_for_api(result)

    assert output["result"]["1"] == "one"
    assert output["result"]["nested"]["2"] == "two"
    assert output["result"]["items"][0]["3"] == "three"


class _FakeGeminiPart:
    def __init__(
        self,
        text: str | None = None,
        thought: bool = False,
        thought_signature: bytes | None = None,
    ) -> None:
        self.text = text
        self.thought = thought
        self.thought_signature = thought_signature
        self.function_call = None
        self.executable_code = None
        self.code_execution_result = None


class _FakeGeminiContent:
    def __init__(self, parts: list[_FakeGeminiPart]) -> None:
        self.parts = parts


class _FakeGeminiCandidate:
    def __init__(self, parts: list[_FakeGeminiPart]) -> None:
        self.content = _FakeGeminiContent(parts)


class _FakeGeminiResponse:
    def __init__(self, parts: list[_FakeGeminiPart], text: str) -> None:
        self.candidates = [_FakeGeminiCandidate(parts)]
        self.text = text


def test_safe_extract_text_prefers_parts_over_flattened_response_text():
    client = GoogleGenAIClient(api_key="fake_key")
    response = _FakeGeminiResponse(
        parts=[_FakeGeminiPart(text="Here are the available models.")],
        text=(
            "The user wants to list models.\n" "I will call the model-listing tool.\n" "Here are the available models."
        ),
    )

    assert client._safe_extract_text(response) == "Here are the available models."


def test_safe_extract_text_skips_thought_parts():
    client = GoogleGenAIClient(api_key="fake_key")
    response = _FakeGeminiResponse(
        parts=[
            _FakeGeminiPart(text="The user wants to list models.", thought=True),
            _FakeGeminiPart(text="Here are the available models."),
        ],
        text="The user wants to list models.\nHere are the available models.",
    )

    assert client._safe_extract_text(response) == "Here are the available models."


def test_truncate_large_list_result():
    """A list exceeding max chars is trimmed to fewer items with metadata."""
    client = GoogleGenAIClient(api_key="fake_key")
    # Use a small limit to make the test deterministic
    client.MAX_TOOL_RESULT_CHARS = 200

    big_list = [{"id": i, "name": f"item_{i}"} for i in range(100)]
    output = client._process_tool_result_for_api(big_list)

    result = output["result"]
    assert isinstance(result, list)
    # Last element should be the truncation metadata
    meta = result[-1]
    assert meta["_truncated"] is True
    assert meta["_total_items"] == 100
    assert meta["_kept_items"] < 100
    assert meta["_kept_items"] >= 1


def test_truncate_large_dict_with_list():
    """A dict whose largest value is a list gets that list trimmed."""
    client = GoogleGenAIClient(api_key="fake_key")
    client.MAX_TOOL_RESULT_CHARS = 300

    data = {
        "metadata": {"source": "test"},
        "items": [{"id": i, "value": f"v_{i}"} for i in range(200)],
    }
    output = client._process_tool_result_for_api(data)

    result = output["result"]
    assert isinstance(result, dict)
    # metadata key should be preserved intact
    assert result["metadata"] == {"source": "test"}
    # items list should be truncated with metadata appended
    assert isinstance(result["items"], list)
    assert len(result["items"]) < 200
    meta = result["items"][-1]
    assert meta["_truncated"] is True


def test_truncate_result_within_limit():
    """Results under the limit pass through unchanged."""
    client = GoogleGenAIClient(api_key="fake_key")

    small = [{"id": 1}, {"id": 2}]
    output = client._process_tool_result_for_api(small)

    result = output["result"]
    assert isinstance(result, list)
    assert len(result) == 2
    assert result[0]["id"] == 1


def test_tool_result_redacts_environment_key_view():
    client = GoogleGenAIClient(api_key="fake_key")
    leaked = "KeysView(environ({'JIRA_API_TOKEN': 'super-secret-value', " "'NORMAL_SETTING': 'visible'}))"

    output = client._process_tool_result_for_api(leaked)

    assert "super-secret-value" not in output["result"]
    # FEAT-252: OutputScrubber emits reason-tagged markers (***REDACTED:<reason>***) or plain [REDACTED]
    assert "REDACTED" in output["result"]
    assert "NORMAL_SETTING" in output["result"]


def test_simple_summary_withholds_sensitive_tool_string_result():
    client = GoogleGenAIClient(api_key="fake_key")
    tool_call = ToolCall(
        id="call_1",
        name="python_repl",
        arguments={"code": "import os"},
        result="KeysView(environ({'JIRA_API_TOKEN': 'super-secret-value'}))",
    )

    summary = client._create_simple_summary([tool_call])

    assert "super-secret-value" not in summary
    assert "withheld for safety" in summary


# ── FEAT-193 TASK-1303: capability helper + configurable whitelist tests ─────

from parrot.models.google import GoogleModel


class TestSupportsCombinedToolsAndSchema:
    """Unit tests for the FEAT-193 capability helper."""

    DEFAULT_PREFIXES = GoogleGenAIClient._default_combined_call_prefixes

    def test_is_staticmethod(self):
        """Helper is a @staticmethod (matches the _is_gemini3_model pattern)."""
        descriptor = GoogleGenAIClient.__dict__["_supports_combined_tools_and_schema"]
        assert isinstance(descriptor, staticmethod)

    @pytest.mark.parametrize(
        "model",
        [
            "gemini-3.1-pro-preview",
            "gemini-3.5-flash",
            "gemini-3.1-flash-lite-preview",
            # also matches longer suffixes the API may publish later
            "gemini-3.5-flash-001",
        ],
    )
    def test_whitelisted_returns_true(self, model):
        assert GoogleGenAIClient._supports_combined_tools_and_schema(model, self.DEFAULT_PREFIXES) is True

    @pytest.mark.parametrize(
        "model",
        [
            "gemini-2.5-pro",
            "gemini-2.5-flash",
            "gemini-2.0-flash",
            "gemini-3-flash-preview",  # NOT in the prefix list — 3-flash without the .5
        ],
    )
    def test_unwhitelisted_returns_false(self, model):
        assert GoogleGenAIClient._supports_combined_tools_and_schema(model, self.DEFAULT_PREFIXES) is False

    @pytest.mark.parametrize("model", ["", None])
    def test_falsy_input_returns_false(self, model):
        assert GoogleGenAIClient._supports_combined_tools_and_schema(model, self.DEFAULT_PREFIXES) is False

    def test_accepts_googlemodel_enum(self):
        """Helper normalises GoogleModel enum members via _as_model_str."""
        assert (
            GoogleGenAIClient._supports_combined_tools_and_schema(
                GoogleModel.GEMINI_3_PRO_PREVIEW, self.DEFAULT_PREFIXES
            )
            is True
        )

    def test_empty_prefixes_disables_combined_mode(self):
        """Passing an empty prefix tuple is the documented kill switch."""
        assert GoogleGenAIClient._supports_combined_tools_and_schema("gemini-3.5-flash", ()) is False


class TestCombinedCallPrefixesResolution:
    """Constructor-kwarg resolution for the configurable whitelist."""

    def test_default_when_kwarg_omitted(self):
        client = GoogleGenAIClient(api_key="fake")
        assert client._combined_call_prefixes == GoogleGenAIClient._default_combined_call_prefixes

    def test_explicit_kwarg_overrides_default(self):
        client = GoogleGenAIClient(api_key="fake", combined_call_prefixes=("foo", "bar"))
        assert client._combined_call_prefixes == ("foo", "bar")

    def test_kwarg_coerced_to_tuple(self):
        """List / generator inputs are coerced to tuple."""
        client = GoogleGenAIClient(api_key="fake", combined_call_prefixes=["foo", "bar"])
        assert client._combined_call_prefixes == ("foo", "bar")
        assert isinstance(client._combined_call_prefixes, tuple)


# ── FEAT-193 TASK-1307: Combined-mode regression tests ────────────────────────

import logging
from pydantic import Field as _Field
from parrot.core.events.lifecycle.events.client import AfterClientCallEvent


def _make_weather_schema():
    """Return a real Pydantic model class for structured output tests."""
    from pydantic import BaseModel

    class WeatherReport(BaseModel):
        location: str = _Field(...)
        temperature: float = _Field(...)
        condition: str = _Field(...)

    return WeatherReport


def _make_fake_response(text: str):
    """Build a minimal fake response that _safe_extract_text can pull text from."""
    part = _FakeGeminiPart(text=text)
    response = _FakeGeminiResponse(parts=[part], text=text)
    # The multiturn loop checks response.function_calls; add an empty list.
    response.function_calls = []
    return response


def _register_fake_tool(client):
    """Register a minimal fake tool so _use_tools=True takes effect.

    Without at least one registered tool, ask() with use_tools=True falls
    back to _use_tools=False (line 2167-2173 in client.py).
    """
    from parrot.tools.abstract import AbstractTool

    class _FakeTool(AbstractTool):
        name = "fake_tool"
        description = "Fake tool for testing"

        def get_schema(self):
            return {
                "name": self.name,
                "description": self.description,
                "parameters": {"type": "object", "properties": {}, "required": []},
            }

        async def _execute(self, **kwargs):
            return {}

    client.tool_manager.register_tool(_FakeTool())


def _build_mocked_client(combined_call_prefixes=None):
    """Return (client, mocks_dict) with the Google GenAI SDK boundary fully mocked.

    Mocks ``get_client()`` (the factory called by ``_ensure_client``) to return a
    MagicMock SDK client. After the first ``await client.ask(...)`` call, the mock
    is cached in the per-loop store and ``self.client`` returns it automatically.

    Also registers a fake tool so that ``use_tools=True`` is not silently ignored
    (ask() disables tools when none are registered).
    """
    if combined_call_prefixes is not None:
        client = GoogleGenAIClient(api_key="fake", combined_call_prefixes=combined_call_prefixes)
    else:
        client = GoogleGenAIClient(api_key="fake")

    _register_fake_tool(client)

    chat = MagicMock()
    chat.send_message = AsyncMock()
    chat.send_message_stream = AsyncMock()
    create_mock = MagicMock(return_value=chat)

    reformat_mock = AsyncMock()
    models_mock = MagicMock()
    models_mock.generate_content = reformat_mock

    aio = MagicMock()
    aio.chats = MagicMock(create=create_mock)
    aio.models = models_mock
    mock_sdk_client = MagicMock(aio=aio)

    # get_client() is called by _ensure_client() on a cache miss.
    client.get_client = AsyncMock(return_value=mock_sdk_client)

    return client, {
        "chats.create": create_mock,
        "chat": chat,
        "chat.send_message": chat.send_message,
        "chat.send_message_stream": chat.send_message_stream,
        "models.generate_content": reformat_mock,
    }


class TestVideoUnderstandingStructuredOutput:
    """video_understanding() structured-output support."""

    @pytest.mark.asyncio
    async def test_stateless_applies_schema_and_returns_parsed_output(self):
        weather_schema = _make_weather_schema()
        client, m = _build_mocked_client()
        json_text = '{"location":"Madrid","temperature":25.5,"condition":"Sunny"}'
        m["models.generate_content"].return_value = _make_fake_response(json_text)

        with patch("parrot.clients.google.analysis.AIMessageFactory") as mock_factory:
            mock_factory.from_gemini.return_value = AIMessage(
                input="extract weather",
                output=json_text,
                response=json_text,
                model="gemini-3.5-flash",
                provider="google_genai",
                usage=CompletionUsage(),
            )

            await client.video_understanding(
                prompt="extract weather",
                model="gemini-3.5-flash",
                video="https://www.youtube.com/watch?v=abc123",
                structured_output=weather_schema,
            )

        config = m["models.generate_content"].call_args.kwargs["config"]
        assert getattr(config, "response_mime_type", None) == "application/json"
        assert getattr(config, "response_schema", None) is not None

        structured = mock_factory.from_gemini.call_args.kwargs["structured_output"]
        assert isinstance(structured, weather_schema)
        assert structured.location == "Madrid"
        assert structured.temperature == 25.5
        assert structured.condition == "Sunny"

    @pytest.mark.asyncio
    async def test_stateful_applies_schema_to_chat_config(self):
        weather_schema = _make_weather_schema()
        client, m = _build_mocked_client()
        json_text = '{"location":"Madrid","temperature":25.5,"condition":"Sunny"}'
        m["chat.send_message"].return_value = _make_fake_response(json_text)
        client._prepare_conversation_context = AsyncMock(
            return_value=(
                [
                    {
                        "role": "user",
                        "content": [{"type": "text", "text": "extract weather"}],
                    }
                ],
                MagicMock(),
                "Use JSON output.",
            )
        )
        client._update_conversation_memory = AsyncMock()

        with patch("parrot.clients.google.analysis.AIMessageFactory") as mock_factory:
            mock_factory.from_gemini.return_value = AIMessage(
                input="extract weather",
                output=json_text,
                response=json_text,
                model="gemini-3.5-flash",
                provider="google_genai",
                usage=CompletionUsage(),
            )

            await client.video_understanding(
                prompt="extract weather",
                model="gemini-3.5-flash",
                video="https://www.youtube.com/watch?v=abc123",
                stateless=False,
                structured_output=weather_schema,
            )

        config = m["chats.create"].call_args.kwargs["config"]
        assert getattr(config, "response_mime_type", None) == "application/json"
        assert getattr(config, "response_schema", None) is not None

        structured = mock_factory.from_gemini.call_args.kwargs["structured_output"]
        assert isinstance(structured, weather_schema)
        assert structured.location == "Madrid"


class TestImageUnderstandingStructuredOutput:
    """image_understanding() structured-output support."""

    @pytest.mark.asyncio
    async def test_stateless_applies_schema_and_returns_parsed_output(self):
        weather_schema = _make_weather_schema()
        client, m = _build_mocked_client()
        json_text = '{"location":"Madrid","temperature":25.5,"condition":"Sunny"}'
        m["models.generate_content"].return_value = _make_fake_response(json_text)
        image = Image.new("RGB", (10, 10), color="white")

        with patch("parrot.clients.google.analysis.AIMessageFactory") as mock_factory:
            mock_factory.from_gemini.return_value = AIMessage(
                input="extract weather",
                output=json_text,
                response=json_text,
                model="gemini-3.5-flash",
                provider="google_genai",
                usage=CompletionUsage(),
            )

            await client.image_understanding(
                prompt="extract weather",
                model="gemini-3.5-flash",
                images=image,
                structured_output=weather_schema,
            )

        config = m["models.generate_content"].call_args.kwargs["config"]
        assert getattr(config, "response_mime_type", None) == "application/json"
        assert getattr(config, "response_schema", None) is not None

        structured = mock_factory.from_gemini.call_args.kwargs["structured_output"]
        assert isinstance(structured, weather_schema)
        assert structured.location == "Madrid"
        assert structured.temperature == 25.5
        assert structured.condition == "Sunny"

    @pytest.mark.asyncio
    async def test_stateful_applies_schema_to_chat_config(self):
        weather_schema = _make_weather_schema()
        client, m = _build_mocked_client()
        json_text = '{"location":"Madrid","temperature":25.5,"condition":"Sunny"}'
        m["chat.send_message"].return_value = _make_fake_response(json_text)
        image = Image.new("RGB", (10, 10), color="white")

        with patch("parrot.clients.google.analysis.AIMessageFactory") as mock_factory:
            mock_factory.from_gemini.return_value = AIMessage(
                input="extract weather",
                output=json_text,
                response=json_text,
                model="gemini-3.5-flash",
                provider="google_genai",
                usage=CompletionUsage(),
            )

            await client.image_understanding(
                prompt="extract weather",
                model="gemini-3.5-flash",
                images=image,
                stateless=False,
                structured_output=weather_schema,
            )

        config = m["chats.create"].call_args.kwargs["config"]
        assert getattr(config, "response_mime_type", None) == "application/json"
        assert getattr(config, "response_schema", None) is not None

        structured = mock_factory.from_gemini.call_args.kwargs["structured_output"]
        assert isinstance(structured, weather_schema)
        assert structured.location == "Madrid"


class TestAskCombinedModeGate:
    """ask() combined-mode gate: whitelisted model skips the reformat call."""

    @pytest.mark.asyncio
    async def test_combined_mode_single_call(self):
        """Whitelisted model + tools + schema -> one send_message, zero reformat calls."""
        weather_schema = _make_weather_schema()
        client, m = _build_mocked_client()

        json_text = '{"location":"Madrid","temperature":25.5,"condition":"Sunny"}'
        m["chat.send_message"].return_value = _make_fake_response(json_text)

        with patch("parrot.clients.google.client.AIMessageFactory") as mock_factory:
            mock_factory.from_gemini.return_value = AIMessage(
                input="weather?",
                output=json_text,
                response=json_text,
                model="gemini-3.5-flash",
                provider="google_genai",
                usage=CompletionUsage(),
            )
            await client.ask(
                prompt="weather?",
                model="gemini-3.5-flash",
                structured_output=weather_schema,
                use_tools=True,
            )

        assert m["chat.send_message"].call_count == 1
        assert m["models.generate_content"].call_count == 0

        # Schema was applied to the chat config (combined mode).
        config = (
            m["chat.send_message"].call_args.kwargs.get("config") or m["chat.send_message"].call_args.args[1]
            if m["chat.send_message"].call_args.args
            else None
        )
        if config is None:
            # config may be positional arg in some versions; fall back
            all_kwargs = m["chat.send_message"].call_args
            config = all_kwargs.kwargs.get("config") or (all_kwargs.args[1] if len(all_kwargs.args) > 1 else None)
        assert getattr(config, "response_mime_type", None) == "application/json"
        assert getattr(config, "response_schema", None) is not None

    @pytest.mark.asyncio
    async def test_two_phase_preserved_for_unwhitelisted(self):
        """Non-whitelisted model + tools + schema -> send_message + reformat call."""
        weather_schema = _make_weather_schema()
        client, m = _build_mocked_client()

        m["chat.send_message"].return_value = _make_fake_response("It is sunny in Madrid at 25.5 degrees Celsius.")
        reformat_json = '{"location":"Madrid","temperature":25.5,"condition":"Sunny"}'
        m["models.generate_content"].return_value = _make_fake_response(reformat_json)

        with patch("parrot.clients.google.client.AIMessageFactory") as mock_factory:
            mock_factory.from_gemini.return_value = AIMessage(
                input="weather?",
                output=reformat_json,
                response=reformat_json,
                model="gemini-2.5-pro",
                provider="google_genai",
                usage=CompletionUsage(),
            )
            await client.ask(
                prompt="weather?",
                model="gemini-2.5-pro",
                structured_output=weather_schema,
                use_tools=True,
            )

        # Both a chat call AND a reformat call.
        assert m["chat.send_message"].call_count == 1
        assert m["models.generate_content"].call_count >= 1

        # Schema NOT on the initial chat config (two-phase: defer schema to reformat).
        chat_config = m["chat.send_message"].call_args.kwargs.get("config")
        assert getattr(chat_config, "response_schema", None) is None

        # Schema IS on the reformat config.
        reformat_config = m["models.generate_content"].call_args.kwargs.get("config")
        assert getattr(reformat_config, "response_mime_type", None) == "application/json"

    @pytest.mark.asyncio
    async def test_combined_mode_no_structured_output(self):
        """Whitelisted + tools, no schema -> one chat call, no reformat."""
        client, m = _build_mocked_client()
        m["chat.send_message"].return_value = _make_fake_response("It is sunny.")

        with patch("parrot.clients.google.client.AIMessageFactory") as mock_factory:
            mock_factory.from_gemini.return_value = AIMessage(
                input="x",
                output="It is sunny.",
                response="It is sunny.",
                model="gemini-3.5-flash",
                provider="google_genai",
                usage=CompletionUsage(),
            )
            await client.ask(
                prompt="x",
                model="gemini-3.5-flash",
                use_tools=True,
            )

        assert m["chat.send_message"].call_count == 1
        assert m["models.generate_content"].call_count == 0

    @pytest.mark.asyncio
    async def test_combined_mode_no_tools(self):
        """Whitelisted + schema, no tools -> schema on chat config, no reformat."""
        weather_schema = _make_weather_schema()
        client, m = _build_mocked_client()
        json_text = '{"location":"Madrid","temperature":25.5,"condition":"Sunny"}'
        m["chat.send_message"].return_value = _make_fake_response(json_text)

        with patch("parrot.clients.google.client.AIMessageFactory") as mock_factory:
            mock_factory.from_gemini.return_value = AIMessage(
                input="x",
                output=json_text,
                response=json_text,
                model="gemini-3.5-flash",
                provider="google_genai",
                usage=CompletionUsage(),
            )
            await client.ask(
                prompt="x",
                model="gemini-3.5-flash",
                structured_output=weather_schema,
                use_tools=False,
            )

        assert m["chat.send_message"].call_count == 1
        assert m["models.generate_content"].call_count == 0

    @pytest.mark.asyncio
    async def test_combined_call_prefixes_kwarg_override_empty(self):
        """Empty prefixes tuple forces two-phase even for normally-whitelisted models."""
        weather_schema = _make_weather_schema()
        client, m = _build_mocked_client(combined_call_prefixes=())

        m["chat.send_message"].return_value = _make_fake_response("It is sunny in Madrid at 25.5 degrees.")
        reformat_json = '{"location":"Madrid","temperature":25.5,"condition":"Sunny"}'
        m["models.generate_content"].return_value = _make_fake_response(reformat_json)

        with patch("parrot.clients.google.client.AIMessageFactory") as mock_factory:
            mock_factory.from_gemini.return_value = AIMessage(
                input="x",
                output=reformat_json,
                response=reformat_json,
                model="gemini-3.5-flash",
                provider="google_genai",
                usage=CompletionUsage(),
            )
            await client.ask(
                prompt="x",
                model="gemini-3.5-flash",
                structured_output=weather_schema,
                use_tools=True,
            )

        # Should have fallen back to two-phase because combined_call_prefixes=().
        assert m["models.generate_content"].call_count >= 1

    @pytest.mark.asyncio
    async def test_combined_call_prefixes_kwarg_override_custom(self):
        """Custom whitelist: only the listed prefix triggers combined mode."""
        weather_schema = _make_weather_schema()

        # Custom prefix that matches gemini-3.5-flash but NOT gemini-2.5-pro.
        client, m = _build_mocked_client(combined_call_prefixes=("gemini-3.5-flash",))

        json_text = '{"location":"Madrid","temperature":25.5,"condition":"Sunny"}'
        m["chat.send_message"].return_value = _make_fake_response(json_text)

        with patch("parrot.clients.google.client.AIMessageFactory") as mock_factory:
            mock_factory.from_gemini.return_value = AIMessage(
                input="x",
                output=json_text,
                response=json_text,
                model="gemini-3.5-flash",
                provider="google_genai",
                usage=CompletionUsage(),
            )
            await client.ask(
                prompt="x",
                model="gemini-3.5-flash",
                structured_output=weather_schema,
                use_tools=True,
            )

        # gemini-3.5-flash matches custom prefix -> combined mode -> zero reformat calls.
        assert m["models.generate_content"].call_count == 0

    @pytest.mark.asyncio
    async def test_combined_mode_malformed_json_falls_back_to_reformat(self):
        """Combined mode: _parse_structured_output returns str -> recovery reformat call."""
        weather_schema = _make_weather_schema()
        client, m = _build_mocked_client()

        # The model returns text that fails JSON parsing.
        m["chat.send_message"].return_value = _make_fake_response("Not valid JSON at all")
        reformat_json = '{"location":"Madrid","temperature":25.5,"condition":"Sunny"}'
        m["models.generate_content"].return_value = _make_fake_response(reformat_json)

        with patch("parrot.clients.google.client.AIMessageFactory") as mock_factory:
            mock_factory.from_gemini.return_value = AIMessage(
                input="x",
                output=reformat_json,
                response=reformat_json,
                model="gemini-3.5-flash",
                provider="google_genai",
                usage=CompletionUsage(),
            )
            await client.ask(
                prompt="x",
                model="gemini-3.5-flash",
                structured_output=weather_schema,
                use_tools=True,
            )

        # Chat call AND recovery reformat call.
        assert m["chat.send_message"].call_count == 1
        assert m["models.generate_content"].call_count >= 1

    @pytest.mark.asyncio
    async def test_flash_lite_debug_log_emitted_once(self, caplog):
        """gemini-3.1-flash-lite-preview + combined mode -> debug log with AFC note."""
        weather_schema = _make_weather_schema()
        client, m = _build_mocked_client()

        json_text = '{"location":"Madrid","temperature":25.5,"condition":"Sunny"}'
        m["chat.send_message"].return_value = _make_fake_response(json_text)

        with caplog.at_level(logging.DEBUG):
            with patch("parrot.clients.google.client.AIMessageFactory") as mock_factory:
                mock_factory.from_gemini.return_value = AIMessage(
                    input="x",
                    output=json_text,
                    response=json_text,
                    model="gemini-3.1-flash-lite-preview",
                    provider="google_genai",
                    usage=CompletionUsage(),
                )
                await client.ask(
                    prompt="x",
                    model="gemini-3.1-flash-lite-preview",
                    structured_output=weather_schema,
                    use_tools=True,
                )

        matches = [r for r in caplog.records if "AFC instability" in r.getMessage()]
        assert len(matches) == 1

    @pytest.mark.asyncio
    async def test_lifecycle_events_fire_in_combined_mode(self):
        """AfterClientCallEvent fires exactly once in combined mode (parity with non-combined)."""
        weather_schema = _make_weather_schema()
        client, m = _build_mocked_client()

        json_text = '{"location":"Madrid","temperature":25.5,"condition":"Sunny"}'
        m["chat.send_message"].return_value = _make_fake_response(json_text)

        events_captured = []

        async def _capture(event):
            events_captured.append(event)

        client.events.subscribe(AfterClientCallEvent, _capture)

        with patch("parrot.clients.google.client.AIMessageFactory") as mock_factory:
            mock_factory.from_gemini.return_value = AIMessage(
                input="x",
                output=json_text,
                response=json_text,
                model="gemini-3.5-flash",
                provider="google_genai",
                usage=CompletionUsage(),
            )
            await client.ask(
                prompt="x",
                model="gemini-3.5-flash",
                structured_output=weather_schema,
                use_tools=True,
            )

        assert len(events_captured) == 1
        assert isinstance(events_captured[0], AfterClientCallEvent)


class TestAskStreamCombinedModeGate:
    """ask_stream() combined-mode gate: whitelisted model skips the post-stream reformat call."""

    def _make_stream_chunk(self, text: str):
        """Build a minimal async-stream chunk mock."""
        chunk = MagicMock()
        chunk.text = text
        part = _FakeGeminiPart(text=text)
        chunk.candidates = [_FakeGeminiCandidate([part])]
        return chunk

    @pytest.mark.asyncio
    async def test_ask_stream_combined_mode_no_reformat_call(self):
        """Whitelisted model + tools + schema -> schema on stream config, zero reformat calls."""
        weather_schema = _make_weather_schema()
        client, m = _build_mocked_client()

        # Pre-populate the per-loop client cache (ask_stream accesses self.client
        # before the inner retry loop calls _ensure_client).
        await client._ensure_client(model="gemini-3.5-flash")

        json_chunk = '{"location":"Madrid","temperature":25.5,"condition":"Sunny"}'

        async def _stream_iter():
            yield self._make_stream_chunk(json_chunk)

        mock_stream = MagicMock()
        mock_stream.__aiter__ = MagicMock(side_effect=_stream_iter)
        m["chat"].send_message_stream = AsyncMock(return_value=mock_stream)

        with patch("parrot.clients.google.client.AIMessageFactory") as mock_factory:
            mock_factory.from_gemini.return_value = AIMessage(
                input="x",
                output=json_chunk,
                response=json_chunk,
                model="gemini-3.5-flash",
                provider="google_genai",
                usage=CompletionUsage(),
            )
            chunks = []
            async for chunk in client.ask_stream(
                prompt="x",
                model="gemini-3.5-flash",
                structured_output=weather_schema,
                use_tools=True,
            ):
                chunks.append(chunk)

        # No reformat call in combined mode.
        assert m["models.generate_content"].call_count == 0

    @pytest.mark.asyncio
    async def test_ask_stream_two_phase_preserved_for_unwhitelisted(self):
        """Non-whitelisted model + tools + schema -> reformat call after streaming."""
        weather_schema = _make_weather_schema()
        client, m = _build_mocked_client()

        # Pre-populate the per-loop client cache.
        await client._ensure_client(model="gemini-2.5-pro")

        prose_chunk = "It is sunny in Madrid at 25.5 degrees."
        reformat_json = '{"location":"Madrid","temperature":25.5,"condition":"Sunny"}'

        async def _stream_iter():
            yield self._make_stream_chunk(prose_chunk)

        mock_stream = MagicMock()
        mock_stream.__aiter__ = MagicMock(side_effect=_stream_iter)
        m["chat"].send_message_stream = AsyncMock(return_value=mock_stream)
        m["models.generate_content"].return_value = _make_fake_response(reformat_json)

        with patch("parrot.clients.google.client.AIMessageFactory") as mock_factory:
            mock_factory.from_gemini.return_value = AIMessage(
                input="x",
                output=reformat_json,
                response=reformat_json,
                model="gemini-2.5-pro",
                provider="google_genai",
                usage=CompletionUsage(),
            )
            chunks = []
            async for chunk in client.ask_stream(
                prompt="x",
                model="gemini-2.5-pro",
                structured_output=weather_schema,
                use_tools=True,
            ):
                chunks.append(chunk)

        # Two-phase: reformat call should fire.
        assert m["models.generate_content"].call_count >= 1


class TestCleanGoogleSchemaArrayItems:
    """Regression for the Gemini 400 'array.items: missing field' error.

    Pydantic v2 emits ``prefixItems`` (not ``items``) for fixed-length tuples
    such as ``Tuple[float, float]`` (e.g. SpatialFilterSpec.point). Gemini does
    not understand ``prefixItems`` and rejects any array schema lacking
    ``items``. ``clean_google_schema`` must backfill ``items`` from
    ``prefixItems`` so the function declaration is accepted.
    """

    def _clean(self, schema):
        # Skip __init__ — clean_google_schema only needs self for recursion
        # and _resolve_schema_refs (also a method on the class).
        client = GoogleGenAIClient.__new__(GoogleGenAIClient)
        return client.clean_google_schema(schema)

    def test_tuple_prefixitems_backfills_items(self):
        """A Tuple-style array (prefixItems, no items) gets items backfilled."""
        schema = {
            "type": "array",
            "minItems": 2,
            "maxItems": 2,
            "prefixItems": [{"type": "number"}, {"type": "number"}],
        }
        cleaned = self._clean(schema)
        assert cleaned["type"] == "array"
        assert cleaned["items"] == {"type": "number"}
        assert "prefixItems" not in cleaned

    def test_array_without_any_item_schema_gets_permissive_items(self):
        """An array with neither items nor prefixItems still gets an items schema."""
        cleaned = self._clean({"type": "array"})
        assert cleaned["type"] == "array"
        assert cleaned["items"] == {"type": "string"}

    def test_regular_list_items_preserved(self):
        """A normal List[str] array keeps its existing items untouched."""
        cleaned = self._clean({"type": "array", "items": {"type": "string"}})
        assert cleaned["items"] == {"type": "string"}

    def test_nested_tuple_property_in_object(self):
        """Tuple inside an object property (the SpatialFilterSpec.point shape)."""
        schema = {
            "type": "object",
            "properties": {
                "point": {
                    "type": "array",
                    "prefixItems": [{"type": "number"}, {"type": "number"}],
                    "minItems": 2,
                    "maxItems": 2,
                },
            },
            "required": ["point"],
        }
        cleaned = self._clean(schema)
        pt = cleaned["properties"]["point"]
        assert pt["type"] == "array"
        assert pt["items"] == {"type": "number"}
        assert "prefixItems" not in pt


@pytest.mark.asyncio
async def test_generate_image_config_developer_api():
    """In Developer API mode (vertexai=False), output_mime_type and person_generation must be omitted from ImageConfig."""
    with (
        patch("parrot.clients.google.client.genai.Client") as mock_genai_cls,
        patch("parrot.clients.google.generation.types.ImageConfig") as mock_image_config_cls,
        patch("parrot.clients.google.generation.types.GenerateContentConfig") as mock_generate_content_config_cls,
    ):

        mock_client_instance = MagicMock()
        mock_genai_cls.return_value = mock_client_instance

        # Setup mock response
        mock_response = MagicMock()
        mock_response.parts = []

        # In generate_image (stateless=True), we call aio.models.generate_content
        mock_client_instance.aio.models.generate_content = AsyncMock(return_value=mock_response)

        client = GoogleGenAIClient(api_key="fake_key", vertexai=False)
        client.get_client = AsyncMock(return_value=mock_client_instance)

        await client.generate_image(
            prompt="A cute kitten", output_mime_type="image/jpeg", person_generation="dont_allow", stateless=True
        )

        # Verify that ImageConfig was called WITHOUT output_mime_type and person_generation
        mock_image_config_cls.assert_called_once()
        called_kwargs = mock_image_config_cls.call_args.kwargs
        assert "output_mime_type" not in called_kwargs
        assert "person_generation" not in called_kwargs


@pytest.mark.asyncio
async def test_generate_image_config_vertexai():
    """In Vertex AI mode (vertexai=True), output_mime_type and person_generation must be included in ImageConfig."""
    with (
        patch("parrot.clients.google.client.genai.Client") as mock_genai_cls,
        patch("parrot.clients.google.generation.types.ImageConfig") as mock_image_config_cls,
        patch("parrot.clients.google.generation.types.GenerateContentConfig") as mock_generate_content_config_cls,
    ):

        mock_client_instance = MagicMock()
        mock_genai_cls.return_value = mock_client_instance

        # Setup mock response
        mock_response = MagicMock()
        mock_response.parts = []

        # In generate_image (stateless=True), we call aio.models.generate_content
        mock_client_instance.aio.models.generate_content = AsyncMock(return_value=mock_response)

        client = GoogleGenAIClient(
            api_key="fake_key", vertexai=True, vertex_project="fake_project", vertex_location="us-central1"
        )
        client.get_client = AsyncMock(return_value=mock_client_instance)

        await client.generate_image(
            prompt="A cute kitten", output_mime_type="image/jpeg", person_generation="dont_allow", stateless=True
        )

        # Verify that ImageConfig was called WITH output_mime_type and person_generation
        mock_image_config_cls.assert_called_once()
        called_kwargs = mock_image_config_cls.call_args.kwargs
        assert called_kwargs["output_mime_type"] == "image/jpeg"
        assert called_kwargs["person_generation"] == "dont_allow"


@pytest.mark.asyncio
async def test_generate_images_config_developer_api():
    """In Developer API mode (vertexai=False), add_watermark, negative_prompt, and seed must be omitted from GenerateImagesConfig."""
    with (
        patch("parrot.clients.google.client.genai.Client") as mock_genai_cls,
        patch("parrot.clients.google.generation.types.GenerateImagesConfig") as mock_generate_images_config_cls,
        patch("parrot.clients.google.generation.AIMessageFactory") as mock_aimessage_factory_cls,
    ):

        mock_aimessage_factory_cls.from_imagen.return_value = AIMessage(
            input="A majestic eagle",
            output=[],
            response="Image generated successfully.",
            model="imagen-4.0-generate-001",
            provider="google",
            usage=CompletionUsage(),
        )

        mock_client_instance = MagicMock()
        mock_genai_cls.return_value = mock_client_instance

        # Setup mock response
        mock_response = MagicMock()
        mock_response.generated_images = []

        # In generate_images, we call aio.models.generate_images
        mock_client_instance.aio.models.generate_images = AsyncMock(return_value=mock_response)

        client = GoogleGenAIClient(api_key="fake_key", vertexai=False)
        client.get_client = AsyncMock(return_value=mock_client_instance)

        await client.generate_images(
            prompt="A majestic eagle",
            add_watermark=True,
            negative_prompt="blurry",
            seed=42,
            safety_filter_level="BLOCK_ONLY_HIGH",
        )

        # Verify GenerateImagesConfig was called WITHOUT add_watermark, negative_prompt, and seed
        mock_generate_images_config_cls.assert_called_once()
        called_kwargs = mock_generate_images_config_cls.call_args.kwargs
        assert "add_watermark" not in called_kwargs
        assert "negative_prompt" not in called_kwargs
        assert "seed" not in called_kwargs
        # For Developer API, safety_filter_level must be forced to BLOCK_LOW_AND_ABOVE
        assert called_kwargs["safety_filter_level"] == "BLOCK_LOW_AND_ABOVE"


@pytest.mark.asyncio
async def test_generate_images_config_vertexai():
    """In Vertex AI mode (vertexai=True), add_watermark, negative_prompt, and seed must be included in GenerateImagesConfig."""
    with (
        patch("parrot.clients.google.client.genai.Client") as mock_genai_cls,
        patch("parrot.clients.google.generation.types.GenerateImagesConfig") as mock_generate_images_config_cls,
        patch("parrot.clients.google.generation.AIMessageFactory") as mock_aimessage_factory_cls,
    ):

        mock_aimessage_factory_cls.from_imagen.return_value = AIMessage(
            input="A majestic eagle",
            output=[],
            response="Image generated successfully.",
            model="imagen-4.0-generate-001",
            provider="google",
            usage=CompletionUsage(),
        )

        mock_client_instance = MagicMock()
        mock_genai_cls.return_value = mock_client_instance

        # Setup mock response
        mock_response = MagicMock()
        mock_response.generated_images = []

        # In generate_images, we call aio.models.generate_images
        mock_client_instance.aio.models.generate_images = AsyncMock(return_value=mock_response)

        client = GoogleGenAIClient(
            api_key="fake_key", vertexai=True, vertex_project="fake_project", vertex_location="us-central1"
        )
        client.get_client = AsyncMock(return_value=mock_client_instance)

        await client.generate_images(
            prompt="A majestic eagle",
            add_watermark=True,
            negative_prompt="blurry",
            seed=42,
            safety_filter_level="BLOCK_ONLY_HIGH",
        )

        # Verify GenerateImagesConfig was called WITH add_watermark, negative_prompt, and seed
        mock_generate_images_config_cls.assert_called_once()
        called_kwargs = mock_generate_images_config_cls.call_args.kwargs
        assert called_kwargs["add_watermark"] is True
        assert called_kwargs["negative_prompt"] == "blurry"
        assert called_kwargs["seed"] == 42
        # For Vertex AI, safety_filter_level remains what was specified
        assert called_kwargs["safety_filter_level"] == "BLOCK_ONLY_HIGH"


# =============================================================================
# FEAT-252 / TASK-1613 — _resolve_final_response chokepoint tests
# =============================================================================

def _make_tool_call(result=None, name="some_tool"):
    """Helper: construct a minimal ToolCall for testing."""
    from parrot.models.basic import ToolCall
    return ToolCall(id="tc-1", name=name, arguments={}, result=result)


def _make_client():
    """Return a GoogleGenAIClient with faked credentials (no real API call)."""
    from unittest.mock import MagicMock
    client = GoogleGenAIClient.__new__(GoogleGenAIClient)
    client.model = "gemini-2.5-flash"
    client.temperature = 0.0
    client.max_tokens = None
    client.logger = MagicMock()
    client.logger.notice = MagicMock()
    client.logger.info = MagicMock()
    client.logger.warning = MagicMock()
    from parrot.security.redaction import OutputScrubber, ScrubPolicy
    client._scrubber = OutputScrubber(ScrubPolicy())
    client._echo_threshold = 0.85
    return client


class TestResolveFinalResponse:
    """Unit tests for GoogleGenAIClient._resolve_final_response (FEAT-252)."""

    def test_method_exists(self):
        """_resolve_final_response must exist on the client."""
        from parrot.clients.google.client import GoogleGenAIClient
        assert hasattr(GoogleGenAIClient, "_resolve_final_response")

    def test_synthesis_passes_through(self):
        """A genuine synthesis answer is returned (after scrub)."""
        client = _make_client()
        out = client._resolve_final_response("The answer is 42.", [], None)
        assert "42" in out

    def test_suppresses_verbatim_tool_echo(self):
        """Near-verbatim echo of a tool result is suppressed."""
        client = _make_client()
        tool_result = "KeysView(environ({'PWD': '/home/user', 'SECRET': 'hunter2'}))"
        tc = _make_tool_call(result=tool_result)
        out = client._resolve_final_response(tool_result, [tc], None)
        assert "hunter2" not in out or "no answer" in out.lower()

    def test_empty_after_tools_returns_sentinel(self):
        """Empty candidate after tool calls → typed 'no answer' sentinel."""
        client = _make_client()
        tc = _make_tool_call(result="42")
        out = client._resolve_final_response("", [tc], None)
        assert client._is_no_answer(out)

    def test_empty_no_tools_is_safe(self):
        """Empty candidate with no tool calls → returns empty or sentinel, never raw stdout."""
        client = _make_client()
        out = client._resolve_final_response("", [], None)
        # Either empty-string or the typed sentinel is acceptable; must NOT be raw stdout
        assert out == "" or client._is_no_answer(out)

    def test_secret_in_synthesis_is_scrubbed(self):
        """A synthesis answer containing a secret is scrubbed before delivery."""
        client = _make_client()
        out = client._resolve_final_response("The password is PASSWORD=hunter2", [], None)
        assert "hunter2" not in out
        assert "REDACTED" in out

    def test_is_no_answer_helper(self):
        """_is_no_answer correctly identifies the sentinel."""
        client = _make_client()
        assert client._is_no_answer(client._no_answer_sentinel())
        assert not client._is_no_answer("The answer is 42.")

    def test_code_exec_output_framed(self):
        """Code-exec stdout is framed rather than shipped raw."""
        client = _make_client()
        out = client._resolve_final_response("42\n", [], "42\n")
        assert out  # not empty

    def test_default_api_call_gated(self):
        """_get_function_calls_from_response drops 'default_api' calls."""
        from unittest.mock import MagicMock
        client = _make_client()
        # Simulate a response with a default_api function call
        mock_fc = MagicMock()
        mock_fc.name = "default_api"
        mock_part = MagicMock()
        mock_part.function_call = mock_fc
        mock_part.executable_code = None
        mock_part.code_execution_result = None
        mock_candidate = MagicMock()
        mock_candidate.content.parts = [mock_part]
        mock_response = MagicMock()
        mock_response.candidates = [mock_candidate]
        mock_response.text = None
        calls = client._get_function_calls_from_response(mock_response)
        assert all(c.name != "default_api" for c in calls)

    def test_no_scattered_redact_calls(self):
        """google/client.py must have zero scattered redact_text/redact_secrets calls."""
        import inspect
        import parrot.clients.google.client as m
        src = inspect.getsource(m)
        count = src.count("redact_text(") + src.count("redact_secrets(")
        assert count == 0, (
            f"Found {count} scattered redact_text/redact_secrets call(s) in client.py — "
            "all scrubbing must go through _resolve_final_response / OutputScrubber."
        )
