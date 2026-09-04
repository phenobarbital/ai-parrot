"""Regression tests for OpenAI-compatible client defaults.

Both behaviours covered here broke the Bedrock Mantle path (Deepseek V3.2):

1. ``_prepare_tools()`` derived the tool wire format from ``client_type``,
   so every ``OpenAIClient`` subclass with its own label emitted
   Anthropic-shaped tool schemas and the provider rejected the request with
   ``Invalid 'tools': missing field `type```.
2. ``ask()`` / ``ask_stream()`` hard-coded an OpenAI model as the signature
   default, which overrode the model the client was configured with
   (``The model 'gpt-4.1' does not exist``).

FEAT-438 TASK-2301 extends this into the permanent contract-enforcement
suite: a parametric "no gpt-* leak" check over every Phase-1
``OpenAIBaseClient`` subclass (kills the DeepSeek-404 bug class for good),
covering class-level defaults, the ``invoke()`` model-resolution chain, and
a mocked ``ask()`` request payload.
"""

import re
from types import SimpleNamespace
from typing import Any

import pytest
from parrot.clients.claude import AnthropicClient
from parrot.clients.openai import OpenAIClient
from parrot.clients.groq import GroqClient
from parrot.clients.local import LocalLLMClient
from parrot.clients.meta import MetaClient
from parrot.clients.moonshot import MoonshotClient
from parrot.clients.nova.mantle import BedrockMantleClient
from parrot.clients.nvidia import NvidiaClient
from parrot.clients.openai_base import OpenAIBaseClient
from parrot.clients.openrouter import OpenRouterClient
from parrot.clients.vllm import vLLMClient
from parrot.clients.zai import ZaiClient
from parrot.tools.manager import ToolFormat

# Every client that speaks the OpenAI wire protocol under its own label.
OPENAI_COMPATIBLE = [
    OpenAIClient,
    BedrockMantleClient,
    OpenRouterClient,
    LocalLLMClient,
    MoonshotClient,
    NvidiaClient,
]

# FEAT-438 TASK-2301/2303/2304: every OpenAIBaseClient subclass — Phase 1
# (six wire clients) + Phase 2 (GroqClient, ZaiClient).
# FEAT-526: MetaClient added.
WIRE_SUBCLASSES = [
    OpenRouterClient,
    MoonshotClient,
    NvidiaClient,
    LocalLLMClient,
    vLLMClient,
    BedrockMantleClient,
    GroqClient,
    ZaiClient,
    MetaClient,
]

# Matches an OpenAI-the-provider model id (e.g. "gpt-5-mini", "gpt-4.1").
# Deliberately anchored + dash-required so it does NOT false-positive on
# BedrockMantleClient's "openai.gpt-oss-120b" (no leading "gpt-").
GPT_LEAK = re.compile(r"^gpt-")


def _client_kwargs(cls) -> dict:
    """Minimal explicit construction kwargs so no test touches real env vars."""
    if cls is BedrockMantleClient:
        return {"api_key": "test-key", "region": "us-east-1"}
    if cls in (LocalLLMClient, vLLMClient):
        return {"api_key": "test-key", "base_url": "http://localhost:8000/v1"}
    if cls is MetaClient:
        # FEAT-526: MetaClient defaults to use_responses=True, routing
        # ask() to a MetaClient-local Responses override that bypasses
        # `_chat_completion` entirely (D1). These tests mock
        # `_chat_completion` and exercise the Chat-Completions funnel,
        # which is exactly what use_responses=False selects.
        return {"api_key": "test-key", "use_responses": False}
    return {"api_key": "test-key"}


class _StubToolManager:
    """Minimal ToolManager stand-in returning one generic tool schema."""

    def __init__(self) -> None:
        self.requested_format: Any = None

    def get_tool_schemas(self, provider_format=None):
        self.requested_format = provider_format
        return [
            {
                "name": "calculator",
                "description": "Evaluate a mathematical expression.",
                "parameters": {
                    "type": "object",
                    "properties": {"expression": {"type": "string"}},
                    "required": ["expression"],
                },
            }
        ]

    def get_tool(self, name: str):  # pragma: no cover - unused here
        return None


@pytest.mark.parametrize("client_cls", OPENAI_COMPATIBLE, ids=lambda c: c.__name__)
def test_openai_compatible_clients_declare_openai_tool_format(client_cls):
    """Subclassing OpenAIClient must not silently downgrade the tool format."""
    assert client_cls.tool_format is ToolFormat.OPENAI


def test_mantle_prepares_openai_shaped_tools():
    """Bedrock Mantle tool schemas must carry the ``type``/``function`` wrapper."""
    client = BedrockMantleClient(api_key="test-key", model="deepseek.v3.2")
    client.tool_manager = _StubToolManager()

    schemas = client._prepare_tools()

    assert client.tool_manager.requested_format is ToolFormat.OPENAI
    assert len(schemas) == 1
    assert schemas[0]["type"] == "function"
    assert schemas[0]["function"]["name"] == "calculator"


def test_anthropic_still_prepares_input_schema_tools():
    """The Anthropic wire format must be untouched by the OPENAI branch."""
    client = AnthropicClient(api_key="test-key")
    client.tool_manager = _StubToolManager()

    schemas = client._prepare_tools()

    assert client.tool_manager.requested_format is ToolFormat.ANTHROPIC
    assert schemas[0] == {
        "name": "calculator",
        "description": "Evaluate a mathematical expression.",
        "input_schema": {
            "type": "object",
            "properties": {"expression": {"type": "string"}},
            "required": ["expression"],
        },
    }


