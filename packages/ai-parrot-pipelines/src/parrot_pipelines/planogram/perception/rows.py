"""Row and shelf-edge structure from proposed shapes (FEAT-574). Pure and picklable."""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

import cv2
import numpy as np

from .profiles import ShapeCandidate

_MIN_PAIR_DX = 0.20  # a defining pair must be at least this fraction of the width apart
_MIN_ROW_SPAN = 0.25  # a row must span at least this fraction of the width
_RESIDUAL_TOL = 0.40  # |dy| to the line, in median member heights
_SIZE_BAND = (0.6, 1.6)  # member size relative to the defining pair's median
_EDGE_MAX_ANGLE_DEG = 5.0  # a shelf edge is (almost) horizontal
_EDGE_CLUSTER = 0.01  # edges closer than this fraction of the height merge into one


def group_rows(
    candidates: Sequence[ShapeCandidate], image_width: int, *, min_row_items: int = 4, max_slope: float = 0.12
) -> List[List[ShapeCandidate]]:
    """Group aligned, similarly sized candidates into visible rows.

    Reference: plancheck/detection.py:68. Rows are *visible* rows, not planogram shelf identities.

    Args:
        candidates: Proposed shapes of ONE image (any profile mix; callers usually pass one kind).
        image_width: Source image width in pixels.
        min_row_items: Minimum members for a row.
        max_slope: Maximum |slope| of a row line (perspective tolerance).

    Returns:
        Rows ordered top→bottom, items left→right. Candidates that fit no row are omitted.
        ``[]`` when fewer than ``min_row_items`` candidates are given.
    """
    if len(candidates) < min_row_items:
        return []
    boxes = np.array([[c.x1, c.y1, c.x2, c.y2] for c in candidates], dtype=float)
    centers = (boxes[:, :2] + boxes[:, 2:]) / 2
    widths = boxes[:, 2] - boxes[:, 0]
    heights = boxes[:, 3] - boxes[:, 1]
    available = list(range(len(candidates)))
    rows: List[Tuple[float, float, List[int]]] = []
    while len(available) >= min_row_items:
        best: Optional[Tuple[Tuple[int, float, int], np.ndarray]] = None
        for offset, i in enumerate(available):
            for j in available[offset + 1 :]:
                dx = centers[j, 0] - centers[i, 0]
                if abs(dx) < _MIN_PAIR_DX * image_width:
                    continue
                slope = (centers[j, 1] - centers[i, 1]) / dx
                if abs(slope) > max_slope:
                    continue
                intercept = centers[i, 1] - slope * centers[i, 0]
                indexes = np.array(available)
                residuals = np.abs(centers[indexes, 1] - (slope * centers[indexes, 0] + intercept))
                med_height = float(np.median(heights[[i, j]]))
                med_width = float(np.median(widths[[i, j]]))
                keep = (
                    (residuals < _RESIDUAL_TOL * med_height)
                    & (heights[indexes] > _SIZE_BAND[0] * med_height)
                    & (heights[indexes] < _SIZE_BAND[1] * med_height)
                    & (widths[indexes] > _SIZE_BAND[0] * med_width)
                    & (widths[indexes] < _SIZE_BAND[1] * med_width)
                )
                members = indexes[keep]
                if len(members) < min_row_items:
                    continue
                if float(np.ptp(centers[members, 0])) < _MIN_ROW_SPAN * image_width:
                    continue
                # More members, then lower median residual, then lower first index.
                score = (len(members), -float(np.median(residuals[keep])), -int(members.min()))
                if best is None or score > best[0]:
                    best = (score, members)
        if best is None:
            break
        members = best[1]
        slope, intercept = np.polyfit(centers[members, 0], centers[members, 1], 1)
        ordered = sorted(members.tolist(), key=lambda k: (centers[k, 0], k))
        rows.append((float(slope), float(intercept), ordered))
        consumed = set(ordered)
        available = [k for k in available if k not in consumed]
    rows.sort(key=lambda row: row[0] * image_width / 2 + row[1])
    return [[candidates[k] for k in members] for _, _, members in rows]


def detect_shelf_edges(image: np.ndarray, *, min_length: float = 0.35) -> List[int]:
    """Y coordinates of long horizontal edges, top→bottom. ``[]`` when none.

    Args:
        image: BGR or gray uint8 source image.
        min_length: Minimum edge length as a fraction of the image width.

    Returns:
        Sorted, de-duplicated y coordinates (ints).

    Raises:
        ValueError: ``image`` is not a non-empty uint8 HxW / HxWx3 array.
    """
    if not isinstance(image, np.ndarray) or image.dtype != np.uint8 or image.size == 0 or image.ndim not in (2, 3):
        raise ValueError("detect_shelf_edges: expected a non-empty uint8 HxW or HxWx3 image")
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    height, width = gray.shape[:2]
    edges = cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 0), 50, 150)
    lines = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi / 180,
        threshold=max(10, int(0.2 * min_length * width)),
        minLineLength=int(min_length * width),
        maxLineGap=max(2, int(0.01 * width)),
    )
    if lines is None:
        return []
    max_tan = np.tan(np.radians(_EDGE_MAX_ANGLE_DEG))
    ys: List[float] = []
    for x1, y1, x2, y2 in lines[:, 0, :]:
        dx = abs(int(x2) - int(x1))
        if dx == 0 or abs(int(y2) - int(y1)) / dx > max_tan:
            continue
        ys.append((int(y1) + int(y2)) / 2.0)
    if not ys:
        return []
    ys.sort()
    tolerance = max(1.0, _EDGE_CLUSTER * height)
    clusters: List[List[float]] = [[ys[0]]]
    for y in ys[1:]:
        if y - clusters[-1][-1] <= tolerance:
            clusters[-1].append(y)
        else:
            clusters.append([y])
    result = sorted({int(round(float(np.median(c)))) for c in clusters})
    return result
