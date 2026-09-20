"""Slot geometry with pluggable anchoring rules (FEAT-574). Pure and picklable."""

from __future__ import annotations

import math
from enum import Enum
from statistics import median
from typing import List, Optional, Sequence, Tuple

import numpy as np

from parrot.models.detections import DetectionBox  # verified: detections.py:37

from ..contracts import Slot
from .profiles import ShapeCandidate

END_HALF_WIDTH = 0.65  # row-end half width, in median anchor widths   (ref grid.py:16)
CLAMP_HALF_WIDTH = 0.85  # never stretch a slot further than this        (ref grid.py:17)
TOP_OFFSET = 0.7  # see ref grid.py:18
GAP_TOLERANCE = 0.25  # |d/pitch - k| allowed for gap filling         (ref grid.py:19)
UNTAGGED_MIN_PITCH = 0.6  # ref grid.py:20
FIRST_ROW_GAP_FALLBACK = 0.2  # ref grid.py:21

_Line = Tuple[float, float]  # (slope, intercept) through anchor centres


class AnchorRule(str, Enum):
    """How a slot is derived from its anchor shape."""

    TAG_BELOW_PRODUCT = "tag_below_product"
    SHAPE_IS_SLOT = "shape_is_slot"


def candidate_shape_id(image_id: str, candidate: ShapeCandidate) -> str:
    """Deterministic id of a candidate: ``"<image_id>:<profile>:<x1>-<y1>-<x2>-<y2>"``."""
    return f"{image_id}:{candidate.profile}:{candidate.x1}-{candidate.y1}-{candidate.x2}-{candidate.y2}"


def _cx(c: ShapeCandidate) -> float:
    """x-centre of a candidate."""
    return (c.x1 + c.x2) / 2.0


def _fit_line(row: Sequence[ShapeCandidate]) -> _Line:
    """Least-squares line through the anchor centres (flat through the centre for one anchor)."""
    xs = [_cx(c) for c in row]
    ys = [(c.y1 + c.y2) / 2.0 for c in row]
    if len(row) < 2 or max(xs) - min(xs) <= 0:
        return 0.0, float(median(ys))
    slope, intercept = np.polyfit(xs, ys, 1)
    return float(slope), float(intercept)


def _line_y(line: _Line, x: float) -> float:
    """Evaluate a row line at ``x``."""
    return line[0] * x + line[1]


def _row_pitch(row: Sequence[ShapeCandidate]) -> float:
    """Median centre-to-centre distance of consecutive anchors; 0.0 with fewer than two."""
    centres = [_cx(c) for c in row]
    gaps = [b - a for a, b in zip(centres, centres[1:], strict=False)]
    return float(median(gaps)) if gaps else 0.0


def _columns(row: Sequence[ShapeCandidate], fill_gaps: bool) -> List[Tuple[float, Optional[ShapeCandidate]]]:
    """Column centres left→right: real anchors plus virtual centres for unambiguous holes."""
    pitch = _row_pitch(row)
    columns: List[Tuple[float, Optional[ShapeCandidate]]] = []
    for position, anchor in enumerate(row):
        if fill_gaps and position and pitch > 0:
            previous = _cx(row[position - 1])
            distance = _cx(anchor) - previous
            k = round(distance / pitch)
            if k >= 2 and abs(distance / pitch - k) <= GAP_TOLERANCE:
                for j in range(1, k):
                    columns.append((previous + j * distance / k, None))
        columns.append((_cx(anchor), anchor))
    return columns


def _x_bounds(centres: Sequence[float], j: int, median_width: float) -> Tuple[float, float]:
    """Neighbour midpoints, row-end half widths, then the ±CLAMP_HALF_WIDTH clamp."""
    cx = centres[j]
    left = (centres[j - 1] + cx) / 2 if j else cx - END_HALF_WIDTH * median_width
    right = (centres[j + 1] + cx) / 2 if j + 1 < len(centres) else cx + END_HALF_WIDTH * median_width
    return max(left, cx - CLAMP_HALF_WIDTH * median_width), min(right, cx + CLAMP_HALF_WIDTH * median_width)


def _clip(
    box: Tuple[float, float, float, float], image_size: Tuple[int, int], confidence: float
) -> Optional[DetectionBox]:
    """Round, clip to the image; ``None`` for a degenerate box."""
    width, height = image_size
    x1, y1 = max(0, round(box[0])), max(0, round(box[1]))
    x2, y2 = min(width, round(box[2])), min(height, round(box[3]))
    if x1 >= x2 or y1 >= y2:
        return None
    return DetectionBox(x1=x1, y1=y1, x2=x2, y2=y2, confidence=max(0.0, min(1.0, confidence)))


