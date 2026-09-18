"""Unit tests for plancheck/grid.py (FEAT-565, Module 4)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # → ``import plancheck``

from plancheck.grid import (
    build_slots,
    row_pitch,
    strip_box,
    to_strip_norm,
)
from plancheck.models import Box, Slot, Tag, TagRow

# Layout constants from conftest.py
IMAGE = (1600, 1200)
TAG_W, TAG_H, TAG_X0, TAG_DX = 70, 30, 150, 220
TAG_ROWS_Y = (300, 650, 1000)
TAGS_PER_ROW = 6


def _tag(image_id: str, row: int, position: int, left: int, top: int, width: int = TAG_W, height: int = TAG_H) -> Tag:
    """Create a Tag with the given geometry."""
    return Tag(
        tag_id=f"{image_id}_r{row:02d}_p{position:02d}",
        image_id=image_id,
        row=row,
        position=position,
        box=(left, top, left + width, top + height),
        crop_box=(left, top, left + width, top + height),
        rectangularity=1.0,
    )


def _row(
    image_id: str,
    row: int,
    lefts: list[int],
    top: int,
    width: int = TAG_W,
    height: int = TAG_H,
    slope: float = 0.0,
    intercept: float | None = None,
) -> TagRow:
    """Create a TagRow with tags at the given left positions."""
    tags = [_tag(image_id, row, i + 1, left, top, width, height) for i, left in enumerate(lefts)]
    # Intercept is the y-coordinate of the line through tag centres
    if intercept is None:
        intercept = top + height / 2
    return TagRow(
        image_id=image_id,
        row=row,
        slope=slope,
        intercept=intercept,
        tags=tags,
    )


def _full_rows(image_id: str = "img", width: int = TAG_W, height: int = TAG_H) -> list[TagRow]:
    """Three full rows of 6 tags each (standard fixture)."""
    rows = []
    for r, top in enumerate(TAG_ROWS_Y, start=1):
        lefts = [TAG_X0 + TAG_DX * i for i in range(TAGS_PER_ROW)]
        rows.append(_row(image_id, r, lefts, top, width=width, height=height))
    return rows


def test_row_pitch() -> None:
    """row_pitch returns median centre-to-centre distance."""
    # Full row → 220.0
    rows = _full_rows()
    assert row_pitch(rows[0]) == 220.0

    # One tag → 0.0
    single = _row("img", 1, [TAG_X0], TAG_ROWS_Y[0])
    assert row_pitch(single) == 0.0

    # Row with one 440 hole among 220 gaps → 220.0 (median)
    lefts = [TAG_X0, TAG_X0 + TAG_DX, TAG_X0 + 3 * TAG_DX, TAG_X0 + 4 * TAG_DX, TAG_X0 + 5 * TAG_DX]
    row = _row("img", 1, lefts, TAG_ROWS_Y[0])
    assert row_pitch(row) == 220.0


def test_anchored_slot_geometry() -> None:
    """Anchored slots follow clamp/midpoint/row-end rules and top/bottom rules."""
    rows = _full_rows()
    slots = build_slots(rows, IMAGE)

    # 18 slots, all tag_anchored
    assert len(slots) == 18
    assert all(s.origin == "tag_anchored" for s in slots)

    # Check slot IDs
    assert slots[0].slot_id == "img_r01_s01"
    assert slots[5].slot_id == "img_r01_s06"
    assert slots[6].slot_id == "img_r02_s01"
    assert slots[17].slot_id == "img_r03_s06"

    # Row 1: y == (55, 300)
    row1_slots = [s for s in slots if s.row == 1]
    for s in row1_slots:
        assert s.box[1] == 55, f"row 1 top should be 55, got {s.box[1]}"
        assert s.box[3] == 300, f"row 1 bottom should be 300, got {s.box[3]}"

    # Row 2: y == (336, 650)
    row2_slots = [s for s in slots if s.row == 2]
    for s in row2_slots:
        assert s.box[1] == 336, f"row 2 top should be 336, got {s.box[1]}"
        assert s.box[3] == 650, f"row 2 bottom should be 650, got {s.box[3]}"

    # Row 1 interior column cx=405: x within ±1 of (346, 464)
    # cx=405 is the 3rd tag (position index 2): left=185+220*2=625, centre=625+35=660
    # Actually: TAG_X0=150, so lefts are 150, 370, 590, 810, 1030, 1250
    # Centres: 185, 405, 625, 845, 1065, 1285
    # Interior column at cx=405 (2nd tag): midpoints 295/515, clamp 405±59.5
    slot_405 = row1_slots[1]  # 2nd slot, centre at 405
    assert abs(slot_405.box[0] - 346) <= 1, f"expected left ~346, got {slot_405.box[0]}"
    assert abs(slot_405.box[2] - 464) <= 1, f"expected right ~464, got {slot_405.box[2]}"

    # Row-start column: cx=185, x ≈ (140, 244)
    slot_185 = row1_slots[0]
    assert abs(slot_185.box[0] - 140) <= 1, f"expected left ~140, got {slot_185.box[0]}"
    assert abs(slot_185.box[2] - 244) <= 1, f"expected right ~244, got {slot_185.box[2]}"

    # Slots of a row never overlap horizontally
    for row_slots in [row1_slots, row2_slots, [s for s in slots if s.row == 3]]:
        for i in range(len(row_slots) - 1):
            assert row_slots[i].box[2] <= row_slots[i + 1].box[0], f"slots {i} and {i+1} overlap"

    # Wide tags: midpoints win
    wide_rows = _full_rows(width=200)
    wide_slots = build_slots(wide_rows, IMAGE)
    wide_row1 = [s for s in wide_slots if s.row == 1]
    # Interior column cx=405: clamp is ±170, midpoints are 295/515
    # Midpoints win: x = (310, 530) - but wait, let me recalculate
    # With width=200, lefts are still 150, 370, 590, etc.
    # Centres: 250, 470, 690, etc.
    # Actually the centres change: left=150+200/2=250, not 185
    # Let me check: TAG_X0=150, width=200, so centres are 150+100=250, 370+100=470, etc.
    # Midpoint between 250 and 470 is 360, between 470 and 690 is 580
    # Clamp is 470 ± 170 = (300, 640)
    # Midpoints (360, 580) are within clamp, so midpoints win
    # Actually the interior column at index 1 has cx=470
    # left = (250+470)/2 = 360, right = (470+690)/2 = 580
    # clamp: max(360, 470-170) = 360, min(580, 470+170) = 580
    # So x = (360, 580)
    wide_interior = wide_row1[1]
    assert abs(wide_interior.box[0] - 360) <= 1, f"expected left ~360, got {wide_interior.box[0]}"
    assert abs(wide_interior.box[2] - 580) <= 1, f"expected right ~580, got {wide_interior.box[2]}"


def test_gap_fill_integer_pitch() -> None:
    """A 2×pitch hole yields exactly one gap_filled slot."""
    # Drop the 3rd tag of row 2 (distance 440 = 2×220)
    lefts_row2 = [TAG_X0, TAG_X0 + TAG_DX, TAG_X0 + 3 * TAG_DX, TAG_X0 + 4 * TAG_DX, TAG_X0 + 5 * TAG_DX]
    rows = _full_rows()
    rows[1] = _row("img", 2, lefts_row2, TAG_ROWS_Y[1])

    slots = build_slots(rows, IMAGE)

    # Row 2 has 6 slots (5 anchored + 1 gap-filled)
    row2_slots = [s for s in slots if s.row == 2]
    assert len(row2_slots) == 6

    # The 3rd slot is gap_filled
    gap_slot = row2_slots[2]
    assert gap_slot.origin == "gap_filled"
    assert gap_slot.tag_id is None
    assert gap_slot.tag_box is None

    # Centre x ≈ 625 (midpoint between 405 and 845)
    # Actually: lefts are 150, 370, 810, 1030, 1250
    # Centres: 185, 405, 845, 1065, 1285
    # Gap between 405 and 845 is 440 = 2×220
    # Virtual centre at 405 + 220 = 625
    cx = (gap_slot.box[0] + gap_slot.box[2]) / 2
    assert abs(cx - 625) <= 1, f"expected centre ~625, got {cx}"

    # Index is 3 and indexes 1..6 are contiguous
    assert gap_slot.index == 3
    assert [s.index for s in row2_slots] == [1, 2, 3, 4, 5, 6]

    # Y bounds follow the same rule as neighbours (336, 650)
    assert gap_slot.box[1] == 336
    assert gap_slot.box[3] == 650

    # row_pitch of that row is still 220
    assert row_pitch(rows[1]) == 220.0


def test_gap_fill_rejects_ambiguous() -> None:
    """A 1.5×pitch hole yields no gap_filled slot; no slot stretches across it."""
    # lefts [150, 370, 700, 920, 1140] → one distance 330 = 1.5×220
    lefts = [150, 370, 700, 920, 1140]
    row = _row("img", 1, lefts, TAG_ROWS_Y[0])
    slots = build_slots([row], IMAGE)

    # 5 slots, none gap_filled
    assert len(slots) == 5
    assert all(s.origin == "tag_anchored" for s in slots)

    # Slots either side of the hole are clamped to ±0.85*70 of their centre
    # Centres: 185, 405, 735, 955, 1175
    # Gap between 405 and 735 is 330 = 1.5×220 → no gap fill
    # Slot at 405: clamp is 405 ± 59.5 = (345.5, 464.5)
    # Midpoints: (185+405)/2 = 295, (405+735)/2 = 570
    # Clamp wins: max(295, 345.5) = 345.5, min(570, 464.5) = 464.5
    slot_405 = slots[1]
    assert abs(slot_405.box[0] - 346) <= 1, f"expected left ~346, got {slot_405.box[0]}"
    assert abs(slot_405.box[2] - 464) <= 1, f"expected right ~464, got {slot_405.box[2]}"


def test_untagged_bottom_row() -> None:
    """Untagged row synthesized only when ≥ 0.6 pitch remains below last tags."""
    # IMAGE height 1200 → no untagged_row slot (170 < 210)
    rows = _full_rows()
    slots = build_slots(rows, IMAGE)
    assert not any(s.origin == "untagged_row" for s in slots)

    # image_size (1600, 1300) → 6 extra slots, row 4
    slots_1300 = build_slots(rows, (1600, 1300))
    untagged = [s for s in slots_1300 if s.origin == "untagged_row"]
    assert len(untagged) == 6
    assert all(s.row == 4 for s in untagged)
    assert all(s.tag_id is None for s in untagged)
    assert all(s.tag_box is None for s in untagged)

    # y == (1036, 1300)
    for s in untagged:
        assert s.box[1] == 1036, f"expected top 1036, got {s.box[1]}"
        assert s.box[3] == 1300, f"expected bottom 1300, got {s.box[3]}"

    # Same x bounds as row 3's slots
    row3_slots = [s for s in slots_1300 if s.row == 3]
    for i, (u, r3) in enumerate(zip(untagged, row3_slots, strict=False)):
        assert u.box[0] == r3.box[0], f"slot {i+1} left differs"
        assert u.box[2] == r3.box[2], f"slot {i+1} right differs"

    # A single tag row → never synthesizes
    single_row = [_row("img", 1, [TAG_X0 + i * TAG_DX for i in range(6)], TAG_ROWS_Y[0])]
    single_slots = build_slots(single_row, (1600, 1300))
    assert not any(s.origin == "untagged_row" for s in single_slots)

    # A gap-filled last row → the untagged row has the gap-filled column too
    lefts_row3 = [TAG_X0, TAG_X0 + TAG_DX, TAG_X0 + 3 * TAG_DX, TAG_X0 + 4 * TAG_DX, TAG_X0 + 5 * TAG_DX]
    rows_gap = _full_rows()
    rows_gap[2] = _row("img", 3, lefts_row3, TAG_ROWS_Y[2])
    slots_gap = build_slots(rows_gap, (1600, 1300))
    untagged_gap = [s for s in slots_gap if s.origin == "untagged_row"]
    assert len(untagged_gap) == 6  # Still 6 slots (5 anchored + 1 gap-filled)


def test_to_strip_norm() -> None:
    """to_strip_norm returns [ymin, xmin, ymax, xmax] in 0-1000."""
    strip: Box = (100, 200, 1100, 700)
    box: Box = (100, 200, 600, 450)

    # Normal conversion
    result = to_strip_norm(box, strip)
    # strip: x in [100, 1100] (width 1000), y in [200, 700] (height 500)
    # box: x in [100, 600] → (100-100)/1000 = 0, (600-100)/1000 = 0.5 → 0, 500
    #      y in [200, 450] → (200-200)/500 = 0, (450-200)/500 = 0.5 → 0, 500
    assert result == [0, 0, 500, 500]

    # Box equal to strip → [0, 0, 1000, 1000]
    assert to_strip_norm(strip, strip) == [0, 0, 1000, 1000]

    # Box poking outside is clipped to 0..1000
    outside: Box = (50, 150, 1200, 800)
    result_out = to_strip_norm(outside, strip)
    # x: (50-100)/1000 = -0.05 → clipped to 0, (1200-100)/1000 = 1.1 → clipped to 1000
    # y: (150-200)/500 = -0.1 → clipped to 0, (800-200)/500 = 1.2 → clipped to 1000
    assert result_out == [0, 0, 1000, 1000]

    # Degenerate strip → ValueError
    with pytest.raises(ValueError, match="degenerate"):
        to_strip_norm(box, (100, 200, 100, 700))  # zero width


def test_strip_box_contains_slots_and_tags() -> None:
    """strip_box contains every slot.box and tag_box, is clipped to IMAGE."""
    rows = _full_rows()
    slots = build_slots(rows, IMAGE)

    # Slots of row 2
    row2_slots = [s for s in slots if s.row == 2]
    strip = strip_box(row2_slots, IMAGE)

    # Strip contains every slot.box
    for s in row2_slots:
        assert strip[0] <= s.box[0] and s.box[2] <= strip[2], f"slot {s.slot_id} x not in strip"
        assert strip[1] <= s.box[1] and s.box[3] <= strip[3], f"slot {s.slot_id} y not in strip"

    # Strip contains every tag_box
    for s in row2_slots:
        if s.tag_box:
            assert strip[0] <= s.tag_box[0] and s.tag_box[2] <= strip[2], f"tag {s.slot_id} x not in strip"
            assert strip[1] <= s.tag_box[1] and s.tag_box[3] <= strip[3], f"tag {s.slot_id} y not in strip"

    # Strip is clipped to IMAGE
    assert 0 <= strip[0] <= IMAGE[0]
    assert 0 <= strip[1] <= IMAGE[1]
    assert 0 <= strip[2] <= IMAGE[0]
    assert 0 <= strip[3] <= IMAGE[1]

    # Strip grows with pad
    strip_padded = strip_box(row2_slots, IMAGE, pad=0.1)
    assert strip_padded[0] <= strip[0]
    assert strip_padded[1] <= strip[1]
    assert strip_padded[2] >= strip[2]
    assert strip_padded[3] >= strip[3]

    # Empty slots → ValueError
    with pytest.raises(ValueError, match="needs at least one slot"):
        strip_box([], IMAGE)
