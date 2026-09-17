"""Price-tag candidate detection and row grouping (FEAT-565).

Faithful port of ``white_label_detector/detect_price_labels.py`` (``candidates`` L15-52, ``group_rows`` L55-107).
Geometry/contrast heuristics only — no model weights. Pure, synchronous, CPU-bound.
"""
from __future__ import annotations

import logging
from typing import Any

import cv2
import numpy as np

from .models import Box, Tag, TagRow

logger = logging.getLogger(__name__)

_THRESHOLDS: tuple[int, ...] = (130, 150, 170, 190, 210, 230)


def find_candidates(image: np.ndarray, min_width: float = 0.025, max_width: float = 0.09) -> list[dict[str, Any]]:
    """Return contrasting, approximately rectangular components found at several gray thresholds.

    Args:
        image: BGR image; all returned boxes are in this image's pixel space.
        min_width: Minimum tag width as a fraction of the image width.
        max_width: Maximum tag width as a fraction of the image width.

    Returns:
        ``[{"box": [x1, y1, x2, y2], "rectangularity": float, "contrast": float}, ...]`` after suppression of
        duplicates across thresholds and of nested screen/frame contours, best rectangularity first.
    """
    h, w = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    found: list[dict[str, Any]] = []
    for threshold in _THRESHOLDS:
        mask = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY)[1]
        contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            x, y, bw, bh = cv2.boundingRect(contour)
            if not (min_width * w < bw < max_width * w and 0.014 * h < bh < 0.06 * h and 1.65 < bw / bh < 4.4):
                continue
            (_, _), (rw, rh), _ = cv2.minAreaRect(contour)
            rectangularity = cv2.contourArea(contour) / (rw * rh + 1e-6)
            if rectangularity < 0.75:
                continue
            contrast = float(gray[y : y + bh, x : x + bw].std())
            if contrast < 25:
                continue
            found.append(
                {"box": [x, y, x + bw, y + bh], "rectangularity": float(rectangularity), "contrast": contrast}
            )
    kept: list[dict[str, Any]] = []
    for item in sorted(found, key=lambda d: d["rectangularity"], reverse=True):
        x1, y1, x2, y2 = item["box"]
        area = (x2 - x1) * (y2 - y1)
        duplicate = False
        for other in kept:
            a, b, c, d = other["box"]
            overlap = max(0, min(x2, c) - max(x1, a)) * max(0, min(y2, d) - max(y1, b))
            if overlap / min(area, (c - a) * (d - b)) > 0.5:
                duplicate = True
                break
        if not duplicate:
            kept.append(item)
    return kept


def group_rows(
    items: list[dict[str, Any]], image_width: int, min_row_labels: int = 4, max_slope: float = 0.12
) -> tuple[list[dict[str, Any]], list[int]]:
    """Deterministic line consensus: at least ``min_row_labels`` aligned, similarly sized boxes per row.

    Groups *visible* label rows, not planogram shelf identities. A row may contain a gap; missing labels are
    never invented here.

    Returns:
        ``(rows, unassigned)`` — ``rows`` sorted top→bottom, each ``{"members": [item index, left→right],
        "slope": float, "intercept": float}`` (line through box centres); ``unassigned`` = leftover item indexes.
    """
    if not items:
        return [], []
    boxes = np.array([d["box"] for d in items], dtype=float)
    centers = (boxes[:, :2] + boxes[:, 2:]) / 2
    widths = boxes[:, 2] - boxes[:, 0]
    heights = boxes[:, 3] - boxes[:, 1]
    available = list(range(len(items)))
    rows: list[dict[str, Any]] = []
    while len(available) >= min_row_labels:
        best: tuple[tuple[int, float], np.ndarray] | None = None
        for offset, i in enumerate(available):
            for j in available[offset + 1 :]:
                dx = centers[j, 0] - centers[i, 0]
                if abs(dx) < 0.2 * image_width:
                    continue
                a = (centers[j, 1] - centers[i, 1]) / dx
                if abs(a) > max_slope:
                    continue
                b = centers[i, 1] - a * centers[i, 0]
                indexes = np.array(available)
                residuals = np.abs(centers[indexes, 1] - (a * centers[indexes, 0] + b))
                med_height = np.median(heights[[i, j]])
                med_width = np.median(widths[[i, j]])
                keep = (
                    (residuals < 0.40 * med_height)
                    & (heights[indexes] > 0.6 * med_height)
                    & (heights[indexes] < 1.6 * med_height)
                    & (widths[indexes] > 0.6 * med_width)
                    & (widths[indexes] < 1.6 * med_width)
                )
                members = indexes[keep]
                if len(members) < min_row_labels:
                    continue
                span = np.ptp(centers[members, 0])
                if span < 0.25 * image_width:
                    continue
                score = (len(members), -float(np.median(residuals[keep])))
                if best is None or score > best[0]:
                    best = (score, members)
        if best is None:
            break
        members = best[1]
        a, b = np.polyfit(centers[members, 0], centers[members, 1], 1)
        ordered = sorted(members.tolist(), key=lambda i: centers[i, 0])
        rows.append({"members": ordered, "slope": float(a), "intercept": float(b)})
        consumed = set(ordered)
        available = [i for i in available if i not in consumed]
    rows.sort(key=lambda row: row["slope"] * image_width / 2 + row["intercept"])
    return rows, available