def _slot(image_id: str, row_index: int, slot_index: int, box: DetectionBox, anchor_id: Optional[str]) -> Slot:
    """Build a cycle Slot with the id convention of this module."""
    return Slot(
        slot_id=f"{image_id}:r{row_index}:s{slot_index}",
        image_id=image_id,
        row_index=row_index,
        slot_index=slot_index,
        box=box,
        anchor_shape_id=anchor_id,
        inferred=anchor_id is None,
    )


def build_slots(
    rows: Sequence[Sequence[ShapeCandidate]],
    image_size: Tuple[int, int],
    *,
    image_id: str,
    rule: AnchorRule,
    fill_gaps: bool = True,
    untagged_bottom_row: bool = False,
) -> List[Slot]:
    """Build every slot of one image. Reference: plancheck/grid.py:78.

    Args:
        rows: Visible rows top→bottom (``group_rows`` output), candidates left→right.
        image_size: ``(width, height)`` of the source image.
        image_id: Id of the image (slot ids and anchor ids).
        rule: How a slot derives from its anchor.
        fill_gaps: Insert inferred slots for unambiguous holes (``TAG_BELOW_PRODUCT`` only).
        untagged_bottom_row: Synthesize a last row below the last anchored row when room remains
            (``TAG_BELOW_PRODUCT`` only).

    Returns:
        Slots ordered by row then left→right. ``slot_index`` is 1..n per row after gap filling;
        gap-filled and synthesized bottom-row slots have ``inferred=True`` and no anchor.
        Degenerate boxes are skipped.
    """
    width, height = image_size
    slots: List[Slot] = []
    if rule == AnchorRule.SHAPE_IS_SLOT:
        for row_index, row in enumerate(rows):
            index = 0
            for candidate in sorted(row, key=lambda c: (_cx(c), c.y1)):
                box = _clip((candidate.x1, candidate.y1, candidate.x2, candidate.y2), image_size, candidate.score)
                if box is None:
                    continue
                index += 1
                slots.append(_slot(image_id, row_index, index, box, candidate_shape_id(image_id, candidate)))
        return slots

    lines = [_fit_line(row) if row else None for row in rows]
    anchored = [r for r, row in enumerate(rows) if row]
    last_columns: List[Tuple[float, float, float]] = []
    for r, row in enumerate(rows):
        if not row:
            continue
        line = lines[r]
        columns = _columns(row, fill_gaps)
        centres = [cx for cx, _ in columns]
        median_width = float(median(c.x2 - c.x1 for c in row))
        median_height = float(median(c.y2 - c.y1 for c in row))
        last_columns = []
        index = 0
        for j, (cx, anchor) in enumerate(columns):
            left, right = _x_bounds(centres, j, median_width)
            last_columns.append((cx, left, right))
            anchor_height = float(anchor.y2 - anchor.y1) if anchor else median_height
            bottom = float(anchor.y1) if anchor else _line_y(line, cx) - anchor_height / 2
            previous = next((lines[p] for p in range(r - 1, -1, -1) if lines[p] is not None), None)
            if previous is not None:
                top = _line_y(previous, cx) + TOP_OFFSET * anchor_height
            else:
                following = next((lines[p] for p in range(r + 1, len(rows)) if lines[p] is not None), None)
                row_gap = (
                    _line_y(following, cx) - _line_y(line, cx)
                    if following is not None
                    else FIRST_ROW_GAP_FALLBACK * height
                )
                top = bottom - TOP_OFFSET * row_gap
            box = _clip((left, top, right, bottom), image_size, anchor.score if anchor else 0.0)
            if box is None:
                continue
            index += 1
            anchor_id = candidate_shape_id(image_id, anchor) if anchor else None
            slots.append(_slot(image_id, r, index, box, anchor_id))

    if untagged_bottom_row and len(anchored) >= 2 and last_columns:
        xc = width / 2
        pitches = [
            _line_y(lines[b], xc) - _line_y(lines[a], xc)  # type: ignore[arg-type]
            for a, b in zip(anchored, anchored[1:], strict=False)
        ]
        vertical_pitch = float(median(pitches))
        last = anchored[-1]
        last_line = lines[last]
        max_bottom = max(c.y2 for c in rows[last])
        if vertical_pitch > 0 and height - max_bottom >= UNTAGGED_MIN_PITCH * vertical_pitch:
            median_height = float(median(c.y2 - c.y1 for c in rows[last]))
            new_row = len(rows)
            index = 0
            for cx, left, right in last_columns:
                top = _line_y(last_line, cx) + TOP_OFFSET * median_height  # type: ignore[arg-type]
                bottom = min(float(height), _line_y(last_line, cx) - median_height / 2 + vertical_pitch)  # type: ignore[arg-type]
                box = _clip((left, top, right, bottom), image_size, 0.0)
                if box is None:
                    continue
                index += 1
                slots.append(_slot(image_id, new_row, index, box, None))
    return slots


