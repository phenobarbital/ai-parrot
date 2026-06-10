"""Unit tests for AnthropicClient model-capability guards.

Covers the Fable 5 / Opus 4.7 / Opus 4.8 sanitization added to drop request
params those models reject with a 400:

- adaptive-thinking-only models remove ``temperature`` / ``top_p`` / ``top_k``
- Fable 5 additionally rejects an explicit ``thinking={"type": "disabled"}``

The guards mirror ``GoogleGenAIClient._requires_thinking``.
"""
import pytest

from parrot.clients.claude import AnthropicClient
from parrot.models.claude import ClaudeModel


@pytest.fixture(scope="module")
def client():
    """A lightweight AnthropicClient instance (no network calls are made)."""
    return AnthropicClient(api_key="test-key")


# ── ClaudeModel enum membership ──────────────────────────────────────────────

def test_claude_model_exposes_new_models():
    """Fable 5 and the current Opus tiers are present in the enum."""
    assert ClaudeModel.FABLE_5.value == "claude-fable-5"
    assert ClaudeModel.OPUS_4_8.value == "claude-opus-4-8"
    assert ClaudeModel.OPUS_4_7.value == "claude-opus-4-7"


# ── _model_str ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value,expected", [
    (ClaudeModel.FABLE_5, "claude-fable-5"),
    ("claude-opus-4-8", "claude-opus-4-8"),
    (None, ""),
    ("", ""),
])
def test_model_str_normalisation(value, expected):
    assert AnthropicClient._model_str(value) == expected


# ── _rejects_sampling_params ─────────────────────────────────────────────────

@pytest.mark.parametrize("model", [
    "claude-fable-5",
    "claude-opus-4-8",
    "claude-opus-4-7",
    ClaudeModel.FABLE_5,
    ClaudeModel.OPUS_4_8,
])
def test_adaptive_only_models_reject_sampling(model):
    assert AnthropicClient._rejects_sampling_params(model) is True


@pytest.mark.parametrize("model", [
    "claude-sonnet-4-6",
    "claude-opus-4-6",
    "claude-haiku-4-5-20251001",
    "claude-3-5-sonnet-20241022",
    None,
    "",
])
def test_other_models_accept_sampling(model):
    assert AnthropicClient._rejects_sampling_params(model) is False


# ── _rejects_explicit_thinking_disabled ──────────────────────────────────────

def test_only_fable5_rejects_thinking_disabled():
    # Fable 5 is the only model that 400s on thinking={type:disabled}
    assert AnthropicClient._rejects_explicit_thinking_disabled("claude-fable-5") is True
    assert AnthropicClient._rejects_explicit_thinking_disabled(ClaudeModel.FABLE_5) is True
    # Opus 4.7 / 4.8 still accept an explicit disabled thinking block
    assert AnthropicClient._rejects_explicit_thinking_disabled("claude-opus-4-8") is False
    assert AnthropicClient._rejects_explicit_thinking_disabled("claude-opus-4-7") is False
    assert AnthropicClient._rejects_explicit_thinking_disabled("claude-sonnet-4-6") is False


# ── _sanitize_payload_for_model ──────────────────────────────────────────────

def test_sanitize_fable5_drops_sampling_and_thinking_disabled(client):
    payload = {
        "model": "claude-fable-5",
        "max_tokens": 100,
        "temperature": 0.7,
        "top_p": 0.9,
        "top_k": 40,
        "thinking": {"type": "disabled"},
    }
    out = client._sanitize_payload_for_model(payload)
    assert out == {"model": "claude-fable-5", "max_tokens": 100}


def test_sanitize_opus48_drops_sampling_keeps_thinking_disabled(client):
    # Opus 4.8 removed sampling params but still accepts thinking={disabled}.
    payload = {
        "model": "claude-opus-4-8",
        "max_tokens": 100,
        "temperature": 0.5,
        "thinking": {"type": "disabled"},
    }
    out = client._sanitize_payload_for_model(payload)
    assert out == {
        "model": "claude-opus-4-8",
        "max_tokens": 100,
        "thinking": {"type": "disabled"},
    }


def test_sanitize_keeps_adaptive_thinking_on_fable5(client):
    # Only thinking={type:disabled} is dropped — adaptive thinking is preserved.
    payload = {
        "model": "claude-fable-5",
        "max_tokens": 100,
        "thinking": {"type": "adaptive"},
    }
    out = client._sanitize_payload_for_model(payload)
    assert out == {
        "model": "claude-fable-5",
        "max_tokens": 100,
        "thinking": {"type": "adaptive"},
    }


def test_sanitize_leaves_non_adaptive_models_untouched(client):
    payload = {
        "model": "claude-sonnet-4-6",
        "max_tokens": 100,
        "temperature": 0.5,
    }
    out = client._sanitize_payload_for_model(payload)
    assert out == {
        "model": "claude-sonnet-4-6",
        "max_tokens": 100,
        "temperature": 0.5,
    }


def test_sanitize_mutates_in_place_and_returns_same_dict(client):
    payload = {"model": "claude-fable-5", "temperature": 0.7, "max_tokens": 10}
    out = client._sanitize_payload_for_model(payload)
    assert out is payload
    assert "temperature" not in payload
