"""Unit tests for MoonshotClient, MoonshotModel, and factory registration.

Tests cover initialization, env-var fallback for MOONSHOT_API_KEY,
parameter sanitization for K-series models, thinking-mode injection for
all three variants (K3 reasoning_effort, K2.6 thinking dict, K2.7-code
always-on), max_tokens -> max_completion_tokens translation,
prompt_cache_key injection, model enum values, and LLMFactory registration.

No live Moonshot API calls are made.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.clients.moonshot import MoonshotClient
from parrot.clients import moonshot as moonshot_mod
from parrot.clients.factory import LLMFactory, SUPPORTED_CLIENTS
from parrot.models import AIMessage, CompletionUsage
from parrot.models.moonshot import (
    MoonshotModel,
    K_SERIES_MODELS,
    ALWAYS_THINKING_MODELS,
    REASONING_EFFORT_MODELS,
    THINKING_DICT_MODELS,
    VISION_MODELS,
)


def _make_ai_message(raw_response=None, **overrides):
    """Build a minimal real AIMessage for _capture_reasoning_content tests."""
    fields = dict(
        input="hi",
        output="ok",
        response="ok",
        model="kimi-k3",
        provider="moonshot",
        usage=CompletionUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        raw_response=raw_response,
    )
    fields.update(overrides)
    return AIMessage(**fields)


def _make_moonshot_client(**attrs):
    """Create a minimal MoonshotClient instance for testing."""
    client = MoonshotClient.__new__(MoonshotClient)
    client.prompt_cache_key = None
    client.temperature = 0  # AbstractClient.__init__ default; ask_stream() reads this
    for key, value in attrs.items():
        setattr(client, key, value)
    return client


def _make_mock_response():
    """Build a MagicMock resembling an OpenAI ChatCompletion response."""
    mock_choice = MagicMock()
    mock_choice.message.content = "ok"
    mock_choice.message.tool_calls = None
    mock_choice.message.role = "assistant"
    mock_choice.finish_reason = "stop"
    mock_choice.stop_reason = "stop"
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_response.usage = MagicMock(
        prompt_tokens=1, completion_tokens=1, total_tokens=2
    )
    mock_response.dict = MagicMock(return_value={})
    return mock_response


async def _client_with_mock_sdk(**attrs):
    """MoonshotClient with self.client mocked to capture request kwargs.

    ``AbstractClient.client`` is a loop-local property populated by
    ``_ensure_client()`` (which calls ``get_client()`` on a cache miss) —
    it rejects direct assignment. So we build a real client, patch
    ``get_client()`` to return our mock SDK object, and prime the
    per-loop cache via ``_ensure_client()``.

    Returns a tuple of ``(client, captured)`` where ``captured`` is
    populated with the kwargs passed to
    ``client.client.chat.completions.create`` on every call.
    """
    client = MoonshotClient(api_key="test-key-123")
    for key, value in attrs.items():
        setattr(client, key, value)
    captured: dict = {}

    async def fake_create(model, messages, **kwargs):
        captured["model"] = model
        captured["messages"] = messages
        captured.update(kwargs)
        return _make_mock_response()

    mock_sdk = MagicMock()
    mock_sdk.chat.completions.create = AsyncMock(side_effect=fake_create)
    client.get_client = AsyncMock(return_value=mock_sdk)
    await client._ensure_client()
    return client, captured


@pytest.fixture
def env_key(monkeypatch):
    """Patch navconfig.config.get so MoonshotClient() picks up a fake key."""
    monkeypatch.delenv("MOONSHOT_API_KEY", raising=False)
    monkeypatch.setattr(
        moonshot_mod.config,
        "get",
        lambda key, default=None: (
            "env-moonshot-key" if key == "MOONSHOT_API_KEY" else default
        ),
    )
    return "env-moonshot-key"


# ---------------------------------------------------------------------------
# TestMoonshotClientInit
# ---------------------------------------------------------------------------


class TestMoonshotClientInit:
    """Tests for MoonshotClient constructor behavior."""

    def test_client_init_explicit_key(self):
        """api_key passed explicitly is stored on the client."""
        client = MoonshotClient(api_key="test-key-123")
        assert client.api_key == "test-key-123"

    def test_client_init_env_fallback(self, env_key):
        """With api_key=None the client falls back to MOONSHOT_API_KEY via config.get."""
        client = MoonshotClient(api_key=None)
        assert client.api_key == "env-moonshot-key"

    def test_client_base_url(self):
        """base_url points to the Moonshot API gateway."""
        client = MoonshotClient(api_key="test-key-123")
        assert client.base_url == "https://api.moonshot.ai/v1"

    def test_prompt_cache_key_stored(self):
        """prompt_cache_key constructor arg is stored on the instance."""
        client = MoonshotClient(api_key="test-key-123", prompt_cache_key="session-abc")
        assert client.prompt_cache_key == "session-abc"

    def test_prompt_cache_key_default_none(self):
        """prompt_cache_key defaults to None when not provided."""
        client = MoonshotClient(api_key="test-key-123")
        assert client.prompt_cache_key is None


# ---------------------------------------------------------------------------
# TestMoonshotClientAttributes
# ---------------------------------------------------------------------------


class TestMoonshotClientAttributes:
    """Tests for class-level attribute defaults."""

    def test_client_type_and_name(self):
        client = _make_moonshot_client()
        assert client.client_type == "moonshot"
        assert client.client_name == "moonshot"

    def test_default_model(self):
        assert MoonshotClient._default_model == MoonshotModel.KIMI_K2_6.value

    def test_fallback_model(self):
        assert MoonshotClient._fallback_model == MoonshotModel.MOONSHOT_V1_128K.value


# ---------------------------------------------------------------------------
# TestMoonshotParameterSanitization
# ---------------------------------------------------------------------------


class TestMoonshotParameterSanitization:
    """Tests for _sanitize_params_for_model — K-series parameter stripping."""

    def test_sanitize_strips_temperature_for_k_series(self):
        for model in K_SERIES_MODELS:
            out = MoonshotClient._sanitize_params_for_model(model, {"temperature": 0.7})
            assert "temperature" not in out, f"temperature not stripped for {model}"

    def test_sanitize_strips_top_p_for_k_series(self):
        for model in K_SERIES_MODELS:
            out = MoonshotClient._sanitize_params_for_model(model, {"top_p": 0.9})
            assert "top_p" not in out, f"top_p not stripped for {model}"

    def test_sanitize_strips_penalties_for_k_series(self):
        for model in K_SERIES_MODELS:
            out = MoonshotClient._sanitize_params_for_model(
                model,
                {"presence_penalty": 0.1, "frequency_penalty": 0.2, "n": 2},
            )
            assert "presence_penalty" not in out
            assert "frequency_penalty" not in out
            assert "n" not in out

    def test_sanitize_preserves_params_for_legacy_models(self):
        """moonshot-v1-* models keep temperature/top_p untouched."""
        out = MoonshotClient._sanitize_params_for_model(
            MoonshotModel.MOONSHOT_V1_128K.value,
            {"temperature": 0.7, "top_p": 0.9},
        )
        assert out["temperature"] == 0.7
        assert out["top_p"] == 0.9


# ---------------------------------------------------------------------------
# TestMoonshotMaxTokensTranslation
# ---------------------------------------------------------------------------


class TestMoonshotMaxTokensTranslation:
    """Tests for max_tokens -> max_completion_tokens translation in _chat_completion."""

    @pytest.mark.asyncio
    async def test_max_tokens_translated_to_max_completion_tokens(self):
        client, captured = await _client_with_mock_sdk()
        await client._chat_completion(
            model=MoonshotModel.MOONSHOT_V1_128K.value,
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=256,
        )
        assert "max_tokens" not in captured
        assert captured["max_completion_tokens"] == 256


# ---------------------------------------------------------------------------
# TestMoonshotThinkingMode
# ---------------------------------------------------------------------------


class TestMoonshotThinkingMode:
    """Tests for tri-mode thinking injection in _chat_completion."""

    @pytest.mark.asyncio
    async def test_thinking_k3_reasoning_effort(self):
        client, captured = await _client_with_mock_sdk()
        token = moonshot_mod._thinking_ctx.set({"reasoning_effort": "max"})
        try:
            await client._chat_completion(
                model=MoonshotModel.KIMI_K3.value,
                messages=[{"role": "user", "content": "hi"}],
            )
        finally:
            moonshot_mod._thinking_ctx.reset(token)
        assert captured["extra_body"]["reasoning_effort"] == "max"

    @pytest.mark.asyncio
    async def test_thinking_k3_defaults_to_max(self):
        """When reasoning_effort isn't supplied, K3 still defaults to 'max'."""
        client, captured = await _client_with_mock_sdk()
        await client._chat_completion(
            model=MoonshotModel.KIMI_K3.value,
            messages=[{"role": "user", "content": "hi"}],
        )
        assert captured["extra_body"]["reasoning_effort"] == "max"

    @pytest.mark.asyncio
    async def test_thinking_k26_thinking_dict_bool_true(self):
        client, captured = await _client_with_mock_sdk()
        token = moonshot_mod._thinking_ctx.set({"thinking": True})
        try:
            await client._chat_completion(
                model=MoonshotModel.KIMI_K2_6.value,
                messages=[{"role": "user", "content": "hi"}],
            )
        finally:
            moonshot_mod._thinking_ctx.reset(token)
        assert captured["extra_body"]["thinking"] == {"type": "enabled"}

    @pytest.mark.asyncio
    async def test_thinking_k26_thinking_dict_explicit(self):
        client, captured = await _client_with_mock_sdk()
        token = moonshot_mod._thinking_ctx.set({"thinking": {"type": "disabled"}})
        try:
            await client._chat_completion(
                model=MoonshotModel.KIMI_K2_6.value,
                messages=[{"role": "user", "content": "hi"}],
            )
        finally:
            moonshot_mod._thinking_ctx.reset(token)
        assert captured["extra_body"]["thinking"] == {"type": "disabled"}

    @pytest.mark.asyncio
    async def test_thinking_k26_no_injection_when_not_requested(self):
        client, captured = await _client_with_mock_sdk()
        await client._chat_completion(
            model=MoonshotModel.KIMI_K2_6.value,
            messages=[{"role": "user", "content": "hi"}],
        )
        assert "extra_body" not in captured or captured.get("extra_body") is None

    @pytest.mark.asyncio
    async def test_thinking_k27_always_on(self):
        """K2.7-code needs no thinking parameter injection — always on server-side."""
        client, captured = await _client_with_mock_sdk()
        await client._chat_completion(
            model=MoonshotModel.KIMI_K2_7_CODE.value,
            messages=[{"role": "user", "content": "hi"}],
        )
        assert "extra_body" not in captured or captured.get("extra_body") is None


