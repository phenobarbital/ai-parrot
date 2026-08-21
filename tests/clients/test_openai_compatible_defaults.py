"""Regression tests for OpenAI-compatible client defaults.

Both behaviours covered here broke the Bedrock Mantle path (Deepseek V3.2):

1. ``_prepare_tools()`` derived the tool wire format from ``client_type``,
   so every ``OpenAIClient`` subclass with its own label emitted
   Anthropic-shaped tool schemas and the provider rejected the request with
   ``Invalid 'tools': missing field `type```.
2. ``ask()`` / ``ask_stream()`` hard-coded an OpenAI model as the signature
   default, which overrode the model the client was configured with
   (``The model 'gpt-4.1' does not exist``).
"""
from types import SimpleNamespace
from typing import Any

import pytest

from parrot.clients.claude import AnthropicClient
from parrot.clients.gpt import OpenAIClient
from parrot.clients.localllm import LocalLLMClient
from parrot.clients.moonshot import MoonshotClient
from parrot.clients.nova.mantle import BedrockMantleClient
from parrot.clients.nvidia import NvidiaClient
from parrot.clients.openrouter import OpenRouterClient
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
