"""Tests for output-token budget resolution across ask(), ask_stream() and invoke().

Background: every client hardcoded numeric ``max_tokens`` defaults in its
signatures (``invoke()``: 4096 everywhere; ``ask()``/``ask_stream()``: 4096, 512
or 16000 depending on the client). Reasoning ("thinking") models bill reasoning
tokens against the same output budget as the answer, so a 4096 cap could be
consumed entirely by reasoning before any answer text was emitted — observed on
``gemini-3.1-pro-preview``, where 3,199 of 4,096 tokens went to reasoning and the
call ended at MAX_TOKENS with truncated, unparseable JSON.

The fix: every ``max_tokens`` parameter defaults to ``None`` and resolves against
a per-client class default —``_default_max_tokens`` for ask()/ask_stream(),
``_invoke_max_tokens`` for the lightweight invoke() path.
"""
from __future__ import annotations

import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from parrot.clients.base import AbstractClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bare(cls, **attrs):
    """Build a client without running __init__ (mirrors tests/integration/test_invoke.py)."""
    client = cls.__new__(cls)
    for key, value in attrs.items():
        setattr(client, key, value)
    return client


def _init_json(client):
    from datamodel.parsers.json import JSONContent

    client._json = JSONContent()


class _StubClient(AbstractClient):
    """Minimal concrete AbstractClient so __init__ can be exercised."""

    client_type = "stub"
    client_name = "stub"

    async def ask(self, *args, **kwargs):  # pragma: no cover - contract filler
        raise NotImplementedError

    async def ask_stream(self, *args, **kwargs):  # pragma: no cover
        raise NotImplementedError

    async def invoke(self, *args, **kwargs):  # pragma: no cover
        raise NotImplementedError

    async def resume(self, *args, **kwargs):  # pragma: no cover
        raise NotImplementedError

    async def get_client(self, *args, **kwargs):  # pragma: no cover
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Signature contract
# ---------------------------------------------------------------------------

CLIENT_PATHS = [
    ("parrot.clients.base", "AbstractClient"),
    ("parrot.clients.claude", "AnthropicClient"),
    ("parrot.clients.claude_agent", "ClaudeAgentClient"),
    ("parrot.clients.codex_agent", "OpenAICodexClient"),
    ("parrot.clients.google.client", "GoogleGenAIClient"),
    ("parrot.clients.openai_base", "OpenAIBaseClient"),
    ("parrot.clients.gpt", "OpenAIClient"),
    ("parrot.clients.groq", "GroqClient"),
    ("parrot.clients.grok", "GrokClient"),
    ("parrot.clients.zai", "ZaiClient"),
    ("parrot.clients.bedrock", "BedrockConverseBase"),
    ("parrot.clients.localllm", "LocalLLMClient"),
    ("parrot.clients.hf", "TransformersClient"),
    ("parrot.clients.gemma4", "Gemma4Client"),
]


@pytest.mark.parametrize("module_path,class_name", CLIENT_PATHS)
@pytest.mark.parametrize("method", ["ask", "ask_stream", "invoke"])
def test_max_tokens_defaults_to_none(module_path, class_name, method):
    """No client may hardcode a numeric max_tokens default in a public entrypoint."""
    module = pytest.importorskip(module_path)
    cls = getattr(module, class_name, None)
    if cls is None:
        pytest.skip(f"{class_name} not available")
    params = inspect.signature(getattr(cls, method)).parameters
    if "max_tokens" not in params:
        pytest.skip(f"{class_name}.{method}() takes no max_tokens")
    default = params["max_tokens"].default
    assert default is None, (
        f"{class_name}.{method}() hardcodes max_tokens={default!r}; it must "
        "default to None and resolve via _resolve_max_tokens() / "
        "_resolve_invoke_max_tokens()"
    )


# ---------------------------------------------------------------------------
# ask() / ask_stream() resolution chain
# ---------------------------------------------------------------------------


class TestAskResolutionChain:
    """_resolve_max_tokens() precedence rules."""

    def test_class_default_when_nothing_configured(self):
        client = _StubClient()
        assert client.max_tokens is None  # "not configured", not a silent 4096
        assert client._resolve_max_tokens() == 8192
        assert client._resolve_max_tokens(None) == 8192

    def test_per_call_wins(self):
        client = _StubClient(max_tokens=1000)
        assert client._resolve_max_tokens(512) == 512

    def test_constructor_wins_over_class_default(self):
        client = _StubClient(max_tokens=32000)
        assert client._resolve_max_tokens() == 32000

    def test_preset_supplies_the_budget(self):
        client = _StubClient(preset="detailed")
        assert client._resolve_max_tokens() == 8000

    def test_none_class_default_means_let_provider_decide(self):
        class _NoCapClient(_StubClient):
            _default_max_tokens = None

        client = _NoCapClient()
        assert client._resolve_max_tokens() is None
        assert client._resolve_max_tokens(4096) == 4096

    def test_missing_attributes_fall_back_to_class_default(self):
        """A client built via __new__ (no __init__) must still resolve."""
        assert _bare(_StubClient)._resolve_max_tokens() == 8192

    @pytest.mark.parametrize("bad", [0, -1, -4096])
    def test_non_positive_budget_rejected(self, bad):
        client = _StubClient()
        with pytest.raises(ValueError, match="positive integer"):
            client._resolve_max_tokens(bad)


