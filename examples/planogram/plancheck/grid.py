"""Slot grid derived from price-tag rows: anchored, gap-filled and untagged-row slots (FEAT-565).

Pure geometry over ``TagRow``/``Slot`` models in ORIGINAL image pixels. No image access, no I/O.
Tags sit BELOW their products, so a slot spans from the previous row's line down to its own tag's top.
"""

from __future__ import annotations

import logging
from statistics import median

from .models import Box, Slot, Tag, TagRow

logger = logging.getLogger(__name__)

END_HALF_WIDTH = 0.65  # row-end half width, in median tag widths
CLAMP_HALF_WIDTH = 0.85  # never stretch a slot further than this from its centre
TOP_OFFSET = 0.7  # fraction of tag height below the previous row line / of the row gap above the first row
GAP_TOLERANCE = 0.25  # |d/pitch - k| allowed for gap filling
UNTAGGED_MIN_PITCH = 0.6  # fraction of the vertical row pitch that must remain below the last tag row
FIRST_ROW_GAP_FALLBACK = 0.2  # fraction of image height when there is a single tag row


def _cx(tag: Tag) -> float:
    """Return the x-centre of a tag's box."""
    return (tag.box[0] + tag.box[2]) / 2


def _line_y(row: TagRow, x: float) -> float:
    """Row line (through tag centres) evaluated at ``x``."""
    return row.slope * x + row.intercept


def row_pitch(row: TagRow) -> float:
    """Median centre-to-centre distance of consecutive tags (original pixels); ``0.0`` with fewer than two tags."""
    centres = [_cx(tag) for tag in row.tags]
    gaps = [b - a for a, b in zip(centres, centres[1:], strict=False)]
    return float(median(gaps)) if gaps else 0.0


def _columns(row: TagRow) -> list[tuple[float, Tag | None]]:
    """Centres of the row's columns left→right: real tags plus virtual centres for unambiguous holes.

    Returns:
        ``[(cx, tag_or_None), ...]`` — ``None`` marks a gap-filled (virtual) column.
    """
    pitch = row_pitch(row)
    columns: list[tuple[float, Tag | None]] = []
    for position, tag in enumerate(row.tags):
        if position and pitch > 0:
            previous = _cx(row.tags[position - 1])
            distance = _cx(tag) - previous
            k = round(distance / pitch)
            if k >= 2 and abs(distance / pitch - k) <= GAP_TOLERANCE:
                # Insert k-1 virtual columns evenly spaced
                for j in range(1, k):
                    columns.append((previous + j * distance / k, None))
        columns.append((_cx(tag), tag))
    return columns


def _x_bounds(centres: list[float], j: int, median_width: float) -> tuple[float, float]:
    """Horizontal bounds of column ``j``: neighbour midpoints, row-end half widths, then the ±0.85 clamp."""
    cx = centres[j]
    left = (centres[j - 1] + cx) / 2 if j else cx - END_HALF_WIDTH * median_width
    right = (centres[j + 1] + cx) / 2 if j + 1 < len(centres) else cx + END_HALF_WIDTH * median_width
    return max(left, cx - CLAMP_HALF_WIDTH * median_width), min(right, cx + CLAMP_HALF_WIDTH * median_width)


def _clip(box: tuple[float, float, float, float], image_size: tuple[int, int]) -> Box | None:
    """Round, clip to the image, and return ``None`` for a degenerate box."""
    width, height = image_size
    x1, y1 = max(0, round(box[0])), max(0, round(box[1]))
    x2, y2 = min(width, round(box[2])), min(height, round(box[3]))
    return (x1, y1, x2, y2) if x1 < x2 and y1 < y2 else None