# ---------------------------------------------------------------------------
# TestMoonshotPromptCacheKey
# ---------------------------------------------------------------------------


class TestMoonshotPromptCacheKey:
    """Tests for prompt_cache_key injection in _chat_completion."""

    @pytest.mark.asyncio
    async def test_prompt_cache_key_injected(self):
        client, captured = await _client_with_mock_sdk(prompt_cache_key="session-abc")
        await client._chat_completion(
            model=MoonshotModel.MOONSHOT_V1_128K.value,
            messages=[{"role": "user", "content": "hi"}],
        )
        assert captured["prompt_cache_key"] == "session-abc"

    @pytest.mark.asyncio
    async def test_prompt_cache_key_absent_when_not_configured(self):
        client, captured = await _client_with_mock_sdk()
        await client._chat_completion(
            model=MoonshotModel.MOONSHOT_V1_128K.value,
            messages=[{"role": "user", "content": "hi"}],
        )
        assert "prompt_cache_key" not in captured


# ---------------------------------------------------------------------------
# TestMoonshotUsesCreateNotParse
# ---------------------------------------------------------------------------


class TestMoonshotUsesCreateNotParse:
    """Verify _chat_completion always uses .create(), never .parse()."""

    @pytest.mark.asyncio
    async def test_uses_create_method(self):
        client, _captured = await _client_with_mock_sdk()
        await client._chat_completion(
            model=MoonshotModel.MOONSHOT_V1_128K.value,
            messages=[{"role": "user", "content": "hi"}],
        )
        client.client.chat.completions.create.assert_awaited_once()


