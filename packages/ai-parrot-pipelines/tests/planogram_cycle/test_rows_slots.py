"""Offline tests for row grouping, shelf edges and slot geometry."""

import math
import pickle

import cv2
import numpy as np
import pytest

from parrot.models.detections import DetectionBox
from parrot_pipelines.planogram.perception.profiles import ShapeCandidate
from parrot_pipelines.planogram.perception.rows import detect_shelf_edges, group_rows
from parrot_pipelines.planogram.perception.slots import (
    AnchorRule,
    build_slots,
    candidate_shape_id,
    from_strip_norm,
    strip_box,
    to_strip_norm,
)

W, H = 2000, 1500
ROW_Y = (400, 800, 1200)
PITCH = 220


def _tag(x: int, y: int, w: int = 120, h: int = 50) -> ShapeCandidate:
    return ShapeCandidate(profile="price_tag", kind="price_tag", x1=x, y1=y, x2=x + w, y2=y + h, score=0.9)


def _tag_rows(n_rows: int = 3, n_cols: int = 8, skip: tuple[int, int] | None = None) -> list[ShapeCandidate]:
    """Grid of tags with a slight slope and jittered sizes; ``skip=(row, col)`` leaves a gap."""
    tags = []
    for r in range(n_rows):
        for c in range(n_cols):
            if skip == (r, c):
                continue
            x = 150 + c * PITCH
            y = ROW_Y[r] + int(0.03 * x)  # slope 0.03
            tags.append(_tag(x, y, w=120 + (c % 3) * 6, h=50 + (c % 2) * 4))
    return tags


def test_group_rows_orders_rows_and_items():  # AC-1
    """3 rows x 8 tags ⇒ 3 rows top→bottom, items left→right; strays are in no row."""
    tags = _tag_rows()
    strays = [_tag(1900, 100, 40, 200), _tag(60, 1450, 30, 30), _tag(1000, 600, 300, 20)]
    rows = group_rows(list(reversed(tags)) + strays, W)
    assert len(rows) == 3
    assert [len(r) for r in rows] == [8, 8, 8]
    assert [r[0].y1 for r in rows] == sorted(r[0].y1 for r in rows)
    for row in rows:
        assert [c.x1 for c in row] == sorted(c.x1 for c in row)
    in_rows = {id(c) for row in rows for c in row}
    assert all(id(s) not in in_rows for s in strays)


def test_group_rows_rejects_short_or_sparse_rows():  # AC-2
    """Too few candidates ⇒ []; a row spanning < 25 % of the width is rejected."""
    assert group_rows(_tag_rows(n_rows=1, n_cols=3), W) == []
    narrow = [_tag(100 + i * 60, 500, w=50) for i in range(6)]  # span ~300 px < 500 px
    assert group_rows(narrow, W) == []


def test_group_rows_and_gap_filled_slots():  # AC-3 (spec §4 name)
    """A missing tag becomes one inferred, anchor-less slot when fill_gaps is on."""
    rows = group_rows(_tag_rows(skip=(1, 3)), W)
    assert [len(r) for r in rows] == [8, 7, 8]
    filled = build_slots(rows, (W, H), image_id="img", rule=AnchorRule.TAG_BELOW_PRODUCT)
    middle = [s for s in filled if s.row_index == 1]
    assert [s.slot_index for s in middle] == list(range(1, 9))
    inferred = [s for s in middle if s.inferred]
    assert len(inferred) == 1 and inferred[0].anchor_shape_id is None and inferred[0].slot_index == 4
    assert inferred[0].slot_id == "img:r1:s4"
    unfilled = build_slots(rows, (W, H), image_id="img", rule=AnchorRule.TAG_BELOW_PRODUCT, fill_gaps=False)
    assert len([s for s in unfilled if s.row_index == 1]) == 7


def test_anchored_slots_sit_above_their_tags():  # AC-4
    """Every anchored slot ends at (or above) its tag's top edge and lies inside the image."""
    rows = group_rows(_tag_rows(), W)
    by_id = {candidate_shape_id("img", c): c for row in rows for c in row}
    slots = build_slots(rows, (W, H), image_id="img", rule=AnchorRule.TAG_BELOW_PRODUCT)
    assert len(slots) == 24
    for slot in slots:
        tag = by_id[slot.anchor_shape_id]
        assert slot.box.y2 <= tag.y1 + 1
        assert 0 <= slot.box.x1 < slot.box.x2 <= W and 0 <= slot.box.y1 < slot.box.y2 <= H
        assert slot.box.confidence == pytest.approx(tag.score)


