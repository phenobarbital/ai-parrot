"""FEAT-624 — moved tag helpers."""

from __future__ import annotations

import pytest

from parrot.models.detections import DetectionBox
from parrot_pipelines.planogram.comparison.tags import slot_above, tag_price, tag_text
from parrot_pipelines.planogram.contracts import OcrReading, Shape, ShapeKind, Slot


def _box(x1: int, y1: int, x2: int, y2: int) -> DetectionBox:
    return DetectionBox(x1=x1, y1=y1, x2=x2, y2=y2, confidence=1.0)


def _tag(x1: int, y1: int, x2: int, y2: int, text: str | None = None) -> Shape:
    return Shape(shape_id="t1", image_id="img0", kind=ShapeKind.FACT_TAG, box=_box(x1, y1, x2, y2), ocr_text=text)


def _slot(slot_id: str, x1: int, x2: int) -> Slot:
    return Slot(slot_id=slot_id, image_id="img0", row_index=0, slot_index=1, box=_box(x1, 100, x2, 300))


@pytest.mark.parametrize(
    ("text", "expected"), [("$12.99", 12.99), ("12,99 EUR", 12.99), ("no price", None), (None, None)]
)
def test_tag_price_reads_dot_and_comma(text, expected):
    assert tag_price(text) == expected


def test_tag_text_prefers_own_box_reading():
    tag = _tag(0, 0, 10, 10, text="shape text")
    assert tag_text(tag, {"t1": OcrReading(text=" own box ")}, {}) == "own box"
    assert tag_text(tag, {}, {}) == "shape text"


def test_slot_above_picks_the_slot_over_the_tag():
    left, right = _slot("a", 0, 100), _slot("b", 100, 200)
    assert slot_above(_tag(20, 290, 80, 320), [left, right]) is left
    assert slot_above(_tag(20, 650, 80, 680), [left, right]) is None