def build_slots(rows: list[TagRow], image_size: tuple[int, int]) -> list[Slot]:
    """Build every slot of one image: tag-anchored, gap-filled, then the untagged bottom row.

    Args:
        rows: Tag rows top→bottom (as returned by detection), coordinates in original pixels.
        image_size: ``(width, height)`` of the original image.

    Returns:
        Slots ordered by row then left→right. ``index`` is 1-based within the row after gap filling;
        the synthesized row number is ``last row + 1``. Degenerate boxes are skipped.
    """
    width, height = image_size
    slots: list[Slot] = []
    last_columns: list[tuple[float, float, float]] = []  # (cx, left, right) of the last tag row
    rows_with_tags = [row for row in rows if row.tags]

    for r, row in enumerate(rows):
        if not row.tags:
            continue
        columns = _columns(row)
        centres = [cx for cx, _ in columns]
        median_width = float(median(tag.box[2] - tag.box[0] for tag in row.tags))
        median_height = float(median(tag.box[3] - tag.box[1] for tag in row.tags))
        last_columns = []
        index = 0
        for j, (cx, tag) in enumerate(columns):
            left, right = _x_bounds(centres, j, median_width)
            last_columns.append((cx, left, right))
            tag_height = float(tag.box[3] - tag.box[1]) if tag else median_height
            bottom = float(tag.box[1]) if tag else _line_y(row, cx) - tag_height / 2

            # Compute top
            if r > 0:
                # Previous row exists
                prev_row = rows[r - 1]
                top = _line_y(prev_row, cx) + TOP_OFFSET * tag_height
            else:
                # First row
                if len(rows) > 1:
                    row_gap = _line_y(rows[1], cx) - _line_y(row, cx)
                else:
                    row_gap = FIRST_ROW_GAP_FALLBACK * height
                top = bottom - TOP_OFFSET * row_gap

            box = _clip((left, top, right, bottom), image_size)
            if box is None:
                logger.debug("degenerate slot at row %d column %d", row.row, j)
                continue
            index += 1
            slots.append(
                Slot(
                    slot_id=f"{row.image_id}_r{row.row:02d}_s{index:02d}",
                    image_id=row.image_id,
                    row=row.row,
                    index=index,
                    box=box,
                    tag_id=tag.tag_id if tag else None,
                    tag_box=tag.box if tag else None,
                    origin="tag_anchored" if tag else "gap_filled",
                )
            )

    # Untagged bottom row
    if len(rows_with_tags) >= 2:
        last_row = rows_with_tags[-1]
        # Compute vertical row pitch at image centre
        xc = width / 2
        row_pitch_v = float(
            median(
                [
                    _line_y(rows_with_tags[i + 1], xc) - _line_y(rows_with_tags[i], xc)
                    for i in range(len(rows_with_tags) - 1)
                ]
            )
        )
        # Remaining space below last row
        max_bottom = max(tag.box[3] for tag in last_row.tags)
        remaining = height - max_bottom
        if remaining >= UNTAGGED_MIN_PITCH * row_pitch_v:
            median_height = float(median(tag.box[3] - tag.box[1] for tag in last_row.tags))
            new_row = last_row.row + 1
            index = 0
            for cx, left, right in last_columns:
                top = _line_y(last_row, cx) + TOP_OFFSET * median_height
                bottom = min(height, _line_y(last_row, cx) - median_height / 2 + row_pitch_v)
                box = _clip((left, top, right, bottom), image_size)
                if box is None:
                    logger.debug("degenerate untagged slot at column %d", len(slots))
                    continue
                index += 1
                slots.append(
                    Slot(
                        slot_id=f"{last_row.image_id}_r{new_row:02d}_s{index:02d}",
                        image_id=last_row.image_id,
                        row=new_row,
                        index=index,
                        box=box,
                        tag_id=None,
                        tag_box=None,
                        origin="untagged_row",
                    )
                )

    logger.info("built %d slots from %d tag rows", len(slots), len(rows))
    return slots


def strip_box(slots: list[Slot], image_size: tuple[int, int], pad: float = 0.04) -> Box:
    """Bounding box of one row's slots and their tags, padded and clipped to the image.

    Args:
        slots: Slots of ONE row (non-empty).
        image_size: ``(width, height)`` of the original image.
        pad: Padding per side as a fraction of the union's width (x) and height (y).

    Raises:
        ValueError: ``slots`` is empty.
    """
    if not slots:
        raise ValueError("strip_box needs at least one slot")

    width, height = image_size

    # Union of all slot boxes and tag boxes
    x1 = min(s.box[0] for s in slots)
    y1 = min(s.box[1] for s in slots)
    x2 = max(s.box[2] for s in slots)
    y2 = max(s.box[3] for s in slots)

    # Include tag boxes if present
    for s in slots:
        if s.tag_box:
            x1 = min(x1, s.tag_box[0])
            y1 = min(y1, s.tag_box[1])
            x2 = max(x2, s.tag_box[2])
            y2 = max(y2, s.tag_box[3])

    # Apply padding
    union_width = x2 - x1
    union_height = y2 - y1
    pad_x = pad * union_width
    pad_y = pad * union_height

    x1 = max(0, round(x1 - pad_x))
    y1 = max(0, round(y1 - pad_y))
    x2 = min(width, round(x2 + pad_x))
    y2 = min(height, round(y2 + pad_y))

    return (x1, y1, x2, y2)


def to_strip_norm(box: Box, strip: Box) -> list[int]:
    """Convert an original-pixel box to ``[ymin, xmin, ymax, xmax]`` in 0–1000 relative to ``strip``.

    This is the Gemini ``box_2d`` convention (y first, normalised to 1000). Values are rounded and
    clipped to 0..1000. A degenerate strip (zero width or height) raises ``ValueError``.
    """
    sx1, sy1, sx2, sy2 = strip
    strip_width = sx2 - sx1
    strip_height = sy2 - sy1

    if strip_width <= 0 or strip_height <= 0:
        raise ValueError("degenerate strip")

    # Convert box coordinates relative to strip
    x1, y1, x2, y2 = box

    # Normalise to 0-1000
    ymin = round(1000 * (y1 - sy1) / strip_height)
    xmin = round(1000 * (x1 - sx1) / strip_width)
    ymax = round(1000 * (y2 - sy1) / strip_height)
    xmax = round(1000 * (x2 - sx1) / strip_width)

    # Clip to 0-1000
    ymin = max(0, min(1000, ymin))
    xmin = max(0, min(1000, xmin))
    ymax = max(0, min(1000, ymax))
    xmax = max(0, min(1000, xmax))

    return [ymin, xmin, ymax, xmax]
