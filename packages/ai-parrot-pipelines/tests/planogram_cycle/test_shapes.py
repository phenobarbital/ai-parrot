"""Offline tests for the profile-driven shape proposer (synthetic images only)."""

import pickle

import cv2
import numpy as np
import pytest
from pydantic import ValidationError

from parrot_pipelines.planogram.perception import (
    PRICE_TAG_PROFILE,
    ShapeCandidate,
    ShapeProfile,
    propose_shapes,
)


def _wall(width: int = 2000, height: int = 1500, value: int = 40) -> np.ndarray:
    """Uniform BGR wall."""
    return np.full((height, width, 3), value, dtype=np.uint8)


def _draw_label(img: np.ndarray, x: int, y: int, w: int, h: int) -> tuple[int, int, int, int]:
    """Bright label with dark 'text' strokes so the crop has contrast (std >= 25)."""
    cv2.rectangle(img, (x, y), (x + w, y + h), (245, 245, 245), -1)
    cv2.line(img, (x + 8, y + h // 2), (x + w - 8, y + h // 2), (20, 20, 20), 3)
    return x, y, x + w, y + h


def _draw_dark_label(img: np.ndarray, x: int, y: int, w: int, h: int) -> tuple[int, int, int, int]:
    """Dark label with a bright stroke (the ``dark`` polarity mirror of ``_draw_label``)."""
    cv2.rectangle(img, (x, y), (x + w, y + h), (15, 15, 15), -1)
    cv2.line(img, (x + 8, y + h // 2), (x + w - 8, y + h // 2), (240, 240, 240), 3)
    return x, y, x + w, y + h


def _iou(a, b) -> float:
    """Intersection over union of two ``(x1, y1, x2, y2)`` boxes."""
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union else 0.0


def _box(c: ShapeCandidate) -> tuple[int, int, int, int]:
    return c.x1, c.y1, c.x2, c.y2


def _tag_band_ok(c: ShapeCandidate, width: int, height: int) -> bool:
    bw, bh = c.x2 - c.x1, c.y2 - c.y1
    return (
        0.025 * width * 0.95 <= bw <= 0.09 * width * 1.05
        and 0.014 * height * 0.95 <= bh <= 0.06 * height * 1.05
        and 1.5 <= bw / bh <= 4.6
    )


def test_price_tag_profile_finds_synthetic_tags():
    """AC-2: every drawn label proposed once; oversize/undersize blobs rejected."""
    img = _wall()
    drawn = [_draw_label(img, 100 + i * 300, 400, 120, 40) for i in range(4)]
    drawn.append(_draw_label(img, 300, 900, 150, 50))
    # Oversize bright panel and an undersize speck: neither fits the price-tag band.
    cv2.rectangle(img, (1300, 900), (1800, 1300), (240, 240, 240), -1)
    cv2.line(img, (1320, 1100), (1780, 1100), (20, 20, 20), 5)
    cv2.rectangle(img, (50, 50), (60, 55), (250, 250, 250), -1)

    found = propose_shapes(img, [PRICE_TAG_PROFILE])
    assert all(c.profile == "price_tag" and c.kind == "price_tag" for c in found)
    for rect in drawn:
        matches = [c for c in found if _iou(_box(c), rect) >= 0.7]
        assert len(matches) == 1, f"label {rect} proposed {len(matches)} times"
    assert len(found) == len(drawn)
    assert all(_tag_band_ok(c, 2000, 1500) for c in found)
    assert [c.score for c in found] == sorted((c.score for c in found), reverse=True)


def test_propose_shapes_scales_back_to_source():
    """AC-3: 4096-wide image, work_width=2048 -> source-pixel coordinates inside bounds."""
    img = _wall(width=4096, height=3072)
    drawn = [_draw_label(img, 400 + i * 800, 1000, 240, 80) for i in range(3)]
    found = propose_shapes(img, [PRICE_TAG_PROFILE], work_width=2048)
    assert len(found) == len(drawn)
    for rect in drawn:
        match = max(found, key=lambda c: _iou(_box(c), rect))
        for got, want in zip(_box(match), rect, strict=True):
            assert abs(got - want) <= 3
    for c in found:
        assert 0 <= c.x1 < c.x2 <= 4096
        assert 0 <= c.y1 < c.y2 <= 3072


def test_dark_and_edge_polarities():
    """AC-4."""
    # Dark labels on a bright wall.
    bright_wall = _wall(value=225)
    dark_rects = [_draw_dark_label(bright_wall, 200 + i * 400, 600, 120, 40) for i in range(3)]
    dark_profile = PRICE_TAG_PROFILE.model_copy(update={"name": "dark_tag", "polarity": "dark"})
    found_dark = propose_shapes(bright_wall, [dark_profile])
    for rect in dark_rects:
        assert any(_iou(_box(c), rect) >= 0.7 for c in found_dark)

    # A low-contrast box: slightly lighter than the wall, outlined by a darker stroke.
    img = _wall(value=100)
    x, y, w, h = 800, 600, 300, 150
    cv2.rectangle(img, (x, y), (x + w, y + h), (115, 115, 115), -1)
    cv2.rectangle(img, (x, y), (x + w, y + h), (60, 60, 60), 2)
    box_band = {
        "min_width": 0.05,
        "max_width": 0.3,
        "min_height": 0.03,
        "max_height": 0.3,
        "min_aspect": 1.0,
        "max_aspect": 4.0,
    }
    bright_box = ShapeProfile(name="box_bright", kind="box", polarity="bright", **box_band)
    edge_box = ShapeProfile(name="box_edge", kind="box", polarity="edge", min_contrast_std=5.0, **box_band)
    assert propose_shapes(img, [bright_box]) == []
    found_edge = propose_shapes(img, [edge_box])
    assert any(_iou(_box(c), (x, y, x + w, y + h)) >= 0.7 for c in found_edge)


def test_empty_profiles_and_blank_image_return_empty_list():
    """AC-5 (first half)."""
    img = _wall()
    _draw_label(img, 100, 100, 120, 40)
    assert propose_shapes(img, []) == []
    assert propose_shapes(_wall(), [PRICE_TAG_PROFILE]) == []
    gray = cv2.cvtColor(_wall(), cv2.COLOR_BGR2GRAY)
    assert propose_shapes(gray, [PRICE_TAG_PROFILE]) == []


@pytest.mark.parametrize("bad", [None, "x", np.zeros((0, 0, 3), np.uint8), np.zeros((4, 4, 3), np.float32)])
def test_invalid_image_raises_value_error(bad):
    """AC-5 (second half)."""
    with pytest.raises(ValueError):
        propose_shapes(bad, [PRICE_TAG_PROFILE])


def test_picklable_for_process_pool():
    """AC-6."""
    pickle.dumps(propose_shapes)
    pickle.dumps(PRICE_TAG_PROFILE)


def test_profile_rejects_inverted_band():
    """AC-7."""
    with pytest.raises(ValidationError, match="width"):
        ShapeProfile(
            name="x",
            kind="box",
            min_width=0.2,
            max_width=0.1,
            min_height=0.01,
            max_height=0.5,
            min_aspect=0.5,
            max_aspect=2.0,
            polarity="bright",
        )


def test_dedup_is_per_profile():
    """Two profiles that both match one rectangle yield two candidates (one per profile)."""
    img = _wall()
    rect = _draw_label(img, 500, 500, 120, 40)
    twin = PRICE_TAG_PROFILE.model_copy(update={"name": "price_tag_twin"})
    found = propose_shapes(img, [PRICE_TAG_PROFILE, twin])
    assert [c.profile for c in found] == ["price_tag", "price_tag_twin"]
    assert all(_iou(_box(c), rect) >= 0.7 for c in found)