# ---------------------------------------------------------------------------
# invoke() resolution chain
# ---------------------------------------------------------------------------


class TestInvokeResolutionChain:
    """_resolve_invoke_max_tokens() precedence rules."""

    def test_class_default_when_nothing_configured(self):
        assert _StubClient()._resolve_invoke_max_tokens() == 8192

    def test_per_call_wins_over_everything(self):
        client = _StubClient(max_tokens=1000, invoke_max_tokens=2000)
        assert client._resolve_invoke_max_tokens(512) == 512

    def test_invoke_max_tokens_wins_over_max_tokens(self):
        client = _StubClient(max_tokens=1000, invoke_max_tokens=2000)
        assert client._resolve_invoke_max_tokens() == 2000

    def test_constructor_max_tokens_is_honoured(self):
        assert _StubClient(max_tokens=32000)._resolve_invoke_max_tokens() == 32000

    def test_invoke_never_returns_none(self):
        """Unlike ask(), invoke() always yields a concrete cap."""

        class _NoCapClient(_StubClient):
            _default_max_tokens = None

        assert _NoCapClient()._resolve_invoke_max_tokens() == 8192

    def test_missing_attributes_fall_back_to_class_default(self):
        assert _bare(_StubClient)._resolve_invoke_max_tokens() == 8192

    @pytest.mark.parametrize("bad", [0, -1, -4096])
    def test_non_positive_budget_rejected(self, bad):
        client = _StubClient()
        with pytest.raises(ValueError, match="positive integer"):
            client._resolve_invoke_max_tokens(bad)


# ---------------------------------------------------------------------------
# Per-client class defaults
# ---------------------------------------------------------------------------


class TestPerClientDefaults:
    """Each client declares its own budget; capped/expensive backends stay low."""

    def test_base_defaults(self):
        assert AbstractClient._default_max_tokens == 8192
        assert AbstractClient._invoke_max_tokens == 8192

    def test_google_omits_the_cap_for_ask_but_pads_invoke(self):
        from parrot.clients.google.client import GoogleGenAIClient

        # None => let Gemini apply its own (much larger) per-model ceiling.
        assert GoogleGenAIClient._default_max_tokens is None
        assert GoogleGenAIClient._invoke_max_tokens == 16384

    def test_groq_capped_at_provider_limit(self):
        from parrot.clients.groq import GroqClient

        assert GroqClient._default_max_tokens == 4096
        assert GroqClient._invoke_max_tokens == 4096

    def test_anthropic_default_is_non_none(self):
        """The Anthropic SDK multiplies max_tokens for its timeout calc."""
        from parrot.clients.claude import AnthropicClient

        assert AnthropicClient._default_max_tokens == 16000
        assert _bare(AnthropicClient)._resolve_max_tokens() is not None

    def test_bedrock_keeps_conservative_converse_cap(self):
        bedrock = pytest.importorskip("parrot.clients.bedrock")
        assert bedrock.BedrockConverseBase._default_max_tokens == 4096

    def test_grok_preserves_its_large_budget(self):
        from parrot.clients.grok import GrokClient

        assert GrokClient._default_max_tokens == 16000

    @pytest.mark.parametrize(
        "module_path,class_name,expected",
        [
            ("parrot.clients.localllm", "LocalLLMClient", 4096),
            ("parrot.clients.hf", "TransformersClient", 512),
            ("parrot.clients.gemma4", "Gemma4Client", 512),
        ],
    )
    def test_local_backends_stay_conservative(self, module_path, class_name, expected):
        module = pytest.importorskip(module_path)
        assert getattr(module, class_name)._default_max_tokens == expected


# ---------------------------------------------------------------------------
# End-to-end: the resolved budget reaches the provider payload
# ---------------------------------------------------------------------------


def _google_client(model="gemini-3.1-pro-preview"):
    from parrot.clients.google.client import GoogleGenAIClient

    client = _bare(
        GoogleGenAIClient,
        model=model,
        _lightweight_model=model,
        _fallback_model=None,
        logger=MagicMock(),
        _clients_by_loop={},
        _locks_by_loop={},
    )
    client._tool_manager = MagicMock()
    client._tool_manager.get_tool_schemas.return_value = []
    _init_json(client)
    return client


def _google_response(text="hello"):
    part = SimpleNamespace(text=text)
    content = SimpleNamespace(parts=[part])
    candidate = SimpleNamespace(content=content, finish_reason="STOP")
    um = SimpleNamespace(prompt_token_count=1, candidates_token_count=1, total_token_count=2)
    return SimpleNamespace(candidates=[candidate], text=text, usage_metadata=um)


