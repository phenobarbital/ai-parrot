"""Sampling parameters are stripped for the models that reject them.

Adaptive-thinking-only Claude models removed ``temperature`` / ``top_p`` /
``top_k`` and return 400 when any of them is sent. The bot layer's
``_create_llm_client`` passes all three unconditionally (defaulting to
0.1 / 41 / 0.9), so the guard is what stands between a default-configured
agent and a 400 on its first request.
"""
from __future__ import annotations

import pytest

from parrot.clients.claude import AnthropicClient


@pytest.fixture
def client():
    """A client instance; no request is ever made."""
    return AnthropicClient(model="claude-sonnet-4-6", api_key="sk-ant-test")


@pytest.mark.parametrize(
    "model",
    [
        "claude-opus-5",
        "claude-sonnet-5",
        "claude-fable-5",
        "claude-mythos-5",
        "claude-opus-4-8",
        "claude-opus-4-7",
    ],
)
def test_sampling_params_are_dropped(client, model):
    """Every adaptive-only model must lose all three parameters."""
    payload = {
        "model": model,
        "temperature": 0.1,
        "top_p": 0.9,
        "top_k": 41,
        "max_tokens": 1024,
    }

    sanitized = client._sanitize_payload_for_model(payload)

    assert "temperature" not in sanitized
    assert "top_p" not in sanitized
    assert "top_k" not in sanitized
    assert sanitized["max_tokens"] == 1024


@pytest.mark.parametrize(
    "model", ["claude-sonnet-4-6", "claude-opus-4-6", "claude-haiku-4-5-20251001"]
)
def test_sampling_params_are_kept_where_they_are_accepted(client, model):
    """Models that still accept sampling must not be stripped.

    Without this the guard would be free to over-match and quietly change the
    behaviour of every older model.
    """
    payload = {"model": model, "temperature": 0.1, "top_p": 0.9, "top_k": 41}

    sanitized = client._sanitize_payload_for_model(payload)

    assert sanitized["temperature"] == 0.1
    assert sanitized["top_p"] == 0.9
    assert sanitized["top_k"] == 41


def test_fable_5_also_drops_explicit_thinking_disabled(client):
    """Fable 5 needs the parameter omitted, not set to ``disabled``."""
    payload = {"model": "claude-fable-5", "thinking": {"type": "disabled"}}

    assert "thinking" not in client._sanitize_payload_for_model(payload)


def test_opus_5_keeps_an_explicit_thinking_disabled(client):
    """Only Fable 5 rejects it; the guard must stay that narrow."""
    payload = {"model": "claude-opus-5", "thinking": {"type": "disabled"}}

    sanitized = client._sanitize_payload_for_model(payload)

    assert sanitized["thinking"] == {"type": "disabled"}