# ---------------------------------------------------------------------------
# TestMoonshotAskThinkingPropagation
# ---------------------------------------------------------------------------


class TestMoonshotAskThinkingPropagation:
    """Verify ask()/ask_stream() forward thinking flags via the contextvar."""

    @pytest.mark.asyncio
    async def test_ask_sets_reasoning_effort_context(self):
        client = _make_moonshot_client(model=MoonshotModel.KIMI_K3.value)

        async def fake_ask(self, prompt, **kwargs):
            return dict(moonshot_mod._thinking_ctx.get())

        with patch("parrot.clients.gpt.OpenAIClient.ask", new=fake_ask):
            result = await client.ask("hi", reasoning_effort="max")

        assert result["reasoning_effort"] == "max"

    @pytest.mark.asyncio
    async def test_ask_stream_sets_thinking_context(self):
        client = _make_moonshot_client(model=MoonshotModel.KIMI_K2_6.value)

        async def fake_ask_stream(self, prompt, **kwargs):
            yield dict(moonshot_mod._thinking_ctx.get())

        with patch("parrot.clients.gpt.OpenAIClient.ask_stream", new=fake_ask_stream):
            chunks = [chunk async for chunk in client.ask_stream("hi", thinking=True)]

        assert chunks[0]["thinking"] is True


