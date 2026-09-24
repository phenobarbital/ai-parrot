"""Shared offline test helpers for ai-parrot-pipelines (FEAT-574).

Provides a queue-driven fake vision client and synthetic images so planogram
tests never touch the network or a real store photo.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest
from PIL import Image, ImageDraw


class FakeAIMessage:
    """Minimal stand-in for a provider ``AIMessage``.

    Attributes:
        output: Text (or object) the legacy call sites read via ``msg.output``.
        structured_output: Parsed structured answer, when one was queued.
    """

    def __init__(self, output: Any = "", structured_output: Any = None) -> None:
        self.output = output
        self.structured_output = structured_output


def _coerce_message(item: Any) -> FakeAIMessage:
    """Wrap a queued (non-exception, non-callable) response into a ``FakeAIMessage``.

    Args:
        item: The queued response.

    Returns:
        ``item`` itself when it already is a ``FakeAIMessage``; a text message
        for strings; otherwise a message whose ``output`` and
        ``structured_output`` both carry ``item``.
    """
    if isinstance(item, FakeAIMessage):
        return item
    if isinstance(item, str):
        return FakeAIMessage(output=item)
    return FakeAIMessage(output=item, structured_output=item)


class FakeVisionClient:
    """Offline stand-in for a provider client. Records calls; pops canned responses per method."""

    client_name: str = "fake"
    model: Optional[str] = None

    def __init__(self, default_output: str = "") -> None:
        """Create an empty fake.

        Args:
            default_output: ``.output`` returned by ``ask_to_image`` when its queue is empty.
        """
        self.calls: List[Dict[str, Any]] = []
        self.default_output: str = default_output
        self._queues: Dict[str, List[Any]] = {"ask_to_image": [], "detect_objects": []}

    def queue(self, method: str, *responses: Any) -> None:
        """Append canned responses for ``method`` (``"ask_to_image"`` | ``"detect_objects"``).

        Args:
            method: Fakeable method name.
            *responses: Responses popped in order (str, object, Exception or callable).

        Raises:
            KeyError: If ``method`` is not a fakeable method name.
        """
        self._queues[method].extend(responses)

    def calls_to(self, method: str) -> List[Dict[str, Any]]:
        """Return the recorded calls of one method, in call order.

        Args:
            method: Method name to filter on.

        Returns:
            The matching call records.
        """
        return [c for c in self.calls if c["method"] == method]

    def _record(self, method: str, prompt: str, image: Any, kwargs: Dict[str, Any]) -> None:
        """Record one call (including the image size when the image is a PIL image)."""
        size = getattr(image, "size", None)
        self.calls.append(
            {"method": method, "prompt": prompt, "image": image, "image_size": size, "kwargs": dict(kwargs)}
        )

    async def ask_to_image(self, prompt: str, image: Any, **kwargs: Any) -> Any:
        """Returns an object with .output / .structured_output, or raises a queued Exception.

        Args:
            prompt: Prompt text.
            image: Image passed by the caller (any type).
            **kwargs: Any extra provider keyword (model, no_memory, max_tokens, ...).

        Returns:
            A ``FakeAIMessage``.

        Raises:
            Exception: The queued exception instance, when one is next in the queue.
        """
        self._record("ask_to_image", prompt, image, kwargs)
        if not self._queues["ask_to_image"]:
            return FakeAIMessage(output=self.default_output)
        item = self._queues["ask_to_image"].pop(0)
        if isinstance(item, Exception):
            raise item
        if callable(item) and not isinstance(item, FakeAIMessage):
            item = item(prompt, image, kwargs)
            if isinstance(item, Exception):
                raise item
        return _coerce_message(item)

    async def detect_objects(
        self, image: Any, prompt: str, reference_images: Any = None, output_dir: Any = None, **kwargs: Any
    ) -> List[Dict[str, Any]]:
        """Return the next queued list of detection dicts (``[]`` when the queue is empty).

        Args:
            image: Image passed by the caller.
            prompt: Detection prompt.
            reference_images: Optional reference images.
            output_dir: Ignored output directory.
            **kwargs: Any extra provider keyword.

        Returns:
            The queued detections.

        Raises:
            Exception: The queued exception instance, when one is next in the queue.
        """
        self._record(
            "detect_objects",
            prompt,
            image,
            {"reference_images": reference_images, "output_dir": output_dir, **kwargs},
        )
        if not self._queues["detect_objects"]:
            return []
        item = self._queues["detect_objects"].pop(0)
        if isinstance(item, Exception):
            raise item
        return item(prompt, image, kwargs) if callable(item) else item

    async def __aenter__(self) -> "FakeVisionClient":
        """Return the fake itself (legacy ``async with roi_client as client`` idiom)."""
        return self

    async def __aexit__(self, *exc: Any) -> None:
        """Nothing to release."""
        return None


@pytest.fixture
def fake_vision_client() -> FakeVisionClient:
    """A fresh queue-driven fake client (assign it to BOTH ``pipeline.llm`` and ``pipeline.roi_client``)."""
    return FakeVisionClient()


@pytest.fixture
def synthetic_shelf_image() -> Image.Image:
    """An 800x1000 RGB synthetic endcap: bright header band, three shelf boards, a few product boxes."""
    img = Image.new("RGB", (800, 1000), (40, 40, 45))
    draw = ImageDraw.Draw(img)
    # Bright backlit header band.
    draw.rectangle((0, 0, 799, 199), fill=(235, 235, 240))
    palette = [(200, 40, 40), (40, 90, 200), (40, 160, 70)]
    for board_y in (500, 750, 980):
        # Thin light shelf board.
        draw.rectangle((20, board_y, 779, board_y + 12), fill=(210, 205, 195))
        # Coloured product boxes standing on the board.
        for i, colour in enumerate(palette):
            x0 = 60 + i * 240
            draw.rectangle((x0, board_y - 150, x0 + 160, board_y - 1), fill=colour)
    return img
