"""The Gemini Developer API (API-key) path pins ``v1beta`` — ``v1`` rejects every tool call (google-genai 3.x)."""

from __future__ import annotations

import pytest
from google import genai
from google.genai.types import HttpOptions

import parrot.clients.google.client as client_module
from parrot.clients.google import GoogleGenAIClient
from parrot.clients.google.budget import GenerationBudget


def _budget() -> GenerationBudget:
    return GenerationBudget(max_calls=2, max_output_tokens=128, max_request_bytes=4096, timeout_s=10)


@pytest.fixture(autouse=True)
def passed_options(monkeypatch):
    """Record the ``http_options`` handed to ``genai.Client``.

    The installed SDK may default to ``v1beta`` already (2.x) while 3.x defaults to ``v1``, so the assertions are on
    what our client *passes*, independent of the SDK's own default.
    """
    seen: dict = {}
    real = genai.Client

    def _spy(**kwargs):
        seen["http_options"] = kwargs.get("http_options")
        return real(**kwargs)

    monkeypatch.setattr(client_module.genai, "Client", _spy)
    return seen


async def _build(**client_kwargs) -> genai.Client:
    client = GoogleGenAIClient(api_key="test-key", **client_kwargs)
    return await client.get_client()


@pytest.mark.asyncio
async def test_api_key_client_uses_v1beta(passed_options):
    await _build()
    assert passed_options["http_options"].api_version == "v1beta"


@pytest.mark.asyncio
async def test_api_key_client_with_budget_uses_v1beta_and_keeps_single_attempt(passed_options):
    await _build(generation_budget=_budget())
    options = passed_options["http_options"]
    assert options.api_version == "v1beta"
    assert options.retry_options.attempts == 1


@pytest.mark.asyncio
async def test_caller_api_version_is_kept(passed_options):
    client = GoogleGenAIClient(api_key="test-key")
    await client.get_client(http_options=HttpOptions(api_version="v1alpha"))
    assert passed_options["http_options"].api_version == "v1alpha"


@pytest.mark.asyncio
async def test_caller_api_version_is_kept_with_budget_and_dict_options(passed_options):
    client = GoogleGenAIClient(api_key="test-key", generation_budget=_budget())
    await client.get_client(http_options={"api_version": "v1alpha"})
    options = passed_options["http_options"]
    assert options.api_version == "v1alpha"
    assert options.retry_options.attempts == 1
