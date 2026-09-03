"""Tests for invoke()'s output-token budget resolution.

Background: every client's ``invoke()`` used to hardcode ``max_tokens: int = 4096``
in its signature. Reasoning ("thinking") models bill reasoning tokens against the
same output budget as the answer, so a 4096 cap could be consumed entirely by
reasoning before any answer text was emitted — observed on
``gemini-3.1-pro-preview``, where 3,199 of 4,096 tokens went to reasoning and the
call ended at MAX_TOKENS with truncated, unparseable JSON.

The fix: ``max_tokens`` defaults to ``None`` and is resolved by
``AbstractClient._resolve_invoke_max_tokens()`` against a per-client
``_invoke_max_tokens`` class default.
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
    ("parrot.clients.google.client", "GoogleGenAIClient"),
    ("parrot.clients.openai_base", "OpenAIBaseClient"),
    ("parrot.clients.groq", "GroqClient"),
    ("parrot.clients.grok", "GrokClient"),
    ("parrot.clients.zai", "ZaiClient"),
    ("parrot.clients.bedrock", "BedrockConverseBase"),
    ("parrot.clients.localllm", "LocalLLMClient"),
    ("parrot.clients.claude_agent", "ClaudeAgentClient"),
    ("parrot.clients.codex_agent", "OpenAICodexClient"),
    ("parrot.clients.hf", "TransformersClient"),
    ("parrot.clients.gemma4", "Gemma4Client"),
]


@pytest.mark.parametrize("module_path,class_name", CLIENT_PATHS)
def test_invoke_max_tokens_defaults_to_none(module_path, class_name):
    """No client may hardcode a max_tokens default in invoke()'s signature."""
    module = pytest.importorskip(module_path)
    cls = getattr(module, class_name, None)
    if cls is None:
        pytest.skip(f"{class_name} not available")
    param = inspect.signature(cls.invoke).parameters["max_tokens"]
    assert param.default is None, (
        f"{class_name}.invoke() hardcodes max_tokens={param.default!r}; "
        "it must default to None and resolve via _resolve_invoke_max_tokens()"
    )


# ---------------------------------------------------------------------------
# Resolution chain
# ---------------------------------------------------------------------------


class TestResolutionChain:
    """_resolve_invoke_max_tokens() precedence rules."""

    def test_class_default_when_nothing_configured(self):
        client = _StubClient()
        assert client._resolve_invoke_max_tokens() == 8192
        assert client._resolve_invoke_max_tokens(None) == 8192

    def test_per_call_wins_over_everything(self):
        client = _StubClient(max_tokens=1000, invoke_max_tokens=2000)
        assert client._resolve_invoke_max_tokens(512) == 512

    def test_invoke_max_tokens_wins_over_max_tokens(self):
        client = _StubClient(max_tokens=1000, invoke_max_tokens=2000)
        assert client._resolve_invoke_max_tokens() == 2000

    def test_explicit_max_tokens_is_honoured(self):
        client = _StubClient(max_tokens=32000)
        assert client._resolve_invoke_max_tokens() == 32000

    def test_implicit_max_tokens_does_not_shadow_class_default(self):
        """The framework's own max_tokens default must not win over _invoke_max_tokens.

        AbstractClient.__init__ assigns self.max_tokens = 4096 when the caller
        passes nothing. If that value participated in the chain, every client
        would still be capped at 4096 — the exact bug being fixed.
        """
        client = _StubClient()
        assert client.max_tokens == 4096  # ask()'s default, untouched
        assert client._max_tokens_configured is False
        assert client._resolve_invoke_max_tokens() == 8192

    def test_preset_counts_as_explicit(self):
        client = _StubClient(preset="detailed")
        assert client._max_tokens_configured is True
        assert client._resolve_invoke_max_tokens() == 8000

    def test_missing_attributes_fall_back_to_class_default(self):
        """A client built via __new__ (no __init__) must still resolve."""
        client = _bare(_StubClient)
        assert client._resolve_invoke_max_tokens() == 8192

    @pytest.mark.parametrize("bad", [0, -1, -4096])
    def test_non_positive_budget_rejected(self, bad):
        client = _StubClient()
        with pytest.raises(ValueError, match="positive integer"):
            client._resolve_invoke_max_tokens(bad)


