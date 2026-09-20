"""Offline tests for the provider-neutral VisionAdapter (FEAT-574, spec Module 10)."""

import asyncio

import cv2
import numpy as np
import pytest
from pydantic import BaseModel

from parrot_pipelines.planogram.backend import ResolvedBackend
from parrot_pipelines.planogram.identification import encode_png
from parrot_pipelines.planogram.identification.vision import (
    VisionAdapter,
    VisionError,
    cache_key,
    normalise_kwargs,
)

IMG = b"main-image"
REF = b"reference-image"


class Answer(BaseModel):
    """Schema used by most tests."""

    value: int


class OtherAnswer(BaseModel):
    """A different schema (must miss the cache)."""

    value: int
    label: str = "x"


def _backend(model="m-1") -> ResolvedBackend:
    return ResolvedBackend(provider="google", model=model, origin="constructor")


def _adapter(client, **kw) -> VisionAdapter:
    return VisionAdapter(client, _backend(kw.pop("model", "m-1")), semaphore=asyncio.Semaphore(2), **kw)


def test_client_without_ask_to_image_fails_fast():
    """A client lacking ask_to_image is rejected at construction."""
    with pytest.raises(VisionError):
        VisionAdapter(object(), _backend(), semaphore=asyncio.Semaphore(1))


async def test_vision_adapter_repair_retry_then_error(fake_vision_client):
    """Two invalid answers ⇒ exactly one repair retry, then VisionError."""
    fake_vision_client.queue("ask_to_image", "not json", '{"value": "nope"}')
    with pytest.raises(VisionError, match="repair"):
        await _adapter(fake_vision_client).ask("q", [IMG], Answer, stage="s", prompt_version="v1")
    calls = fake_vision_client.calls_to("ask_to_image")
    assert len(calls) == 2
    assert "Your previous answer was rejected" in calls[1]["prompt"]


async def test_no_repair_when_disabled(fake_vision_client):
    """repair_retries=0 ⇒ a single call."""
    fake_vision_client.queue("ask_to_image", "not json")
    with pytest.raises(VisionError):
        await _adapter(fake_vision_client, repair_retries=0).ask("q", [IMG], Answer, stage="s", prompt_version="v1")
    assert len(fake_vision_client.calls_to("ask_to_image")) == 1


async def test_repaired_answer_is_returned(fake_vision_client, tmp_path):
    """A valid repaired answer is returned and cached under the original key."""
    fake_vision_client.queue("ask_to_image", "garbage", '```json\n{"value": 7}\n```')
    adapter = _adapter(fake_vision_client, cache_dir=tmp_path)
    assert (await adapter.ask("q", [IMG], Answer, stage="s", prompt_version="v1")).value == 7
    again = await adapter.ask("q", [IMG], Answer, stage="s", prompt_version="v1")
    assert again.value == 7
    assert len(fake_vision_client.calls_to("ask_to_image")) == 2  # cache hit, no third call


async def test_structured_output_and_dict_answers(fake_vision_client):
    """A model instance or a dict in structured_output validates into the schema."""
    fake_vision_client.queue("ask_to_image", Answer(value=3), {"value": 4})
    adapter = _adapter(fake_vision_client)
    assert (await adapter.ask("q", [IMG], Answer, stage="s", prompt_version="v1")).value == 3
    assert (await adapter.ask("q", [IMG], Answer, stage="s", prompt_version="v1")).value == 4


async def test_vision_adapter_cache_is_schema_aware(fake_vision_client, tmp_path):
    """Second identical ask = 0 new calls; another schema = cache miss; corrupt file = miss."""
    fake_vision_client.queue("ask_to_image", '{"value": 1}', '{"value": 2}', '{"value": 3}')
    adapter = _adapter(fake_vision_client, cache_dir=tmp_path)
    assert (await adapter.ask("q", [IMG], Answer, stage="s", prompt_version="v1")).value == 1
    assert (await adapter.ask("q", [IMG], Answer, stage="s", prompt_version="v1")).value == 1
    assert len(fake_vision_client.calls_to("ask_to_image")) == 1
    assert (await adapter.ask("q", [IMG], OtherAnswer, stage="s", prompt_version="v1")).value == 2
    assert len(fake_vision_client.calls_to("ask_to_image")) == 2
    for path in tmp_path.glob("*.json"):
        path.write_text("{corrupt")
    assert (await adapter.ask("q", [IMG], Answer, stage="s", prompt_version="v1")).value == 3


async def test_cache_disabled_without_dir(fake_vision_client):
    """cache_dir=None ⇒ every ask calls the provider."""
    fake_vision_client.queue("ask_to_image", '{"value": 1}', '{"value": 1}')
    adapter = _adapter(fake_vision_client)
    await adapter.ask("q", [IMG], Answer, stage="s", prompt_version="v1")
    await adapter.ask("q", [IMG], Answer, stage="s", prompt_version="v1")
    assert len(fake_vision_client.calls_to("ask_to_image")) == 2


