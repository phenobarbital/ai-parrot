"""``ask_to_image`` must build its own loop-local SDK client (offline: the GenAI SDK is mocked).

Regression: the method went straight to ``self.client.aio``, so a caller that never entered the
client's async context manager — e.g. ``PlanogramCompliance``, which builds its client through
``LLMFactory`` — failed every vision call with ``'NoneType' object has no attribute 'aio'``.
``AnthropicClient.ask_to_image`` has always called ``_ensure_client()`` first; this pins the parity.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from PIL import Image

from parrot.clients.google import GoogleGenAIClient
from parrot.clients.google.models import GoogleModel


def _mock_response(text: str) -> MagicMock:
    """A Gemini response carrying one text part and no usage metadata."""
    part = MagicMock()
    part.function_call = None
    part.text = text
    part.executable_code = None
    part.code_execution_result = None
    part.thought = False
    candidate = MagicMock()
    candidate.finish_reason = None
    candidate.content.parts = [part]
    response = MagicMock()
    response.candidates = [candidate]
    response.usage_metadata = None
    response.text = text
    return response


@pytest.fixture
def image() -> Image.Image:
    """A small white RGB image."""
    return Image.new("RGB", (64, 32), "white")


@pytest.fixture
def client() -> GoogleGenAIClient:
    """A client whose ``get_client()`` returns a mocked SDK client; never entered as a context manager."""
    instance = GoogleGenAIClient(api_key="fake_key", model=GoogleModel.GEMINI_2_5_FLASH.value)
    instance.logger = MagicMock()
    sdk = MagicMock()
    chat = MagicMock()
    chat.send_message = AsyncMock(return_value=_mock_response("a white square"))
    sdk.aio.chats.create = MagicMock(return_value=chat)
    instance._sdk = sdk
    instance._chat = chat
    instance.get_client = AsyncMock(return_value=sdk)
    return instance


async def test_ask_to_image_builds_the_client_when_the_caller_never_opened_it(client, image):
    """No ``async with``: the method itself must create the loop-local client and answer."""
    assert client.client is None  # nothing built yet for this loop

    message = await client.ask_to_image(prompt="what is this?", image=image, no_memory=True)

    client.get_client.assert_awaited()  # _ensure_client() ran
    assert client.client is client._sdk  # and cached the SDK client for this loop
    assert client._chat.send_message.await_count == 1
    assert message.provider == "google_genai"


async def test_ask_to_image_passes_the_resolved_model_to_the_chat(client, image):
    """The explicit model reaches both the client hint and ``chats.create`` — a default never masks it."""
    await client.ask_to_image(
        prompt="what is this?", image=image, model=GoogleModel.GEMINI_2_5_PRO.value, no_memory=True
    )

    assert client.get_client.await_args.kwargs.get("model") == GoogleModel.GEMINI_2_5_PRO.value
    assert client._sdk.aio.chats.create.call_args.kwargs["model"] == GoogleModel.GEMINI_2_5_PRO.value


async def test_ask_to_image_reuses_the_cached_client(client, image):
    """A second call on the same loop reuses the cached client instead of rebuilding it."""
    await client.ask_to_image(prompt="first", image=image, no_memory=True)
    build_count = client.get_client.await_count
    await client.ask_to_image(prompt="second", image=image, no_memory=True)

    assert client.get_client.await_count == build_count  # same model class ⇒ no rebuild
    assert client._chat.send_message.await_count == 2