# ---------------------------------------------------------------------------
# TestMoonshotFactoryRegistration
# ---------------------------------------------------------------------------


class TestMoonshotFactoryRegistration:
    """Tests for LLMFactory registration of MoonshotClient."""

    def test_factory_registration_moonshot(self):
        assert "moonshot" in SUPPORTED_CLIENTS
        assert SUPPORTED_CLIENTS["moonshot"] is MoonshotClient

    def test_factory_registration_kimi(self):
        assert "kimi" in SUPPORTED_CLIENTS
        assert SUPPORTED_CLIENTS["kimi"] is MoonshotClient

    def test_factory_create_moonshot(self):
        c = LLMFactory.create("moonshot:kimi-k3", api_key="test-key")
        assert isinstance(c, MoonshotClient)
        assert c.model == "kimi-k3"

    def test_factory_create_kimi(self):
        c = LLMFactory.create("kimi:kimi-k2.6", api_key="test-key")
        assert isinstance(c, MoonshotClient)
        assert c.model == "kimi-k2.6"


# ---------------------------------------------------------------------------
# TestMoonshotModelEnum
# ---------------------------------------------------------------------------


class TestMoonshotModelEnum:
    """Tests that MoonshotModel enum members and capability sets are correct."""

    EXPECTED = {
        "KIMI_K3": "kimi-k3",
        "KIMI_K2_7_CODE": "kimi-k2.7-code",
        "KIMI_K2_7_CODE_HIGHSPEED": "kimi-k2.7-code-highspeed",
        "KIMI_K2_6": "kimi-k2.6",
        "MOONSHOT_V1_128K": "moonshot-v1-128k",
        "MOONSHOT_V1_8K_VISION": "moonshot-v1-8k-vision-preview",
        "MOONSHOT_V1_128K_VISION": "moonshot-v1-128k-vision-preview",
    }

    def test_model_enum_values(self):
        """All 7 model slugs are present and match spec-defined strings."""
        assert len(list(MoonshotModel)) == 7
        for member_name, expected_value in self.EXPECTED.items():
            member = MoonshotModel[member_name]
            assert member.value == expected_value, (
                f"MoonshotModel.{member_name}.value expected {expected_value!r}, "
                f"got {member.value!r}"
            )

    def test_k_series_models_frozenset(self):
        assert K_SERIES_MODELS == frozenset({
            "kimi-k3", "kimi-k2.7-code", "kimi-k2.7-code-highspeed", "kimi-k2.6",
        })

    def test_always_thinking_models_frozenset(self):
        assert ALWAYS_THINKING_MODELS == frozenset({
            "kimi-k2.7-code", "kimi-k2.7-code-highspeed",
        })

    def test_reasoning_effort_models_frozenset(self):
        assert REASONING_EFFORT_MODELS == frozenset({"kimi-k3"})

    def test_thinking_dict_models_frozenset(self):
        assert THINKING_DICT_MODELS == frozenset({"kimi-k2.6"})

    def test_vision_models_frozenset(self):
        assert VISION_MODELS == frozenset({
            "kimi-k3", "kimi-k2.7-code", "kimi-k2.7-code-highspeed", "kimi-k2.6",
            "moonshot-v1-8k-vision-preview", "moonshot-v1-128k-vision-preview",
        })


