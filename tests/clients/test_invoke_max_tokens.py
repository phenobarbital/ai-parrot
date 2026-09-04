"""Tests for invoke()'s output-token budget resolution.

Background: every client's ``invoke()`` used to hardcode ``max_tokens: int = 4096``
in its signature. Reasoning ("thinking") models bill reasoning tokens against the
same output budget as the answer, so a 4096 cap could be consumed entirely by
reasoning before any answer text was emitted — observed on
``gemini-3.1-pro-preview``, where 3,199 of 4,096 tokens went to reasoning and the
call ended at MAX_TOKENS with truncated, unparseable JSON.

The fix: ``max_tokens`` defaults to ``None`` and is resolved by
``AbstractClient._resolve_max_tokens()`` — one resolver for both ``ask()`` and
``invoke()`` (``for_invoke=True`` selects invoke's own override and default).

Beyond the precedence chain, the resolver is model-aware. Output limits differ
by 8x INSIDE a single client — measured on AWS Bedrock 2026-09-03,
``claude-opus-5`` accepts 65,536 while ``qwen3-32b`` refuses anything over
16,384 — and Bedrock rejects an over-cap request rather than clamping it. So
``_model_max_tokens`` both lifts a known model to its real limit and clamps
anything above it.
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
    ("parrot.clients.openai.client", "OpenAIClient"),
    ("parrot.clients.groq", "GroqClient"),
    ("parrot.clients.grok", "GrokClient"),
    ("parrot.clients.zai", "ZaiClient"),
    ("parrot.clients.bedrock", "BedrockConverseBase"),
    ("parrot.clients.local.client", "LocalLLMClient"),
    ("parrot.clients.claude_agent", "ClaudeAgentClient"),
    ("parrot.clients.openai.codex_agent", "OpenAICodexClient"),
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
        "default to None and resolve via _resolve_max_tokens()"
    )


@pytest.mark.parametrize("module_path,class_name", CLIENT_PATHS)
def test_no_method_hardcodes_a_numeric_max_tokens(module_path, class_name):
    """Sweep EVERY method, not just the three public entrypoints.

    The convenience methods are where this bug keeps reappearing: they build a
    provider payload directly, so a hardcoded default silently shadows both the
    constructor's ``max_tokens`` and the client's ``_default_max_tokens``. Two
    rounds of this fix missed them --- ``AnthropicClient``'s five summarize /
    translate / key-points / sentiment / review helpers passed
    ``self.max_tokens`` straight through, and ``GroqClient``'s three helpers
    pinned 1024 --- because the entrypoint-only check above never looked at
    them.

    A required parameter (no default) is fine; only a numeric default is not.
    """
    module = pytest.importorskip(module_path)
    cls = getattr(module, class_name, None)
    if cls is None:
        pytest.skip(f"{class_name} not available")

    offenders = []
    for name, func in inspect.getmembers(cls, inspect.isfunction):
        # Only methods this project defines --- skip inherited third-party ones.
        if not getattr(func, "__module__", "").startswith("parrot.clients"):
            continue
        param = inspect.signature(func).parameters.get("max_tokens")
        if param is None:
            continue
        if isinstance(param.default, (int, float)) and not isinstance(param.default, bool):
            offenders.append(f"{name}(max_tokens={param.default!r})")

    assert not offenders, (
        f"{class_name} hardcodes a numeric max_tokens default in: "
        + ", ".join(sorted(offenders))
        + ". Default it to None and resolve via _resolve_max_tokens() so the "
        "constructor's max_tokens and the client's _default_max_tokens are honoured."
    )


# ---------------------------------------------------------------------------
# Resolution chain
# ---------------------------------------------------------------------------

class TestResolutionChain:
    """_resolve_invoke_max_tokens() precedence rules."""

    def test_class_default_when_nothing_configured(self):
        client = _StubClient()
        assert client._resolve_invoke_max_tokens() == AbstractClient._default_max_tokens
        assert client._resolve_invoke_max_tokens(None) == AbstractClient._default_max_tokens

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
        """An unconfigured max_tokens must not win over _invoke_max_tokens.

        ``AbstractClient.__init__`` leaves ``self.max_tokens`` at ``None`` when
        the caller passes nothing — a framework-wide default assigned eagerly
        would be indistinguishable from a deliberate caller choice and would
        shadow every per-client default downstream. ``_max_tokens_configured``
        records that distinction for the preset case, where a preset may or may
        not carry a budget of its own.
        """
        client = _StubClient()
        assert client.max_tokens is None  # "not configured", not a silent default
        assert client._max_tokens_configured is False
        assert client._resolve_invoke_max_tokens() == _StubClient._default_max_tokens

    def test_preset_counts_as_explicit(self):
        client = _StubClient(preset="detailed")
        assert client._max_tokens_configured is True
        assert client._resolve_invoke_max_tokens() == 8000

    def test_missing_attributes_fall_back_to_class_default(self):
        """A client built via __new__ (no __init__) must still resolve."""
        client = _bare(_StubClient)
        assert client._resolve_invoke_max_tokens() == AbstractClient._default_max_tokens

    @pytest.mark.parametrize("bad", [0, -1, -4096])
    def test_non_positive_budget_rejected(self, bad):
        client = _StubClient()
        with pytest.raises(ValueError, match="positive integer"):
            client._resolve_invoke_max_tokens(bad)


# ---------------------------------------------------------------------------
# ask() / ask_stream() resolution chain — the same resolver, for_invoke=False
# ---------------------------------------------------------------------------

class TestAskResolutionChain:
    """_resolve_max_tokens() precedence rules on the ask() side."""

    def test_class_default_when_nothing_configured(self):
        client = _StubClient()
        assert client._resolve_max_tokens() == _StubClient._default_max_tokens
        assert client._resolve_max_tokens(None) == _StubClient._default_max_tokens

    def test_per_call_wins(self):
        client = _StubClient(max_tokens=1000)
        assert client._resolve_max_tokens(512) == 512

    def test_constructor_wins_over_class_default(self):
        client = _StubClient(max_tokens=32000)
        assert client._resolve_max_tokens() == 32000

    def test_preset_supplies_the_budget(self):
        client = _StubClient(preset="detailed")
        assert client._resolve_max_tokens() == 8000

    def test_invoke_max_tokens_does_not_leak_into_ask(self):
        """``invoke_max_tokens`` is invoke()'s alone; ask() must ignore it."""
        client = _StubClient(invoke_max_tokens=2000)
        assert client._resolve_max_tokens() == _StubClient._default_max_tokens
        assert client._resolve_invoke_max_tokens() == 2000

    def test_none_class_default_means_let_provider_decide(self):
        """``_default_max_tokens = None`` on the ask() path sends no cap at all.

        GoogleGenAIClient does exactly this, so Gemini applies its own (much
        larger) per-model ceiling instead of a number this framework invented.
        """
        class _NoCapClient(_StubClient):
            _default_max_tokens = None

        client = _NoCapClient()
        assert client._resolve_max_tokens() is None
        assert client._resolve_max_tokens(4096) == 4096

    def test_invoke_never_returns_none(self):
        """Unlike ask(), invoke() always yields a concrete cap."""
        class _NoCapClient(_StubClient):
            _default_max_tokens = None
            _invoke_max_tokens = 4096

        assert _NoCapClient()._resolve_invoke_max_tokens() == 4096

    def test_missing_attributes_fall_back_to_class_default(self):
        """A client built via __new__ (no __init__) must still resolve."""
        assert _bare(_StubClient)._resolve_max_tokens() == _StubClient._default_max_tokens

    @pytest.mark.parametrize("bad", [0, -1, -4096])
    def test_non_positive_budget_rejected(self, bad):
        client = _StubClient()
        with pytest.raises(ValueError, match="positive integer"):
            client._resolve_max_tokens(bad)