def strip_box(slots: Sequence[Slot], image_size: Tuple[int, int], pad: float = 0.04) -> DetectionBox:
    """Padded, clipped union of ONE row's slots. Raises ValueError when ``slots`` is empty.

    Args:
        slots: Slots of one row.
        image_size: ``(width, height)`` of the source image.
        pad: Padding per side, as a fraction of the union's width (x) and height (y).

    Returns:
        The strip box (``confidence=1.0``).
    """
    if not slots:
        raise ValueError("strip_box needs at least one slot")
    width, height = image_size
    x1 = min(s.box.x1 for s in slots)
    y1 = min(s.box.y1 for s in slots)
    x2 = max(s.box.x2 for s in slots)
    y2 = max(s.box.y2 for s in slots)
    pad_x, pad_y = pad * (x2 - x1), pad * (y2 - y1)
    return DetectionBox(
        x1=max(0, round(x1 - pad_x)),
        y1=max(0, round(y1 - pad_y)),
        x2=min(width, round(x2 + pad_x)),
        y2=min(height, round(y2 + pad_y)),
        confidence=1.0,
    )


def to_strip_norm(box: DetectionBox, strip: DetectionBox) -> List[int]:
    """[ymin, xmin, ymax, xmax] in 0-1000 relative to the strip (rounded, clipped).

    Raises:
        ValueError: degenerate strip (zero width or height).
    """
    strip_w, strip_h = strip.x2 - strip.x1, strip.y2 - strip.y1
    if strip_w <= 0 or strip_h <= 0:
        raise ValueError("degenerate strip")

    def norm(value: float, origin: int, size: int) -> int:
        return max(0, min(1000, round(1000 * (value - origin) / size)))

    return [
        norm(box.y1, strip.y1, strip_h),
        norm(box.x1, strip.x1, strip_w),
        norm(box.y2, strip.y1, strip_h),
        norm(box.x2, strip.x1, strip_w),
    ]


def from_strip_norm(norm: Sequence[int], strip: DetectionBox) -> DetectionBox:
    """Inverse of to_strip_norm, into SOURCE-image pixels. Raises ValueError on non-finite/out-of-range.

    Args:
        norm: ``[ymin, xmin, ymax, xmax]`` in 0..1000 relative to ``strip``.
        strip: The strip the coordinates are relative to.

    Returns:
        The box in source pixels, clipped to the strip (``confidence=1.0``).
    """
    if len(norm) != 4:
        raise ValueError(f"expected 4 values, got {len(norm)}")
    values: List[float] = []
    for value in norm:
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"non-numeric strip coordinate: {value!r}") from exc
        if not math.isfinite(number) or not 0 <= number <= 1000:
            raise ValueError(f"strip coordinate out of range: {value!r}")
        values.append(number)
    ymin, xmin, ymax, xmax = values
    if ymax <= ymin or xmax <= xmin:
        raise ValueError(f"inverted or empty strip box: {list(norm)}")
    strip_w, strip_h = strip.x2 - strip.x1, strip.y2 - strip.y1
    if strip_w <= 0 or strip_h <= 0:
        raise ValueError("degenerate strip")
    x1 = strip.x1 + round(xmin / 1000 * strip_w)
    x2 = strip.x1 + round(xmax / 1000 * strip_w)
    y1 = strip.y1 + round(ymin / 1000 * strip_h)
    y2 = strip.y1 + round(ymax / 1000 * strip_h)
    x1, x2 = max(strip.x1, min(x1, strip.x2)), max(strip.x1, min(x2, strip.x2))
    y1, y2 = max(strip.y1, min(y1, strip.y2)), max(strip.y1, min(y2, strip.y2))
    if x2 <= x1 or y2 <= y1:
        raise ValueError("strip box collapses to zero size")
    return DetectionBox(x1=x1, y1=y1, x2=x2, y2=y2, confidence=1.0)