def test_cache_key_changes_with_schema_and_images():
    """Schema, images, prompt and backend all change the key."""
    base = cache_key("google:m", 100, "s", "v1", "p", Answer, [IMG])
    assert base == cache_key("google:m", 100, "s", "v1", "p", Answer, [IMG])
    assert base != cache_key("google:m", 100, "s", "v1", "p", OtherAnswer, [IMG])
    assert base != cache_key("google:m", 100, "s", "v1", "p", Answer, [IMG, REF])
    assert base != cache_key("google:m", 100, "s", "v1", "p2", Answer, [IMG])
    assert base != cache_key("claude:m", 100, "s", "v1", "p", Answer, [IMG])


async def test_vision_adapter_passes_resolved_model_and_rejects_unknown_kwargs(fake_vision_client):
    """The pinned model is sent; references go as reference_images; unknown kwargs raise."""
    fake_vision_client.client_name = "google"
    fake_vision_client.queue("ask_to_image", '{"value": 1}')
    await _adapter(fake_vision_client, model="gemini-x").ask("q", [IMG, REF], Answer, stage="s", prompt_version="v1")
    call = fake_vision_client.calls_to("ask_to_image")[0]
    assert call["image"] == IMG
    assert call["kwargs"]["model"] == "gemini-x"
    assert call["kwargs"]["reference_images"] == [REF]
    assert call["kwargs"]["temperature"] == 0.0
    assert call["kwargs"]["structured_output"] is Answer
    with pytest.raises(VisionError):
        normalise_kwargs("google", {"model": "x", "stream": True})


async def test_model_omitted_when_backend_has_none(fake_vision_client):
    """backend.model None ⇒ no model kwarg (provider default)."""
    fake_vision_client.queue("ask_to_image", '{"value": 1}')
    await _adapter(fake_vision_client, model=None).ask("q", [IMG], Answer, stage="s", prompt_version="v1")
    kwargs = fake_vision_client.calls_to("ask_to_image")[0]["kwargs"]
    assert "model" not in kwargs
    assert "reference_images" not in kwargs


async def test_system_prompt_folded_for_google_native_for_claude(fake_vision_client):
    """google: system prompt folded into the prompt; claude: native kwarg; both get no_memory=True."""
    fake_vision_client.client_name = "google"
    fake_vision_client.queue("ask_to_image", '{"value": 1}')
    await _adapter(fake_vision_client).ask("q", [IMG], Answer, stage="s", prompt_version="v1", system_prompt="SYS")
    google_call = fake_vision_client.calls_to("ask_to_image")[-1]
    assert google_call["prompt"] == "SYS\n\nq"
    assert "system_prompt" not in google_call["kwargs"]
    assert google_call["kwargs"]["no_memory"] is True

    fake_vision_client.client_name = "claude"
    fake_vision_client.queue("ask_to_image", '{"value": 1}')
    await _adapter(fake_vision_client).ask("q", [IMG], Answer, stage="s", prompt_version="v1", system_prompt="SYS")
    claude_call = fake_vision_client.calls_to("ask_to_image")[-1]
    assert claude_call["prompt"] == "q"
    assert claude_call["kwargs"]["system_prompt"] == "SYS"
    assert claude_call["kwargs"]["no_memory"] is True


class _SlowClient:
    """ask_to_image that never answers in time."""

    client_name = "google"

    async def ask_to_image(self, prompt, image, **kwargs):
        await asyncio.sleep(10)


async def test_timeout_becomes_vision_error():
    """A timeout surfaces as VisionError."""
    adapter = _adapter(_SlowClient(), timeout=0.05)
    with pytest.raises(VisionError, match="timed out"):
        await adapter.ask("q", [IMG], Answer, stage="s", prompt_version="v1")


async def test_cancellation_propagates():
    """Cancelling the awaiting task raises CancelledError, not VisionError."""
    adapter = _adapter(_SlowClient(), timeout=5)
    task = asyncio.create_task(adapter.ask("q", [IMG], Answer, stage="s", prompt_version="v1"))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_provider_failure_and_empty_images(fake_vision_client):
    """Provider exceptions become VisionError; empty images is a ValueError."""
    fake_vision_client.queue("ask_to_image", RuntimeError("503"))
    with pytest.raises(VisionError, match="503"):
        await _adapter(fake_vision_client).ask("q", [IMG], Answer, stage="s", prompt_version="v1")
    with pytest.raises(ValueError):
        await _adapter(fake_vision_client).ask("q", [], Answer, stage="s", prompt_version="v1")


def test_normalise_kwargs_unknown_raises():
    """Unknown keys raise; unsupported known keys and None values are dropped."""
    with pytest.raises(VisionError):
        normalise_kwargs("openai", {"bogus": 1})
    assert normalise_kwargs("openai", {"model": "m", "system_prompt": "s", "max_tokens": None}) == {"model": "m"}
    assert normalise_kwargs("unknown-provider", {"model": "m", "no_memory": True}) == {"model": "m"}


def test_encode_png_roundtrip():
    """encode_png produces PNG bytes that decode to the same array."""
    image = np.zeros((5, 7, 3), np.uint8)
    image[1, 2] = (10, 20, 30)
    data = encode_png(image)
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    decoded = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    assert np.array_equal(decoded, image)
