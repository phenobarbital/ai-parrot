"""Every async entry point must build its own loop-local SDK client (offline: the GenAI SDK is mocked).

Regression: these methods went straight to ``self.client.aio``, so a caller that never entered the
client's async context manager — e.g. ``PlanogramCompliance``, which builds its client through
``LLMFactory`` — failed with ``'NoneType' object has no attribute 'aio'``. The per-loop cache
contract (``docs/clients/per-loop-cache.md``) says a public method calls ``_ensure_client()``
instead of guarding on ``self.client``; ``AnthropicClient.ask_to_image`` has always done so.
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


async def test_question_builds_the_client_when_the_caller_never_opened_it(client):
    """``question()`` is a public stateless entry point: it must not require an opened client."""
    client._sdk.aio.models.generate_content = AsyncMock(return_value=_mock_response("42"))

    message = await client.question(prompt="the answer?", model=GoogleModel.GEMINI_2_5_FLASH.value)

    client.get_client.assert_awaited()
    assert client.client is client._sdk
    assert client._sdk.aio.models.generate_content.await_args.kwargs["model"] == GoogleModel.GEMINI_2_5_FLASH.value
    assert message.provider == "google_genai"


async def test_invoke_builds_the_client_instead_of_demanding_a_context_manager(client):
    """``invoke()`` used to raise RuntimeError('not initialised') — the cache now builds one."""
    client._sdk.aio.models.generate_content = AsyncMock(return_value=_mock_response("plain answer"))

    result = await client.invoke(prompt="hello")

    client.get_client.assert_awaited()
    assert result.output == "plain answer"


async def test_download_and_parse_batch_results_builds_the_client(client):
    """The batch results reader is public: a caller may hold only the job handle."""
    job = MagicMock()
    job.dest.file_name = "files/out.jsonl"
    client._sdk.aio.files.download = AsyncMock(return_value=b"")

    results = await client.download_and_parse_batch_results(job, [])

    client.get_client.assert_awaited()
    client._sdk.aio.files.download.assert_awaited_once_with(file="files/out.jsonl")
    assert results == []


async def test_deep_research_reports_a_missing_client_as_a_build_not_as_an_old_sdk(client):
    """``hasattr(None, 'interactions')`` is False — an unbuilt client must not masquerade as an old SDK."""
    del client._sdk.interactions  # a genuinely old SDK: attribute absent on a built client

    with pytest.raises(NotImplementedError, match="does not support 'interactions'"):
        await client._deep_research_ask(prompt="research this")

    client.get_client.assert_awaited()  # it built the client before judging the SDK


async def test_reformat_to_structured_does_not_repin_the_model_class(client):
    """The reformat helper borrows the caller's client: it must ensure one, but never hint a model."""
    client._sdk.aio.models.generate_content = AsyncMock(return_value=_mock_response('{"a": 1}'))

    await client._reformat_to_structured("a is one", output_config=None)

    client.get_client.assert_awaited()
    assert client.get_client.await_args.kwargs.get("model") is None  # no hint ⇒ no rebuild mid-turn