def test_untagged_bottom_row_only_with_room():  # AC-5
    """A synthesized last row appears only when enough vertical room remains below the last tag row."""
    rows = group_rows(_tag_rows(n_rows=2), W)  # rows at ~400 and ~800; plenty of room below
    slots = build_slots(rows, (W, H), image_id="img", rule=AnchorRule.TAG_BELOW_PRODUCT, untagged_bottom_row=True)
    bottom = [s for s in slots if s.row_index == 2]
    assert len(bottom) == 8 and all(s.inferred and s.anchor_shape_id is None for s in bottom)

    tight = group_rows(_tag_rows(n_rows=3), W)  # last row near 1200 + slope; < 0.6 pitch remains
    slots = build_slots(tight, (W, H), image_id="img", rule=AnchorRule.TAG_BELOW_PRODUCT, untagged_bottom_row=True)
    assert not [s for s in slots if s.row_index == 3]


def test_shape_is_slot_rule():  # AC-6
    """SHAPE_IS_SLOT: one slot per candidate, same box, anchored to the candidate id."""
    rows = group_rows(_tag_rows(), W)
    slots = build_slots(rows, (W, H), image_id="img", rule=AnchorRule.SHAPE_IS_SLOT, untagged_bottom_row=True)
    assert len(slots) == 24
    for slot, candidate in zip(slots, [c for row in rows for c in row], strict=True):
        assert (slot.box.x1, slot.box.y1, slot.box.x2, slot.box.y2) == (
            candidate.x1,
            candidate.y1,
            candidate.x2,
            candidate.y2,
        )
        assert slot.anchor_shape_id == candidate_shape_id("img", candidate)
        assert not slot.inferred


def test_strip_norm_roundtrip_and_bounds():  # AC-7 (spec §4 name)
    """from_strip_norm(to_strip_norm(b)) is within ±2 px for boxes inside the strip."""
    strip = DetectionBox(x1=137, y1=412, x2=1811, y2=733, confidence=1.0)
    for box in (
        DetectionBox(x1=150, y1=420, x2=300, y2=700, confidence=1.0),
        DetectionBox(x1=900, y1=500, x2=1810, y2=733, confidence=1.0),
    ):
        back = from_strip_norm(to_strip_norm(box, strip), strip)
        for got, want in zip((back.x1, back.y1, back.x2, back.y2), (box.x1, box.y1, box.x2, box.y2), strict=True):
            assert abs(got - want) <= 2
    with pytest.raises(ValueError):
        to_strip_norm(strip, DetectionBox(x1=10, y1=10, x2=10, y2=50, confidence=1.0))


@pytest.mark.parametrize("bad", [[0, 0, 10], [0, 0, math.nan, 10], [0, 0, 1001, 10], [500, 0, 100, 10]])
def test_from_strip_norm_rejects_invalid(bad):
    strip = DetectionBox(x1=0, y1=0, x2=1000, y2=500, confidence=1.0)
    with pytest.raises(ValueError):
        from_strip_norm(bad, strip)


def test_strip_box_empty_raises_and_clips():  # AC-8
    """Empty input raises; the padded union is clipped to the image."""
    with pytest.raises(ValueError):
        strip_box([], (W, H))
    rows = group_rows(_tag_rows(), W)
    slots = build_slots(rows, (W, H), image_id="img", rule=AnchorRule.SHAPE_IS_SLOT)
    edge_row = [s.model_copy(update={"box": DetectionBox(x1=0, y1=0, x2=W, y2=60, confidence=1.0)}) for s in slots[:2]]
    strip = strip_box(edge_row, (W, H))
    assert (strip.x1, strip.y1, strip.x2) == (0, 0, W) and strip.confidence == 1.0
    top_row = [s for s in slots if s.row_index == 0]
    padded = strip_box(top_row, (W, H))
    assert padded.x1 < min(s.box.x1 for s in top_row) and padded.x2 > max(s.box.x2 for s in top_row)


def test_detect_shelf_edges_synthetic_and_blank():  # AC-9
    """Three drawn shelf lines are found (±3 px); a blank image yields []."""
    image = np.full((H, W, 3), 90, np.uint8)
    for y in (500, 900, 1300):
        cv2.line(image, (100, y), (1900, y), (230, 230, 230), 3)
    edges = detect_shelf_edges(image)
    assert len(edges) == 3
    for y in (500, 900, 1300):
        assert any(abs(e - y) <= 3 for e in edges)
    assert edges == sorted(set(edges))
    assert detect_shelf_edges(np.full((H, W, 3), 90, np.uint8)) == []
    with pytest.raises(ValueError):
        detect_shelf_edges("not an image")


def test_public_functions_are_picklable():  # AC-10
    for fn in (group_rows, detect_shelf_edges, build_slots, strip_box, to_strip_norm, from_strip_norm):
        pickle.dumps(fn)
