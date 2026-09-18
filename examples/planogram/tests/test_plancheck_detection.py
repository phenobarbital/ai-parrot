"""Unit tests for plancheck.detection (FEAT-565, spec §4 — Module 3). Synthetic image only."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import cv2
import numpy as np
import pytest

from plancheck.detection import detect_tags, find_candidates, group_rows

REFERENCE_SCRIPT = Path(__file__).resolve().parents[1] / "white_label_detector" / "detect_price_labels.py"


def _load_reference():
    """Load the original detector script by path; skip when it is not in this checkout."""
    if not REFERENCE_SCRIPT.exists():
        pytest.skip(f"reference detector not present: {REFERENCE_SCRIPT}")
    spec = importlib.util.spec_from_file_location("ref_detect_price_labels", REFERENCE_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_detect_synthetic_rows(shelf_image: np.ndarray) -> None:
    rows, unassigned = detect_tags(shelf_image, "img")
    assert unassigned == []
    assert len(rows) == 3
    prev_intercept: float | None = None
    for row_number, row in enumerate(rows, 1):
        assert row.row == row_number
        assert len(row.tags) == 6
        assert abs(row.slope) < 1e-6
        if prev_intercept is not None:
            assert row.intercept > prev_intercept
        prev_intercept = row.intercept
        prev_x1: int | None = None
        for position, tag in enumerate(row.tags, 1):
            assert tag.position == position
            x1, y1, x2, y2 = tag.box
            if prev_x1 is not None:
                assert x1 > prev_x1
            prev_x1 = x1
            cx1, cy1, cx2, cy2 = tag.crop_box
            assert cx1 <= x1 and cy1 <= y1 and cx2 >= x2 and cy2 >= y2
            assert 0 <= cx1 and 0 <= cy1
            assert cx2 <= shelf_image.shape[1] and cy2 <= shelf_image.shape[0]
    first_tag = rows[0].tags[0]
    assert first_tag.box == (150, 300, 220, 330)
    assert first_tag.tag_id == "img_r01_p01"


def test_detect_roi_filters(shelf_image: np.ndarray) -> None:
    rows, _ = detect_tags(shelf_image, "img", roi=(0.0, 0.0, 1.0, 0.45))
    assert len(rows) == 1
    assert len(rows[0].tags) == 6

    rows_narrow, unassigned_narrow = detect_tags(shelf_image, "img", roi=(0.0, 0.0, 0.5, 1.0))
    assert rows_narrow == []
    assert isinstance(unassigned_narrow, list)


def test_detect_matches_reference_script(shelf_image: np.ndarray) -> None:
    ref = _load_reference()
    ref_raw = ref.candidates(shelf_image, 0.025, 0.09)
    raw = find_candidates(shelf_image)
    assert [d["box"] for d in raw] == [d["box"] for d in ref_raw]
    ref_rows, ref_unassigned = ref.group_rows(ref_raw, shelf_image.shape[1])
    rows, unassigned = group_rows(raw, shelf_image.shape[1])
    assert len(rows) == len(ref_rows)
    for row, ref_row in zip(rows, ref_rows, strict=True):
        assert row["members"] == ref_row["members"]
        assert row["slope"] == pytest.approx(ref_row["slope"])
        assert row["intercept"] == pytest.approx(ref_row["intercept"])
    assert unassigned == ref_unassigned


def test_detect_downscales_and_rescales() -> None:
    scale = 2
    img_h, img_w = 1200 * scale, 1600 * scale
    tag_w, tag_h, tag_x0, tag_dx = 70 * scale, 30 * scale, 150 * scale, 220 * scale
    tag_rows_y = tuple(y * scale for y in (300, 650, 1000))
    image = np.full((img_h, img_w, 3), 30, dtype=np.uint8)
    for top in tag_rows_y:
        for i in range(6):
            x = tag_x0 + tag_dx * i
            cv2.rectangle(image, (x, top), (x + tag_w - 1, top + tag_h - 1), (245, 245, 245), -1)
            cv2.rectangle(
                image,
                (x + 15 * scale, top + 10 * scale),
                (x + 54 * scale, top + 19 * scale),
                (40, 40, 40),
                -1,
            )
    rows, unassigned = detect_tags(image, "img", work_width=1600)
    assert unassigned == []
    assert len(rows) == 3
    expected_intercepts = (630, 1330, 2030)
    for row, expected_intercept in zip(rows, expected_intercepts, strict=True):
        assert len(row.tags) == 6
        assert row.intercept == pytest.approx(expected_intercept, abs=3)
    for row_index, top in enumerate(tag_rows_y):
        for i, tag in enumerate(rows[row_index].tags):
            expected_x1 = tag_x0 + tag_dx * i
            expected_box = (expected_x1, top, expected_x1 + tag_w, top + tag_h)
            for actual, expected in zip(tag.box, expected_box, strict=True):
                assert abs(actual - expected) <= 3
