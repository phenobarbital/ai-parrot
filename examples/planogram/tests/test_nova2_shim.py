"""Unit tests for the Nova Converse transport guard (FEAT-592, TASK-3640).

Pure-function tests only: no AWS, no network, no credentials. Per spec §8 Q1 the
live Converse round-trip is guarded at runtime, not covered by a test.
"""
from __future__ import annotations

import pytest

from examples.planogram.aws.nova_vision import NovaVisionClient


def _image_block(payload: bytes) -> dict:
    """A Converse image content block carrying ``payload``."""
    return {"image": {"format": "png", "source": {"bytes": payload}}}


def test_assert_has_image_returns_total_bytes() -> None:
    """A request with image blocks reports the summed payload size."""
    assert NovaVisionClient._assert_has_image([{"text": "describe this shelf"}, _image_block(b"abc")]) == 3


def test_assert_has_image_sums_multiple_blocks() -> None:
    """reference_images contribute to the total."""
    assert NovaVisionClient._assert_has_image([_image_block(b"abc"), _image_block(b"de")]) == 5


def test_assert_has_image_refuses_text_only_request() -> None:
    """A request with no image block is refused before it can reach Bedrock."""
    with pytest.raises(RuntimeError, match="no image block"):
        NovaVisionClient._assert_has_image([{"text": "describe this shelf"}])


def test_assert_has_image_refuses_empty_block_list() -> None:
    """An empty block list is refused, not silently treated as valid."""
    with pytest.raises(RuntimeError, match="no image block"):
        NovaVisionClient._assert_has_image([])