class TestBudgetReachesProvider:
    """The resolved value must land in the actual provider request."""

    async def test_google_invoke_sends_resolved_max_output_tokens(self, bind_sdk_client):
        client = _google_client()
        captured: dict = {}

        async def _generate(**kwargs):
            captured.update(kwargs)
            return _google_response()

        sdk = MagicMock()
        sdk.aio.models.generate_content = _generate
        bind_sdk_client(client, sdk)

        await client.invoke("hi")
        assert captured["config"].max_output_tokens == 16384

        captured.clear()
        await client.invoke("hi", max_tokens=1234)
        assert captured["config"].max_output_tokens == 1234

    async def test_openai_base_invoke_sends_resolved_max_tokens(self, bind_sdk_client):
        from parrot.clients.gpt import OpenAIClient

        client = _bare(
            OpenAIClient,
            model="gpt-4o",
            _lightweight_model="gpt-4.1",
            _fallback_model=None,
            logger=MagicMock(),
            _clients_by_loop={},
            _locks_by_loop={},
        )
        client._tool_manager = MagicMock()
        client._tool_manager.get_tool_schemas.return_value = []
        _init_json(client)

        message = SimpleNamespace(content="hello", tool_calls=None)
        choice = SimpleNamespace(message=message, finish_reason="stop")
        usage = SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2)
        sdk = MagicMock()
        sdk.chat.completions.create = AsyncMock(
            return_value=SimpleNamespace(choices=[choice], usage=usage)
        )
        bind_sdk_client(client, sdk)

        await client.invoke("hi")
        assert sdk.chat.completions.create.await_args.kwargs["max_tokens"] == 8192

    async def test_groq_invoke_stays_at_provider_cap(self, bind_sdk_client):
        from parrot.clients.groq import GroqClient

        client = _bare(
            GroqClient,
            model="llama-3.3-70b-versatile",
            _lightweight_model="kimi-k2-instruct",
            _fallback_model=None,
            logger=MagicMock(),
            _clients_by_loop={},
            _locks_by_loop={},
        )
        client._tool_manager = MagicMock()
        client._tool_manager.get_tool_schemas.return_value = []
        client._ensure_client = AsyncMock()
        _init_json(client)

        message = SimpleNamespace(content="hello", tool_calls=None)
        choice = SimpleNamespace(message=message, finish_reason="stop")
        usage = SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2)
        sdk = MagicMock()
        sdk.chat.completions.create = AsyncMock(
            return_value=SimpleNamespace(choices=[choice], usage=usage)
        )
        bind_sdk_client(client, sdk)

        await client.invoke("hi")
        assert sdk.chat.completions.create.await_args.kwargs["max_tokens"] == 4096


# ---------------------------------------------------------------------------
# Google invoke(): reasoning is switched off where it earns nothing
# ---------------------------------------------------------------------------


class TestGoogleInvokeThinkingBudget:
    """Gemini bills reasoning against max_output_tokens — don't pay it needlessly."""

    @pytest.mark.parametrize(
        "model,structured,expect_off",
        [
            # Structured extraction: schema is supplied, nothing to reason about.
            ("gemini-3.5-flash", True, True),
            # Flash-lite is chosen for mechanical, low-latency work.
            ("gemini-3.1-flash-lite", False, True),
            ("gemini-3.1-flash-lite", True, True),
            # Free-form on a full-size model: leave the provider default alone.
            ("gemini-3.5-flash", False, False),
            # Thinking-only models reject budget=0 — never send it.
            ("gemini-3.1-pro-preview", True, False),
            ("gemini-2.5-pro", True, False),
        ],
    )
    def test_thinking_config_selection(self, model, structured, expect_off):
        client = _google_client(model)
        cfg = client._invoke_thinking_config(model, structured=structured)
        if expect_off:
            assert cfg is not None and cfg.thinking_budget == 0
        else:
            assert cfg is None

    async def test_structured_invoke_disables_thinking(self, bind_sdk_client):
        from pydantic import BaseModel

        class Person(BaseModel):
            name: str

        client = _google_client("gemini-3.5-flash")
        captured: dict = {}

        async def _generate(**kwargs):
            captured.update(kwargs)
            return _google_response('{"name": "John"}')

        sdk = MagicMock()
        sdk.aio.models.generate_content = _generate
        bind_sdk_client(client, sdk)

        await client.invoke("Extract: John", output_type=Person)
        assert captured["config"].thinking_config.thinking_budget == 0

    async def test_thinking_only_model_keeps_reasoning(self, bind_sdk_client):
        from pydantic import BaseModel

        class Person(BaseModel):
            name: str

        client = _google_client("gemini-3.1-pro-preview")
        captured: dict = {}

        async def _generate(**kwargs):
            captured.update(kwargs)
            return _google_response('{"name": "John"}')

        sdk = MagicMock()
        sdk.aio.models.generate_content = _generate
        bind_sdk_client(client, sdk)

        await client.invoke("Extract: John", output_type=Person)
        assert captured["config"].thinking_config is None