def _scale_box(box: list[int], sx: float, sy: float) -> Box:
    """Processing-pixel box → original-pixel ``Box`` (same rounding as the reference ``full_box``)."""
    return (round(box[0] * sx), round(box[1] * sy), round(box[2] * sx), round(box[3] * sy))


def detect_tags(
    image: np.ndarray,
    image_id: str,
    *,
    work_width: int = 2048,
    roi: tuple[float, float, float, float] | None = None,
) -> tuple[list[TagRow], list[Box]]:
    """Detect price-tag rows in one image.

    Args:
        image: Original BGR image.
        image_id: Id used to build ``tag_id`` = ``f"{image_id}_r{row:02d}_p{position:02d}"``.
        work_width: Maximum processing width; the image is downscaled (``cv2.INTER_AREA``) only when wider.
        roi: Optional ``(left, top, right, bottom)`` fixture bounds normalised to 0..1; candidates whose centre
            falls outside are dropped. Detection itself always runs on the full image.

    Returns:
        ``(rows, unassigned)`` — rows top→bottom with tags left→right, every coordinate in ORIGINAL pixels
        (boxes, crop boxes and the row line); ``unassigned`` = boxes of candidates that joined no row.
    """
    oh, ow = image.shape[:2]
    scale = min(1.0, work_width / ow)
    work = (
        cv2.resize(image, (round(ow * scale), round(oh * scale)), interpolation=cv2.INTER_AREA) if scale < 1 else image
    )
    h, w = work.shape[:2]
    sx, sy = ow / w, oh / h
    raw = find_candidates(work)
    if roi is not None:
        left, top, right, bottom = roi
        raw = [
            d
            for d in raw
            if left <= (d["box"][0] + d["box"][2]) / (2 * w) <= right
            and top <= (d["box"][1] + d["box"][3]) / (2 * h) <= bottom
        ]
    grouped, unassigned_idx = group_rows(raw, w)
    rows: list[TagRow] = []
    for row_number, row in enumerate(grouped, 1):
        tags: list[Tag] = []
        for position, index in enumerate(row["members"], 1):
            x1, y1, x2, y2 = _scale_box(raw[index]["box"], sx, sy)
            px, py = max(2, round((x2 - x1) * 0.12)), max(2, round((y2 - y1) * 0.18))
            crop_box: Box = (max(0, x1 - px), max(0, y1 - py), min(ow, x2 + px), min(oh, y2 + py))
            tags.append(
                Tag(
                    tag_id=f"{image_id}_r{row_number:02d}_p{position:02d}",
                    image_id=image_id,
                    row=row_number,
                    position=position,
                    box=(x1, y1, x2, y2),
                    crop_box=crop_box,
                    rectangularity=round(raw[index]["rectangularity"], 4),
                )
            )
        rows.append(
            TagRow(
                image_id=image_id,
                row=row_number,
                slope=row["slope"] * sy / sx,
                intercept=row["intercept"] * sy,
                tags=tags,
            )
        )
    unassigned = [_scale_box(raw[i]["box"], sx, sy) for i in unassigned_idx]
    logger.info("%s: %d tag rows, %d tags, %d unassigned", image_id, len(rows), sum(len(r.tags) for r in rows), len(unassigned))
    if not rows:
        logger.warning("%s: no tag rows detected; photo will be reported unregistered upstream", image_id)
    return rows, unassigned
