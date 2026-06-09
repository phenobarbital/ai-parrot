"""Tests for LLMFactory FEAT-232 additions (TASK-1519).

Verifies that the new ``bedrock`` and ``anthropic-aws`` provider keys
resolve to :class:`~parrot.clients.claude.AnthropicClient` with the
correct ``backend`` attribute pre-bound, and that all existing providers
remain unaffected.
"""
from __future__ import annotations

import pytest
from parrot.clients.factory import LLMFactory, SUPPORTED_CLIENTS, PROVIDER_BACKEND
from parrot.clients.claude import AnthropicClient


# ── FEAT-232 new keys ────────────────────────────────────────────────────────

def test_bedrock_key_returns_anthropic_client():
    """LLMFactory.create('bedrock:...') returns AnthropicClient."""
    client = LLMFactory.create("bedrock:claude-sonnet-4-6")
    assert isinstance(client, AnthropicClient)


def test_bedrock_key_backend_is_bedrock():
    """LLMFactory.create('bedrock:...') sets backend='bedrock'."""
    client = LLMFactory.create("bedrock:claude-sonnet-4-6")
    assert client.backend == "bedrock"


def test_anthropic_aws_key_returns_anthropic_client():
    """LLMFactory.create('anthropic-aws:...') returns AnthropicClient."""
    client = LLMFactory.create("anthropic-aws:claude-sonnet-4-6")
    assert isinstance(client, AnthropicClient)


def test_anthropic_aws_key_backend_is_aws():
    """LLMFactory.create('anthropic-aws:...') sets backend='aws'."""
    client = LLMFactory.create("anthropic-aws:claude-sonnet-4-6")
    assert client.backend == "aws"


def test_bedrock_without_model():
    """LLMFactory.create('bedrock') works without a model suffix."""
    client = LLMFactory.create("bedrock")
    assert isinstance(client, AnthropicClient)
    assert client.backend == "bedrock"


def test_anthropic_aws_without_model():
    """LLMFactory.create('anthropic-aws') works without a model suffix."""
    client = LLMFactory.create("anthropic-aws")
    assert isinstance(client, AnthropicClient)
    assert client.backend == "aws"


# ── Existing providers unchanged ────────────────────────────────────────────

def test_existing_anthropic_unchanged():
    """'anthropic' provider still returns AnthropicClient with backend='direct'."""
    client = LLMFactory.create("anthropic")
    assert isinstance(client, AnthropicClient)
    assert client.backend == "direct"


def test_existing_claude_unchanged():
    """'claude' provider still returns AnthropicClient with backend='direct'."""
    client = LLMFactory.create("claude")
    assert isinstance(client, AnthropicClient)
    assert client.backend == "direct"


def test_unsupported_provider_raises():
    """Unsupported provider key raises ValueError."""
    with pytest.raises(ValueError, match="Unsupported LLM provider"):
        LLMFactory.create("not-a-provider:some-model")


# ── PROVIDER_BACKEND mapping ─────────────────────────────────────────────────

def test_provider_backend_mapping_has_bedrock():
    """PROVIDER_BACKEND contains 'bedrock' → 'bedrock'."""
    assert PROVIDER_BACKEND.get("bedrock") == "bedrock"


def test_provider_backend_mapping_has_anthropic_aws():
    """PROVIDER_BACKEND contains 'anthropic-aws' → 'aws'."""
    assert PROVIDER_BACKEND.get("anthropic-aws") == "aws"


def test_supported_clients_has_bedrock():
    """SUPPORTED_CLIENTS contains 'bedrock' key."""
    assert "bedrock" in SUPPORTED_CLIENTS


def test_supported_clients_has_anthropic_aws():
    """SUPPORTED_CLIENTS contains 'anthropic-aws' key."""
    assert "anthropic-aws" in SUPPORTED_CLIENTS


# ── Explicit backend kwarg override ─────────────────────────────────────────

def test_explicit_backend_kwarg_wins():
    """An explicit backend= kwarg overrides the PROVIDER_BACKEND injection."""
    # Passing backend="direct" to a "bedrock" key should use direct
    client = LLMFactory.create("bedrock", backend="direct")
    assert client.backend == "direct"