def test_resolve_tool_format_falls_back_to_client_type():
    """Clients without an explicit tool_format keep the legacy derivation."""
    client = AnthropicClient(api_key="test-key")
    assert client.tool_format is None
    assert client._resolve_tool_format() is ToolFormat.ANTHROPIC


def test_configured_model_wins_over_signature_default():
    """``ask()`` must use the model the client was configured with."""
    client = BedrockMantleClient(api_key="test-key", model="deepseek.v3.2")
    assert client._resolve_model(None) == "deepseek.v3.2"


def test_explicit_model_wins_over_configured_model():
    client = BedrockMantleClient(api_key="test-key", model="deepseek.v3.2")
    assert client._resolve_model("openai.gpt-oss-120b") == "openai.gpt-oss-120b"


def test_resolve_model_falls_back_to_class_default():
    client = BedrockMantleClient(api_key="test-key")
    assert client.model is None
    assert client._resolve_model(None) == BedrockMantleClient._default_model


# ---------------------------------------------------------------------------
# FEAT-438 TASK-2301 — parametric no-gpt-*-leak contract
# ---------------------------------------------------------------------------


def test_openai_base_client_declares_no_model_defaults():
    """The base carries no OpenAI-provider model defaults at all."""
    for attr in ("_default_model", "_fallback_model", "_lightweight_model", "model"):
        assert getattr(OpenAIBaseClient, attr, None) is None


def test_openai_client_still_has_gpt_defaults():
    """Positive control: OpenAIClient (the one class allowed to) still does."""
    assert OpenAIClient._default_model == "gpt-5-mini"
    assert OpenAIClient._fallback_model == "gpt-5-nano"
    assert OpenAIClient._lightweight_model == "gpt-4.1"


@pytest.mark.parametrize("cls", WIRE_SUBCLASSES, ids=lambda c: c.__name__)
def test_no_gpt_default_leak(cls):
    """No Phase-1 wire subclass's class-level model attrs are OpenAI ids."""
    for attr in ("_default_model", "_fallback_model", "_lightweight_model", "model"):
        val = getattr(cls, attr, None)
        assert val is None or not GPT_LEAK.match(str(val)), f"{cls.__name__}.{attr} leaks an OpenAI model id: {val!r}"


@pytest.mark.parametrize("cls", WIRE_SUBCLASSES, ids=lambda c: c.__name__)
def test_invoke_chain_never_yields_gpt(cls):
    """_resolve_invoke_model() never resolves to a gpt-* id for a client
    explicitly configured with a provider model id."""
    client = cls(model="provider-model-x", **_client_kwargs(cls))
    resolved = client._resolve_invoke_model(None)
    assert not GPT_LEAK.match(resolved), f"{cls.__name__}._resolve_invoke_model() leaked {resolved!r}"


class _FakeChoice:
    """Response.choices[0]-shaped stand-in with a dict-like message."""

    def __init__(self):
        self.message = SimpleNamespace(content="ok", tool_calls=None)
        self.finish_reason = "stop"
        self.stop_reason = "stop"


class _FakeCompletionResponse:
    """SDK-response-shaped stand-in whose ``model_dump()`` returns a real
    dict, so ``AIMessageFactory.from_openai``'s ``raw_response`` handling
    (and MoonshotClient's ``_capture_reasoning_content`` post-processing,
    which indexes into it as a dict) work exactly as they would against a
    real SDK response."""

    def __init__(self):
        self.choices = [_FakeChoice()]
        self.usage = None

    def model_dump(self):
        return {"choices": [{"message": {"content": "ok"}}]}


# vLLMClient.ask() unconditionally forwards `extra_body=extra_body if
# extra_body else None` up through LocalLLMClient.ask() to
# OpenAIBaseClient.ask() — which has never accepted an `extra_body` kwarg
# (neither does OpenAIClient.ask(), pre-FEAT-438; verified present as far
# back as commit ae3d613ab). This is a genuine, pre-existing defect
# predating FEAT-438 entirely — every real (non-mocked) call to
# vLLMClient.ask() has always raised TypeError. Out of scope per this
# task's "NOT in scope: fixing any defect these tests reveal" — reported
# here instead of silently working around it. Excluded from this one
# payload test; still covered by the two class-attribute/invoke-chain
# no-leak tests above.
_ASK_PAYLOAD_ROSTER = [cls for cls in WIRE_SUBCLASSES if cls is not vLLMClient]


@pytest.mark.asyncio
@pytest.mark.parametrize("cls", _ASK_PAYLOAD_ROSTER, ids=lambda c: c.__name__)
async def test_ask_payload_model_never_leaks_gpt(cls, monkeypatch):
    """A mocked ask() request payload carries the configured model, never
    an OpenAI-provider model id — the DeepSeek-404 bug class, permanently
    gated."""
    captured: dict = {}

    async def fake_chat_completion(self, model, messages, use_tools=False, **kwargs):
        captured["model"] = model
        return _FakeCompletionResponse()

    monkeypatch.setattr(cls, "_chat_completion", fake_chat_completion)
    client = cls(model="provider-model-x", **_client_kwargs(cls))
    await client.ask("hello")

    assert "model" in captured
    assert not GPT_LEAK.match(
        captured["model"]
    ), f"{cls.__name__}.ask() sent a gpt-* model on the wire: {captured['model']!r}"
