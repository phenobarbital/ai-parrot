"""Sampling-parameter suppression for 2026-generation Bedrock models.

Bedrock rejects the whole Converse call when a model that dropped sampling
parameters receives one::

    ValidationException: The model returned the following errors:
    `temperature` is deprecated for this model

That broke the ``bedrock-converse`` sample agents on Claude Opus 5 while the
same payload worked on Claude Haiku 4.5, so the suppression has to be
per-model, not global.
"""
import pytest

from parrot.clients.bedrock import (
    NO_SAMPLING_MODEL_FAMILIES,
    BedrockConverseClient,
    rejects_sampling_params,
)

NO_SAMPLING_IDS = [
    "us.anthropic.claude-opus-5",
    "global.anthropic.claude-fable-5",
    "anthropic.claude-opus-4-8",
    "us.anthropic.claude-opus-4-7",
    "anthropic.claude-sonnet-5",
    "anthropic.claude-mythos-5",
]

SAMPLING_IDS = [
    "us.anthropic.claude-haiku-4-5-20251001-v1:0",
    "anthropic.claude-sonnet-4-5-20250929-v1:0",
    "us.anthropic.claude-opus-4-5-20251101-v1:0",
    "anthropic.claude-sonnet-4-6-20260115-v1:0",
    "amazon.nova-2-lite-v1:0",
    "minimax.minimax-m2.5",
]


@pytest.fixture
def client():
    return BedrockConverseClient(model="claude-opus-5")


@pytest.mark.parametrize("model_id", NO_SAMPLING_IDS)
def test_2026_generation_rejects_sampling(model_id):
    assert rejects_sampling_params(model_id) is True


@pytest.mark.parametrize("model_id", SAMPLING_IDS)
def test_older_and_vendor_models_accept_sampling(model_id):
    """A 4.5/4.6-era or non-Anthropic model must keep its temperature."""
    assert rejects_sampling_params(model_id) is False


def test_versioned_family_ids_are_not_confused():
    """``claude-opus-4-5`` must not match the ``claude-opus-5`` family."""
    assert "claude-opus-5" in NO_SAMPLING_MODEL_FAMILIES
    assert rejects_sampling_params("us.anthropic.claude-opus-4-5-20251101-v1:0") is False
    assert rejects_sampling_params("anthropic.claude-sonnet-4-5-20250929-v1:0") is False


def test_empty_model_id_is_safe():
    assert rejects_sampling_params("") is False
    assert rejects_sampling_params(None) is False


def test_inference_config_omits_temperature_for_opus5(client):
    config = client._inference_config("us.anthropic.claude-opus-5")
    assert "temperature" not in config
    assert config["maxTokens"] == (client.max_tokens or 4096)


def test_inference_config_omits_explicit_temperature_too(client):
    """An explicitly-passed temperature must also be dropped, not forwarded."""
    config = client._inference_config("us.anthropic.claude-opus-5", 512, 0.7)
    assert config == {"maxTokens": 512}


def test_inference_config_keeps_temperature_for_haiku(client):
    config = client._inference_config(
        "us.anthropic.claude-haiku-4-5-20251001-v1:0", 512, 0.7
    )
    assert config == {"maxTokens": 512, "temperature": 0.7}


def test_inference_config_falls_back_to_instance_values(client):
    config = client._inference_config("us.anthropic.claude-haiku-4-5-20251001-v1:0")
    assert config["maxTokens"] == (client.max_tokens or 4096)
    assert config["temperature"] == client.temperature