# ---------------------------------------------------------------------------
# Per-client class defaults
# ---------------------------------------------------------------------------


class TestPerClientDefaults:
    """Each client declares its own budget; providers with hard caps stay low."""

    def test_base_default(self):
        assert AbstractClient._invoke_max_tokens == 8192

    def test_google_gets_extra_headroom_for_reasoning(self):
        from parrot.clients.google.client import GoogleGenAIClient

        assert GoogleGenAIClient._invoke_max_tokens == 16384

    def test_groq_capped_at_provider_limit(self):
        from parrot.clients.groq import GroqClient

        assert GroqClient._invoke_max_tokens == 4096

    @pytest.mark.parametrize(
        "module_path,class_name",
        [
            ("parrot.clients.localllm", "LocalLLMClient"),
            ("parrot.clients.hf", "TransformersClient"),
            ("parrot.clients.gemma4", "Gemma4Client"),
        ],
    )
    def test_local_backends_stay_conservative(self, module_path, class_name):
        module = pytest.importorskip(module_path)
        cls = getattr(module, class_name)
        assert cls._invoke_max_tokens == 4096

    def test_anthropic_inherits_base_default(self):
        from parrot.clients.claude import AnthropicClient

        assert AnthropicClient._invoke_max_tokens == 8192


# ---------------------------------------------------------------------------
# End-to-end: the resolved budget reaches the provider payload
# ---------------------------------------------------------------------------


def _init_json(client):
    from datamodel.parsers.json import JSONContent

    client._json = JSONContent()


class TestBudgetReachesProvider:
    """The resolved value must land in the actual provider request."""

    async def test_google_sends_resolved_max_output_tokens(self, bind_sdk_client):
        from parrot.clients.google.client import GoogleGenAIClient

        client = _bare(
            GoogleGenAIClient,
            model="gemini-3.1-pro-preview",
            _fallback_model=None,
            logger=MagicMock(),
            _clients_by_loop={},
            _locks_by_loop={},
        )
        client._tool_manager = MagicMock()
        client._tool_manager.get_tool_schemas.return_value = []
        _init_json(client)

        captured: dict = {}

        async def _generate(**kwargs):
            captured.update(kwargs)
            part = SimpleNamespace(text="hello")
            content = SimpleNamespace(parts=[part])
            candidate = SimpleNamespace(content=content, finish_reason="STOP")
            um = SimpleNamespace(prompt_token_count=1, candidates_token_count=1, total_token_count=2)
            return SimpleNamespace(candidates=[candidate], text="hello", usage_metadata=um)

        sdk = MagicMock()
        sdk.aio.models.generate_content = _generate
        bind_sdk_client(client, sdk)

        await client.invoke("hi")
        assert captured["config"].max_output_tokens == 16384

        captured.clear()
        await client.invoke("hi", max_tokens=1234)
        assert captured["config"].max_output_tokens == 1234

    async def test_openai_base_sends_resolved_max_tokens(self, bind_sdk_client):
        """OpenAIClient opts into max_completion_tokens (HOTFIX
        openai-max-completion-tokens) — the resolved budget still reaches
        the SDK, just under the renamed key.
        """
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
        response = SimpleNamespace(choices=[choice], usage=usage)

        sdk = MagicMock()
        sdk.chat.completions.create = AsyncMock(return_value=response)
        bind_sdk_client(client, sdk)

        await client.invoke("hi")
        assert sdk.chat.completions.create.await_args.kwargs["max_completion_tokens"] == 8192
        assert "max_tokens" not in sdk.chat.completions.create.await_args.kwargs

    async def test_groq_stays_at_provider_cap(self, bind_sdk_client):
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
        response = SimpleNamespace(choices=[choice], usage=usage)

        sdk = MagicMock()
        sdk.chat.completions.create = AsyncMock(return_value=response)
        bind_sdk_client(client, sdk)

        await client.invoke("hi")
        assert sdk.chat.completions.create.await_args.kwargs["max_tokens"] == 4096
