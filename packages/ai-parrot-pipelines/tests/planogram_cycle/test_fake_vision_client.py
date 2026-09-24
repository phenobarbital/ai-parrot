"""Contract tests for the shared FakeVisionClient fixture (FEAT-574, TASK-3420)."""

from __future__ import annotations

from typing import Any

import pytest
from PIL import Image, ImageStat


@pytest.mark.asyncio
async def test_ask_to_image_pops_queue_in_order(fake_vision_client: Any) -> None:
    """Queued strings come back in order, wrapped with ``.output``."""
    fake_vision_client.queue("ask_to_image", "first", "second")
    img = Image.new("RGB", (10, 20))
    a = await fake_vision_client.ask_to_image(image=img, prompt="p1", model="whatever", no_memory=True)
    b = await fake_vision_client.ask_to_image(prompt="p2", image=img)
    assert (a.output, b.output) == ("first", "second")
    calls = fake_vision_client.calls_to("ask_to_image")
    assert [c["method"] for c in calls] == ["ask_to_image", "ask_to_image"]
    assert [c["prompt"] for c in calls] == ["p1", "p2"]
    assert all(c["image_size"] == (10, 20) for c in calls)
    assert calls[0]["kwargs"]["no_memory"] is True


@pytest.mark.asyncio
async def test_empty_queue_returns_default_output(fake_vision_client: Any) -> None:
    """An empty queue is not an error."""
    msg = await fake_vision_client.ask_to_image(prompt="p", image=None)
    assert msg.output == ""
    assert await fake_vision_client.detect_objects(image=None, prompt="p") == []


@pytest.mark.asyncio
async def test_queued_exception_is_raised(fake_vision_client: Any) -> None:
    """A queued Exception instance is raised by the call (and the call is still recorded)."""
    fake_vision_client.queue("ask_to_image", RuntimeError("boom"))
    with pytest.raises(RuntimeError, match="boom"):
        await fake_vision_client.ask_to_image(prompt="p", image=None)
    assert len(fake_vision_client.calls) == 1


@pytest.mark.asyncio
async def test_callable_and_structured_responses(fake_vision_client: Any) -> None:
    """Callables receive (prompt, image, kwargs); non-str objects land in ``.structured_output``."""
    payload = {"verdict": "ON"}
    fake_vision_client.queue("ask_to_image", lambda prompt, image, kwargs: "X:" + prompt, payload)
    first = await fake_vision_client.ask_to_image(prompt="hello", image=None)
    second = await fake_vision_client.ask_to_image(prompt="again", image=None)
    assert first.output == "X:hello"
    assert second.structured_output is payload


@pytest.mark.asyncio
async def test_works_as_async_context_manager(fake_vision_client: Any) -> None:
    """``async with fake as client`` yields the same object (legacy roi_client idiom)."""
    async with fake_vision_client as client:
        assert client is fake_vision_client


@pytest.mark.asyncio
async def test_detect_objects_records_and_returns_queue(fake_vision_client: Any) -> None:
    """detect_objects returns the queued list and records keyword arguments."""
    boxes = [{"label": "printer", "box_2d": [1, 2, 30, 40], "confidence": 0.9}]
    fake_vision_client.queue("detect_objects", boxes)
    got = await fake_vision_client.detect_objects(image=None, prompt="find", reference_images=None, output_dir=None)
    assert got == boxes
    assert fake_vision_client.calls_to("detect_objects")[0]["prompt"] == "find"


def test_unknown_method_queue_raises(fake_vision_client: Any) -> None:
    """Queuing an unknown method is a programming error."""
    with pytest.raises(KeyError):
        fake_vision_client.queue("generate", "x")


def test_synthetic_shelf_image_is_deterministic(synthetic_shelf_image: Image.Image) -> None:
    """Size/mode are fixed and the header band is brighter than the wall."""
    assert synthetic_shelf_image.size == (800, 1000)
    assert synthetic_shelf_image.mode == "RGB"
    header = ImageStat.Stat(synthetic_shelf_image.crop((0, 0, 800, 200)).convert("L")).mean[0]
    wall = ImageStat.Stat(synthetic_shelf_image.crop((0, 250, 800, 450)).convert("L")).mean[0]
    assert header > wall