# ---------------------------------------------------------------------------
# Per-client class defaults
# ---------------------------------------------------------------------------

class TestPerClientDefaults:
    """Each client declares its own budget; providers with hard caps stay low."""

    def test_google_omits_the_cap_for_ask_but_pads_invoke(self):
        from parrot.clients.google.client import GoogleGenAIClient

        # None => let Gemini apply its own (much larger) per-model ceiling.
        assert GoogleGenAIClient._default_max_tokens is None
        assert GoogleGenAIClient._invoke_max_tokens == 16384

    def test_anthropic_default_is_non_none(self):
        """The Anthropic SDK multiplies max_tokens for its timeout calc."""
        from parrot.clients.claude import AnthropicClient

        assert AnthropicClient._default_max_tokens is not None
        assert _bare(AnthropicClient)._resolve_max_tokens() is not None

    def test_bedrock_keeps_conservative_converse_cap(self):
        bedrock = pytest.importorskip("parrot.clients.bedrock")
        assert bedrock.BedrockConverseBase._default_max_tokens == 4096

    def test_grok_preserves_its_large_budget(self):
        from parrot.clients.grok import GrokClient

        assert GrokClient._default_max_tokens == 16000

    @pytest.mark.parametrize("module_path,class_name,expected", [
        ("parrot.clients.local.client", "LocalLLMClient", 4096),
        ("parrot.clients.hf", "TransformersClient", 512),
        ("parrot.clients.gemma4", "Gemma4Client", 512),
    ])
    def test_local_backends_ask_budget_stays_conservative(
        self, module_path, class_name, expected
    ):
        module = pytest.importorskip(module_path)
        assert getattr(module, class_name)._default_max_tokens == expected

    def test_base_leaves_invoke_default_unset(self):
        """``None`` means "invoke() uses _default_max_tokens".

        A concrete number here would silently override every client that raises
        _default_max_tokens for a good reason (NvidiaClient's 65,536 for
        reasoning models, AnthropicClient's non-streaming ceiling), because a
        base class attribute resolves before those.
        """
        assert AbstractClient._invoke_max_tokens is None
        assert AbstractClient._default_max_tokens == 16384

    def test_google_gets_extra_headroom_for_reasoning(self):
        from parrot.clients.google.client import GoogleGenAIClient
        assert GoogleGenAIClient._invoke_max_tokens == 16384

    def test_groq_capped_below_the_provider_limit(self):
        # Groq refuses max_tokens at or above 4096 — the limit is exclusive.
        from parrot.clients.groq import GroqClient
        assert GroqClient._default_max_tokens == 4095
        assert GroqClient()._resolve_invoke_max_tokens(None, "openai/gpt-oss-120b") < 4096

    @pytest.mark.parametrize("module_path,class_name", [
        ("parrot.clients.local.client", "LocalLLMClient"),
        ("parrot.clients.hf", "TransformersClient"),
        ("parrot.clients.gemma4", "Gemma4Client"),
    ])
    def test_local_backends_stay_conservative(self, module_path, class_name):
        module = pytest.importorskip(module_path)
        cls = getattr(module, class_name)
        assert cls._invoke_max_tokens == 4096

    def test_client_default_is_not_shadowed_by_the_base_invoke_default(self):
        """A client's _default_max_tokens must reach invoke(), not just ask().

        Regression guard: while AbstractClient._invoke_max_tokens held a
        concrete 8192, NvidiaClient's deliberate 65,536 (reasoning models draw
        reasoning_content from the answer's budget) was ignored by invoke().
        """
        from parrot.clients.nvidia import NvidiaClient
        assert NvidiaClient._default_max_tokens == 65536
        assert NvidiaClient()._resolve_invoke_max_tokens(None, "openai/gpt-oss-120b") == 65536


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
            um = SimpleNamespace(
                prompt_token_count=1, candidates_token_count=1, total_token_count=2
            )
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
        from parrot.clients.openai import OpenAIClient

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
        # OpenAI sets no _invoke_max_tokens of its own, so invoke() picks up
        # AbstractClient._default_max_tokens rather than a separate base value.
        assert (
            sdk.chat.completions.create.await_args.kwargs["max_tokens"]
            == AbstractClient._default_max_tokens
        )

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
        # 4095, not 4096: Groq's limit is exclusive, and the previous value was
        # the exact one the provider rejects.
        sent = sdk.chat.completions.create.await_args.kwargs["max_tokens"]
        assert sent == GroqClient._default_max_tokens
        assert sent < 4096