# ---------------------------------------------------------------------------
# TestMoonshotReasoningContentCapture
# ---------------------------------------------------------------------------


class TestMoonshotReasoningContentCapture:
    """Tests for _capture_reasoning_content and its wiring into ask()/ask_stream().

    OpenAIClient's AIMessageFactory.from_openai() does not surface
    reasoning_content (code-review finding); MoonshotClient patches this in
    by post-processing the AIMessage's raw_response, mirroring ZaiClient's
    getattr(message, "reasoning_content", None) idiom.
    """

    def test_capture_reasoning_content_present(self):
        message = _make_ai_message(
            raw_response={"choices": [{"message": {"reasoning_content": "because..."}}]},
        )
        MoonshotClient._capture_reasoning_content(message)
        assert message.metadata["reasoning_content"] == "because..."

    def test_capture_reasoning_content_absent(self):
        message = _make_ai_message(raw_response={"choices": [{"message": {}}]})
        MoonshotClient._capture_reasoning_content(message)
        assert "reasoning_content" not in message.metadata

    def test_capture_reasoning_content_no_raw_response(self):
        message = _make_ai_message(raw_response=None)
        MoonshotClient._capture_reasoning_content(message)  # must not raise
        assert "reasoning_content" not in message.metadata

    def test_capture_reasoning_content_no_choices(self):
        message = _make_ai_message(raw_response={"choices": []})
        MoonshotClient._capture_reasoning_content(message)  # must not raise
        assert "reasoning_content" not in message.metadata

    @pytest.mark.asyncio
    async def test_ask_captures_reasoning_content(self):
        client = _make_moonshot_client(model=MoonshotModel.KIMI_K3.value)

        async def fake_ask(self, prompt, **kwargs):
            return _make_ai_message(
                raw_response={
                    "choices": [{"message": {"reasoning_content": "step by step"}}]
                },
            )

        with patch("parrot.clients.gpt.OpenAIClient.ask", new=fake_ask):
            result = await client.ask("hi")

        assert result.metadata["reasoning_content"] == "step by step"

    @pytest.mark.asyncio
    async def test_ask_stream_captures_reasoning_content_on_final_message(self):
        client = _make_moonshot_client(model=MoonshotModel.MOONSHOT_V1_128K.value)

        async def fake_ask_stream(self, prompt, **kwargs):
            yield "chunk"
            yield _make_ai_message(
                model="moonshot-v1-128k",
                raw_response={
                    "choices": [
                        {"message": {"reasoning_content": "final answer reasoning"}}
                    ]
                },
            )

        with patch("parrot.clients.gpt.OpenAIClient.ask_stream", new=fake_ask_stream):
            chunks = [chunk async for chunk in client.ask_stream("hi")]

        final = chunks[-1]
        assert isinstance(final, AIMessage)
        assert final.metadata["reasoning_content"] == "final answer reasoning"


