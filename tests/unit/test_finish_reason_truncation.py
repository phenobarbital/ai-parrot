"""Unit tests for the shared finish_reason truncation guard.

A provider response that stopped because of the output-token limit
(``MAX_TOKENS`` / ``max_tokens`` / ``length`` / ``REASON_MAX_LEN``) is known
to be truncated *before* any structured-output parse is attempted.  The shared
``AbstractClient`` helpers must turn that into a
:class:`~parrot.exceptions.TruncatedResponseError` (an ``InvokeError``)
instead of letting ``_parse_structured_output`` fall back to the raw string.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel

from parrot.exceptions import InvokeError, TruncatedResponseError
from parrot.models.outputs import OutputFormat, StructuredOutputConfig


class Payload(BaseModel):
    """Fixture model for structured output."""

    value: str


def _make_client():
    """Create a concrete AbstractClient subclass without network setup."""
    from parrot.clients.base import AbstractClient

    class _TestClient(AbstractClient):
        _default_model = "test-model"
        model = "test-model"

        async def ask(self, *args, **kwargs):
            raise NotImplementedError

        async def ask_stream(self, *args, **kwargs):
            raise NotImplementedError

        async def resume(self, *args, **kwargs):
            raise NotImplementedError

        async def invoke(self, *args, **kwargs):
            raise NotImplementedError

        async def get_client(self):
            return None

    client = _TestClient.__new__(_TestClient)
    client.model = "test-model"
    client._lightweight_model = None
    client._fallback_model = None
    client.logger = MagicMock()
    from datamodel.parsers.json import JSONContent

    client._json = JSONContent()
    return client


@pytest.fixture
def client():
    return _make_client()


@pytest.fixture
def config():
    return StructuredOutputConfig(output_type=Payload, format=OutputFormat.JSON)


# --------------------------------------------------------------------------- #
# _normalize_finish_reason
# --------------------------------------------------------------------------- #
class TestNormalizeFinishReason:
    def test_none_passthrough(self, client):
        assert client._normalize_finish_reason(None) is None

    def test_empty_string_is_none(self, client):
        assert client._normalize_finish_reason("   ") is None

    def test_plain_string_lowercased(self, client):
        assert client._normalize_finish_reason("STOP") == "stop"
        assert client._normalize_finish_reason("length") == "length"

    def test_enum_like_uses_name(self, client):
        enum_like = SimpleNamespace(name="MAX_TOKENS")
        assert client._normalize_finish_reason(enum_like) == "max_tokens"

    def test_enum_repr_string_strips_prefix(self, client):
        # str(google.genai.types.FinishReason.MAX_TOKENS) == "FinishReason.MAX_TOKENS"
        assert client._normalize_finish_reason("FinishReason.MAX_TOKENS") == "max_tokens"

    def test_mock_object_does_not_match(self, client):
        # MagicMock().name is itself a MagicMock — must not be treated as truncation.
        assert client._normalize_finish_reason(MagicMock()) not in client.TRUNCATED_FINISH_REASONS


# --------------------------------------------------------------------------- #
# _extract_finish_reason
# --------------------------------------------------------------------------- #
class TestExtractFinishReason:
    def test_openai_like_choices(self, client):
        resp = SimpleNamespace(choices=[SimpleNamespace(finish_reason="length")])
        assert client._extract_finish_reason(resp) == "length"

    def test_google_like_candidates(self, client):
        resp = SimpleNamespace(candidates=[SimpleNamespace(finish_reason="MAX_TOKENS")])
        assert client._extract_finish_reason(resp) == "MAX_TOKENS"

    def test_anthropic_like_stop_reason(self, client):
        resp = SimpleNamespace(stop_reason="max_tokens")
        assert client._extract_finish_reason(resp) == "max_tokens"

    def test_xai_like_finish_reason_attr(self, client):
        resp = SimpleNamespace(finish_reason="REASON_MAX_LEN")
        assert client._extract_finish_reason(resp) == "REASON_MAX_LEN"

    def test_bedrock_dict(self, client):
        assert client._extract_finish_reason({"stopReason": "max_tokens"}) == "max_tokens"

    def test_anthropic_dump_dict(self, client):
        assert client._extract_finish_reason({"stop_reason": "end_turn"}) == "end_turn"

    def test_unknown_shape_is_none(self, client):
        assert client._extract_finish_reason(object()) is None
        assert client._extract_finish_reason(None) is None
        assert client._extract_finish_reason(SimpleNamespace(choices=[])) is None


# --------------------------------------------------------------------------- #
# _raise_if_truncated
# --------------------------------------------------------------------------- #
class TestRaiseIfTruncated:
    @pytest.mark.parametrize(
        "reason",
        [
            "max_tokens",                          # Anthropic / Bedrock
            "MAX_TOKENS",                          # Google (str)
            "FinishReason.MAX_TOKENS",             # Google (enum repr)
            SimpleNamespace(name="MAX_TOKENS"),    # Google (enum object)
            "length",                              # OpenAI-compatible
            "REASON_MAX_LEN",                      # xAI Grok
        ],
    )
    def test_raises_for_truncation_vocabulary(self, client, reason):
        with pytest.raises(TruncatedResponseError) as exc_info:
            client._raise_if_truncated(reason, model="m-1")
        err = exc_info.value
        assert isinstance(err, InvokeError)
        assert err.finish_reason
        assert "m-1" in str(err)

    @pytest.mark.parametrize(
        "reason", [None, "", "stop", "STOP", "end_turn", "tool_calls", "tool_use", "REASON_STOP", "SAFETY"]
    )
    def test_no_raise_for_non_truncation(self, client, reason):
        client._raise_if_truncated(reason)  # must not raise


# --------------------------------------------------------------------------- #
# _parse_structured_output — guard runs BEFORE any parse attempt
# --------------------------------------------------------------------------- #
class TestParseStructuredOutputGuard:
    async def test_truncated_raises_before_parsing(self, client, config):
        # Truncated JSON — would otherwise silently come back as the raw str.
        with pytest.raises(TruncatedResponseError):
            await client._parse_structured_output(
                '{"value": "abc', config, finish_reason="MAX_TOKENS"
            )

    async def test_truncated_raises_even_if_text_parses(self, client, config):
        # Known-truncated wins over "looks fine": the payload may be an accidental prefix.
        with pytest.raises(TruncatedResponseError):
            await client._parse_structured_output(
                '{"value": "abc"}', config, finish_reason="length"
            )

    async def test_no_finish_reason_keeps_legacy_fallback(self, client, config):
        # Backward compatible: callers that do not pass finish_reason keep the old behaviour.
        result = await client._parse_structured_output('{"value": "abc', config)
        assert isinstance(result, str)

    async def test_stop_parses_normally(self, client, config):
        result = await client._parse_structured_output(
            '{"value": "abc"}', config, finish_reason="stop"
        )
        assert isinstance(result, Payload)
        assert result.value == "abc"


# --------------------------------------------------------------------------- #
# _handle_invoke_error — never double-wrap
# --------------------------------------------------------------------------- #
class TestHandleInvokeErrorPassthrough:
    def test_invoke_error_returned_as_is(self, client):
        original = TruncatedResponseError("cut", finish_reason="max_tokens")
        assert client._handle_invoke_error(original) is original

    def test_other_exception_wrapped(self, client):
        exc = ValueError("boom")
        wrapped = client._handle_invoke_error(exc)
        assert isinstance(wrapped, InvokeError)
        assert wrapped.original is exc


# --------------------------------------------------------------------------- #
# Provider wiring — invoke() surfaces truncation as InvokeError
# --------------------------------------------------------------------------- #
class TestGoogleInvokeTruncation:
    def _client(self, finish_reason):
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

        part = SimpleNamespace(text='{"value": "ab')
        candidate = SimpleNamespace(
            content=SimpleNamespace(parts=[part]),
            finish_reason=SimpleNamespace(name=finish_reason),
        )
        response = SimpleNamespace(
            candidates=[candidate],
            text='{"value": "ab',
            usage_metadata=SimpleNamespace(
                prompt_token_count=1, candidates_token_count=1, total_token_count=2
            ),
        )
        sdk_client = MagicMock()
        sdk_client.aio = MagicMock()
        sdk_client.aio.models = MagicMock()
        sdk_client.aio.models.generate_content = AsyncMock(return_value=response)
        type(client).client = property(lambda self: sdk_client, lambda self, val: None)

        async def _ensure(model=None, **hints):
            return sdk_client

        client._ensure_client = _ensure
        return client

    async def test_max_tokens_raises_invoke_error(self):
        client = self._client("MAX_TOKENS")
        with pytest.raises(InvokeError) as exc_info:
            await client.invoke("extract", output_type=Payload)
        assert isinstance(exc_info.value, TruncatedResponseError)

    async def test_stop_with_bad_json_still_falls_back(self):
        # Not truncated — legacy behaviour (raw string fallback) is preserved.
        client = self._client("STOP")
        result = await client.invoke("extract", output_type=Payload)
        assert isinstance(result.output, str)


def _make_openai_client():
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
    client._clients_by_loop = {}
    client._locks_by_loop = {}
    return client


class TestOpenAIResponsesShimTruncation:
    """Responses API reports truncation top-level (status/incomplete_details)."""

    async def test_incomplete_max_output_tokens_maps_to_finish_reason(self):
        client = _make_openai_client()
        item = SimpleNamespace(content=[{"type": "output_text", "text": '{"value": "ab'}])
        resp = SimpleNamespace(
            output=[item],
            output_text=None,
            status="incomplete",
            incomplete_details=SimpleNamespace(reason="max_output_tokens"),
            usage=None,
        )
        client._prepare_responses_args = MagicMock(return_value={})
        client._call_responses_create = AsyncMock(return_value=resp)

        compat = await client._responses_completion(
            model="gpt-5", messages=[{"role": "user", "content": "x"}]
        )

        assert compat.choices[0].finish_reason == "max_output_tokens"
        assert client._extract_finish_reason(compat) == "max_output_tokens"
        with pytest.raises(TruncatedResponseError):
            client._raise_if_truncated(client._extract_finish_reason(compat))

    async def test_completed_status_leaves_finish_reason_none(self):
        client = _make_openai_client()
        item = SimpleNamespace(content=[{"type": "output_text", "text": "ok"}])
        resp = SimpleNamespace(
            output=[item], output_text=None, status="completed", incomplete_details=None, usage=None
        )
        client._prepare_responses_args = MagicMock(return_value={})
        client._call_responses_create = AsyncMock(return_value=resp)

        compat = await client._responses_completion(model="gpt-5", messages=[])
        assert compat.choices[0].finish_reason is None
        client._raise_if_truncated(client._extract_finish_reason(compat))  # no raise


class TestCustomParserGuard:
    """A custom_parser must not receive known-truncated text either."""

    async def test_openai_invoke_custom_parser_raises_on_length(self, bind_sdk_client):
        client = _make_openai_client()
        message = SimpleNamespace(content='{"value": "ab', tool_calls=None)
        choice = SimpleNamespace(message=message, finish_reason="length")
        usage = SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2)
        sdk = MagicMock()
        sdk.chat = MagicMock()
        sdk.chat.completions = MagicMock()
        sdk.chat.completions.create = AsyncMock(
            return_value=SimpleNamespace(choices=[choice], usage=usage)
        )
        bind_sdk_client(client, sdk)

        parser = MagicMock(return_value=Payload(value="should-not-run"))
        cfg = StructuredOutputConfig(
            output_type=Payload, format=OutputFormat.CUSTOM, custom_parser=parser
        )
        with pytest.raises(TruncatedResponseError):
            await client.invoke("extract", structured_output=cfg)
        parser.assert_not_called()


class TestOpenAIInvokeTruncation:
    async def test_length_raises_invoke_error(self, bind_sdk_client):
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
        client._clients_by_loop = {}
        client._locks_by_loop = {}

        message = SimpleNamespace(content='{"value": "ab', tool_calls=None)
        choice = SimpleNamespace(message=message, finish_reason="length")
        usage = SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2)
        sdk = MagicMock()
        sdk.chat = MagicMock()
        sdk.chat.completions = MagicMock()
        sdk.chat.completions.create = AsyncMock(
            return_value=SimpleNamespace(choices=[choice], usage=usage)
        )
        bind_sdk_client(client, sdk)

        with pytest.raises(InvokeError) as exc_info:
            await client.invoke("extract", output_type=Payload)
        assert isinstance(exc_info.value, TruncatedResponseError)