# ---------------------------------------------------------------------------
# Model awareness: _model_max_tokens lifts a known model to its real limit and
# clamps anything above it.
# ---------------------------------------------------------------------------

class _ModelAwareClient(_StubClient):
    """Stub whose models have deliberately divergent limits."""

    _default_max_tokens = 1000
    _model_max_tokens = {"big": 5000, "small": 100, "big-model-v2": 7000}


class TestModelAwareResolution:
    """Why this exists: one number per client cannot be correct.

    Measured on AWS Bedrock (us-east-1, 2026-09-03) by walking max_tokens up per
    model until Converse rejected it — inside ONE client, claude-opus-5 accepts
    65,536 and qwen3-32b refuses anything over 16,384. A single class-wide value
    either starves opus or breaks qwen, and Bedrock rejects rather than clamps.
    """

    def test_known_model_is_lifted_to_its_own_limit(self):
        # max_tokens is a ceiling, not a reservation — nothing is billed for
        # unused headroom, so a known limit beats a conservative class default.
        assert _ModelAwareClient()._resolve_max_tokens(None, "big") == 5000

    def test_unknown_model_keeps_the_class_default(self):
        assert _ModelAwareClient()._resolve_max_tokens(None, "unlisted") == 1000

    def test_no_model_keeps_the_class_default(self):
        assert _ModelAwareClient()._resolve_max_tokens(None, None) == 1000

    def test_explicit_per_call_value_is_still_clamped(self):
        # Otherwise the provider answers with a validation error instead.
        assert _ModelAwareClient()._resolve_max_tokens(999_999, "small") == 100

    def test_caller_configured_budget_is_clamped_too(self):
        client = _ModelAwareClient(max_tokens=4000)
        assert client._resolve_max_tokens(None, "small") == 100

    def test_caller_configured_budget_beats_the_model_lift(self):
        client = _ModelAwareClient(max_tokens=250)
        assert client._resolve_max_tokens(None, "big") == 250

    def test_fragment_matches_a_provider_qualified_id(self):
        # One entry has to cover every spelling of the same model.
        assert _ModelAwareClient()._resolve_max_tokens(None, "us.vendor.big-v1:0") == 5000

    def test_matching_is_case_insensitive(self):
        assert _ModelAwareClient()._resolve_max_tokens(None, "US.VENDOR.BIG-V1:0") == 5000

    def test_longest_fragment_wins(self):
        # "big-model-v2" also contains "big"; the specific entry must win, or a
        # family-wide entry would shadow every member of that family.
        assert _ModelAwareClient()._resolve_max_tokens(None, "big-model-v2") == 7000

    def test_empty_table_means_no_lift_and_no_clamp(self):
        assert _StubClient()._resolve_max_tokens(None, "big") == _StubClient._default_max_tokens

    def test_the_lift_reaches_invoke_not_just_ask(self):
        client = _ModelAwareClient()
        assert client._resolve_max_tokens(None, "big", for_invoke=True) == 5000

    def test_instance_invoke_override_applies_only_to_invoke(self):
        client = _ModelAwareClient(invoke_max_tokens=300)
        assert client._resolve_max_tokens(None, "big", for_invoke=True) == 300
        assert client._resolve_max_tokens(None, "big") == 5000