# ---------------------------------------------------------------------------
# TestMoonshotAskStreamKSeriesSafety
# ---------------------------------------------------------------------------


class TestMoonshotAskStreamKSeriesSafety:
    """Regression tests for the ask_stream() K-series temperature safety net.

    OpenAIClient.ask_stream()'s Chat-Completions branch calls
    self.client.chat.completions.create() directly and never routes
    through _chat_completion(), so K-series parameter stripping never runs
    for streaming. MoonshotClient.ask_stream() neutralizes self.temperature
    (and the explicit kwarg) for K-series models as a safety net.
    """

    @pytest.mark.asyncio
    async def test_ask_stream_neutralizes_temperature_for_k_series(self):
        client = _make_moonshot_client(model=MoonshotModel.KIMI_K3.value)
        captured: dict = {}

        async def fake_ask_stream(self, prompt, **kwargs):
            captured["temperature_during_call"] = self.temperature
            captured["kwarg_temperature"] = kwargs.get("temperature", "MISSING")
            yield "chunk"

        with patch("parrot.clients.gpt.OpenAIClient.ask_stream", new=fake_ask_stream):
            chunks = [chunk async for chunk in client.ask_stream("hi")]

        assert captured["temperature_during_call"] is None
        assert captured["kwarg_temperature"] is None
        assert chunks == ["chunk"]
        # Restored after the call.
        assert client.temperature == 0

    @pytest.mark.asyncio
    async def test_ask_stream_leaves_temperature_untouched_for_legacy_models(self):
        client = _make_moonshot_client(model=MoonshotModel.MOONSHOT_V1_128K.value)
        captured: dict = {}

        async def fake_ask_stream(self, prompt, **kwargs):
            captured["temperature_during_call"] = self.temperature
            yield "chunk"

        with patch("parrot.clients.gpt.OpenAIClient.ask_stream", new=fake_ask_stream):
            [chunk async for chunk in client.ask_stream("hi")]

        assert captured["temperature_during_call"] == 0


# ---------------------------------------------------------------------------
# TestMoonshotInvokeGuard
# ---------------------------------------------------------------------------


class TestMoonshotInvokeGuard:
    """Regression tests for the invoke() K-series guard.

    OpenAIClient.invoke() always sends a fixed temperature with no
    None-based omission path, so K-series models (which reject it) are
    rejected locally with a clear ValueError instead of a doomed API call.
    """

    @pytest.mark.asyncio
    async def test_invoke_raises_for_k_series_model_explicit_kwarg(self):
        client = _make_moonshot_client(model=MoonshotModel.KIMI_K2_6.value)
        with pytest.raises(ValueError, match="K-series"):
            await client.invoke("hi", model=MoonshotModel.KIMI_K3.value)

    @pytest.mark.asyncio
    async def test_invoke_raises_using_instance_default_model(self):
        client = _make_moonshot_client(model=MoonshotModel.KIMI_K2_6.value)
        with pytest.raises(ValueError, match="K-series"):
            await client.invoke("hi")  # no explicit model -> falls back to self.model

    @pytest.mark.asyncio
    async def test_invoke_delegates_for_legacy_model(self):
        client = _make_moonshot_client(model=MoonshotModel.MOONSHOT_V1_128K.value)

        async def fake_invoke(self, prompt, **kwargs):
            return "invoked-ok"

        with patch("parrot.clients.gpt.OpenAIClient.invoke", new=fake_invoke):
            result = await client.invoke("hi", model=MoonshotModel.MOONSHOT_V1_128K.value)

        assert result == "invoked-ok"
