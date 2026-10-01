"""Shelf rows for ``SHAPE_IS_SLOT`` fixtures: one row per shelf, one slot per product column.

Product shapes do not arrive as clean rows. Two shape profiles propose the same rectangle, a price
tag is proposed as a small box, a promotional card stands between the products, and cartons stacked
two high on one shelf look like two rows. These helpers reduce the anchors of one image to at most
the number of shelves the fixture is known to have, never using what the shelves should contain.
"""

from __future__ import annotations

from statistics import median
from typing import List, Optional, Sequence, Tuple

from parrot_pipelines.planogram.contracts import Shape, ShapeKind

Box = Tuple[int, int, int, int]
#: One slot of a row: the shape that anchors it and the box it covers (a stack covers several shapes).
RowSlot = Tuple[Shape, Box]

DUPLICATE_IOU = 0.9
TAG_IOU = 0.8
#: A shape this much smaller than the median anchor is not a product of a row that must be pruned.
STRAY_AREA = 0.25
#: Shapes of two merged bands are one stacked column when they share this fraction of the narrower width.
COLUMN_OVERLAP = 0.6

_TAG_KINDS = (ShapeKind.PRICE_TAG, ShapeKind.FACT_TAG)
_KIND_RANK = {ShapeKind.PRODUCT: 0, ShapeKind.BOX: 1}


def _box(shape: Shape) -> Box:
    return (shape.box.x1, shape.box.y1, shape.box.x2, shape.box.y2)


def _area(shape: Shape) -> int:
    return max(0, shape.box.x2 - shape.box.x1) * max(0, shape.box.y2 - shape.box.y1)


def _centre_y(shape: Shape) -> float:
    return (shape.box.y1 + shape.box.y2) / 2.0


def _iou(a: Shape, b: Shape) -> float:
    width = min(a.box.x2, b.box.x2) - max(a.box.x1, b.box.x1)
    height = min(a.box.y2, b.box.y2) - max(a.box.y1, b.box.y1)
    if width <= 0 or height <= 0:
        return 0.0
    shared = width * height
    return shared / float(_area(a) + _area(b) - shared)


def _x_overlap(a: Shape, b: Shape) -> float:
    shared = min(a.box.x2, b.box.x2) - max(a.box.x1, b.box.x1)
    narrower = min(a.box.x2 - a.box.x1, b.box.x2 - b.box.x1)
    return shared / narrower if narrower > 0 else 0.0


def dedupe_anchors(anchors: Sequence[Shape], shapes: Sequence[Shape]) -> List[Shape]:
    """Drop anchors that repeat another anchor or that are really a tag.

    Args:
        anchors: Product-like shapes proposed as slot anchors.
        shapes: Every non-zone shape of the image (tags included).

    Returns:
        The anchors to keep, in their original order.
    """
    tags = [shape for shape in shapes if shape.kind in _TAG_KINDS]
    kept: List[Shape] = []
    ranked = sorted(anchors, key=lambda shape: (_KIND_RANK.get(shape.kind, 2), -shape.box.confidence))
    for anchor in ranked:
        if any(_iou(anchor, tag) >= TAG_IOU for tag in tags):
            continue
        if any(_iou(anchor, other) >= DUPLICATE_IOU for other in kept):
            continue
        kept.append(anchor)
    kept_ids = {shape.shape_id for shape in kept}
    return [anchor for anchor in anchors if anchor.shape_id in kept_ids]


def centre_bands(anchors: Sequence[Shape]) -> List[List[Shape]]:
    """Group anchors into horizontal bands by vertical centre, top to bottom."""
    if not anchors:
        return []
    ordered = sorted(anchors, key=lambda shape: (_centre_y(shape), shape.box.x1))
    height = sorted(shape.box.y2 - shape.box.y1 for shape in ordered)[len(ordered) // 2]
    bands: List[List[Shape]] = [[ordered[0]]]
    for shape in ordered[1:]:
        if abs(_centre_y(shape) - _centre_y(bands[-1][-1])) > height / 2:
            bands.append([])
        bands[-1].append(shape)
    return bands


def _band_centre(band: Sequence[Shape]) -> float:
    return sum(_centre_y(shape) for shape in band) / len(band)


def _stack(band: Sequence[RowSlot]) -> List[RowSlot]:
    """Collapse the shapes of a merged band that sit in the same column into one slot."""
    columns: List[List[RowSlot]] = []
    for slot in sorted(band, key=lambda item: (item[1][0], item[1][1])):
        column = next(
            (group for group in columns if any(_x_overlap(slot[0], other[0]) >= COLUMN_OVERLAP for other in group)),
            None,
        )
        if column is None:
            columns.append([slot])
        else:
            column.append(slot)
    slots: List[RowSlot] = []
    for column in columns:
        top = min(column, key=lambda item: item[1][1])
        boxes = [item[1] for item in column]
        union = (
            min(box[0] for box in boxes),
            min(box[1] for box in boxes),
            max(box[2] for box in boxes),
            max(box[3] for box in boxes),
        )
        slots.append((top[0], union))
    return sorted(slots, key=lambda item: item[1][0])


def fit_rows(bands: Sequence[Sequence[Shape]], max_rows: Optional[int]) -> List[List[RowSlot]]:
    """Reduce bands to at most ``max_rows`` rows.

    Only when there are more bands than the fixture has shelves: shapes far smaller than the median
    anchor are dropped first (cards, tags), then the two vertically closest bands are merged until
    the count fits; shapes of merged bands that share a column become one stacked slot.

    Args:
        bands: Bands top to bottom (``centre_bands`` output or shelf-edge bands).
        max_rows: Shelves the fixture is known to have, or ``None`` when unknown.

    Returns:
        Rows top to bottom, slots left to right.
    """
    rows: List[List[RowSlot]] = [[(shape, _box(shape)) for shape in band] for band in bands if band]
    if max_rows is not None and len(rows) > max_rows:
        areas = [_area(shape) for row in rows for shape, _ in row]
        floor = STRAY_AREA * median(areas)
        rows = [kept for kept in ([slot for slot in row if _area(slot[0]) >= floor] for row in rows) if kept]
        while len(rows) > max(1, max_rows):
            centres = [_band_centre([shape for shape, _ in row]) for row in rows]
            index = min(range(len(rows) - 1), key=lambda k: centres[k + 1] - centres[k])
            rows[index : index + 2] = [_stack([*rows[index], *rows[index + 1]])]
    return [sorted(row, key=lambda item: item[1][0]) for row in rows]