class TestMeasuredProviderLimits:
    """Limits measured against live providers on 2026-09-03."""

    def test_bedrock_lifts_opus_5(self):
        from parrot.clients.bedrock import BedrockConverseClient
        client = BedrockConverseClient()
        assert client._resolve_max_tokens(None, "us.anthropic.claude-opus-5", for_invoke=True) == 65536

    def test_bedrock_holds_qwen3_32b_down(self):
        from parrot.clients.bedrock import BedrockConverseClient
        client = BedrockConverseClient()
        assert client._resolve_max_tokens(None, "qwen.qwen3-32b-v1:0", for_invoke=True) == 16384

    def test_nova_pro_stays_under_its_10k_limit(self):
        from parrot.clients.nova import NovaClient
        assert NovaClient()._resolve_max_tokens(None, "us.amazon.nova-pro-v1:0", for_invoke=True) == 8192

    def test_nova_2_lite_gets_its_larger_limit(self):
        from parrot.clients.nova import NovaClient
        assert NovaClient()._resolve_max_tokens(None, "us.amazon.nova-2-lite-v1:0", for_invoke=True) == 32768


class TestAnthropicNonStreamingCeiling:
    """``ask()``/``invoke()`` are non-streaming, and the SDK enforces a ceiling.

    ``anthropic._base_client._calculate_nonstreaming_timeout`` raises
    ``ValueError`` when ``3600 * max_tokens / 128_000 > 600`` — above 21,333
    tokens — *before* sending anything. A larger default would break every
    non-streaming Anthropic call rather than lengthen it. Raising it means
    teaching invoke() to stream, which is a separate change.
    """

    NON_STREAMING_CEILING = 128_000 * 600 // 3600  # 21_333

    def test_default_sits_at_the_sdk_ceiling(self):
        from parrot.clients.claude import AnthropicClient
        assert AnthropicClient._default_max_tokens == self.NON_STREAMING_CEILING

    @pytest.mark.parametrize(
        "model", ["claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5-20251001"]
    )
    def test_no_model_resolves_above_the_ceiling(self, model):
        from parrot.clients.claude import AnthropicClient
        budget = AnthropicClient()._resolve_max_tokens(None, model, for_invoke=True)
        assert budget <= self.NON_STREAMING_CEILING

    def test_the_ceiling_is_the_transports_not_the_models(self):
        # boto3 Converse has no such guard, so the same model gets far more room.
        from parrot.clients.bedrock import BedrockConverseClient
        from parrot.clients.claude import AnthropicClient
        assert (
            BedrockConverseClient()._resolve_max_tokens(None, "claude-opus-5")
            > AnthropicClient()._resolve_max_tokens(None, "claude-opus-5")
        )


# ---------------------------------------------------------------------------
# Google invoke(): reasoning is switched off where it earns nothing
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
    um = SimpleNamespace(
        prompt_token_count=1, candidates_token_count=1, total_token_count=2
    )
    return SimpleNamespace(candidates=[candidate], text=text, usage_metadata=um)


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
