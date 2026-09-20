"""Profile-driven classical-CV shape proposer (FEAT-574). Pure and picklable."""

from __future__ import annotations

import logging
from typing import List, Optional, Sequence, Tuple

import cv2
import numpy as np

from .profiles import ShapeCandidate, ShapeProfile

logger = logging.getLogger(__name__)

_RawBox = Tuple[int, int, int, int, float]  # x1, y1, x2, y2, score — in WORK-image pixels

_EDGE_BLUR = (5, 5)
_EDGE_LOW = 20
_EDGE_HIGH = 60
_EDGE_CLOSE_KERNEL = np.ones((3, 3), dtype=np.uint8)


def _to_gray(image: np.ndarray) -> np.ndarray:
    """Return a uint8 gray image.

    Args:
        image: BGR ``uint8`` array (HxWx3) or gray ``uint8`` array (HxW).

    Returns:
        The gray image (the input itself when already gray).

    Raises:
        ValueError: ``image`` is not a non-empty HxW or HxWx3 ``uint8`` array.
    """
    if not isinstance(image, np.ndarray):
        raise ValueError(f"propose_shapes: expected a numpy array, got {type(image).__name__}")
    if image.dtype != np.uint8:
        raise ValueError(f"propose_shapes: expected dtype uint8, got {image.dtype}")
    if image.size == 0 or image.ndim not in (2, 3):
        raise ValueError(f"propose_shapes: expected a non-empty HxW or HxWx3 image, got shape {image.shape}")
    if image.ndim == 2:
        return image
    if image.shape[2] != 3:
        raise ValueError(f"propose_shapes: expected 3 channels (BGR), got {image.shape[2]}")
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


def _masks(gray: np.ndarray, profile: ShapeProfile) -> List[np.ndarray]:
    """Binary masks to contour for one profile, one per threshold (or one edge mask).

    Args:
        gray: Gray work image.
        profile: Profile whose polarity/thresholds drive the masks.

    Returns:
        ``uint8`` masks with the shape of ``gray``.
    """
    if profile.polarity == "bright":
        return [cv2.threshold(gray, t, 255, cv2.THRESH_BINARY)[1] for t in profile.thresholds]
    if profile.polarity == "dark":
        return [cv2.threshold(gray, t, 255, cv2.THRESH_BINARY_INV)[1] for t in profile.thresholds]
    blurred = cv2.GaussianBlur(gray, _EDGE_BLUR, 0)
    edges = cv2.Canny(blurred, _EDGE_LOW, _EDGE_HIGH)
    return [cv2.morphologyEx(edges, cv2.MORPH_CLOSE, _EDGE_CLOSE_KERNEL)]


def _qualifies(contour: np.ndarray, gray: np.ndarray, profile: ShapeProfile) -> Optional[_RawBox]:
    """Apply the size/aspect/rectangularity/contrast gates of one profile to one contour.

    Args:
        contour: One OpenCV contour.
        gray: Gray work image the contour was found on.
        profile: Profile providing the gates.

    Returns:
        ``(x1, y1, x2, y2, score)`` in work pixels, or ``None`` when a gate rejects the contour.
    """
    height, width = gray.shape[:2]
    x, y, bw, bh = cv2.boundingRect(contour)
    if bw <= 0 or bh <= 0:
        return None
    if not (
        profile.min_width * width < bw < profile.max_width * width
        and profile.min_height * height < bh < profile.max_height * height
        and profile.min_aspect < bw / bh < profile.max_aspect
    ):
        return None
    if profile.polarity == "edge":
        # An edge contour is an outline: measure how well its convex hull fills the bounding rectangle.
        rectangularity = cv2.contourArea(cv2.convexHull(contour)) / (bw * bh + 1e-6)
    else:
        (_, _), (rw, rh), _ = cv2.minAreaRect(contour)
        rectangularity = cv2.contourArea(contour) / (rw * rh + 1e-6)
    if rectangularity < profile.min_rectangularity:
        return None
    contrast = float(gray[y : y + bh, x : x + bw].std())
    if contrast < profile.min_contrast_std:
        return None
    return (x, y, x + bw, y + bh, float(min(1.0, rectangularity)))


def _dedup(boxes: List[_RawBox], overlap: float) -> List[_RawBox]:
    """Keep best-score-first boxes; drop one whose intersection / min(area) exceeds ``overlap``.

    Args:
        boxes: Candidate boxes of ONE profile.
        overlap: Maximum tolerated ``intersection / min(area)``.

    Returns:
        The kept boxes, best score first (stable for equal scores).
    """
    kept: List[_RawBox] = []
    for box in sorted(boxes, key=lambda b: b[4], reverse=True):
        x1, y1, x2, y2, _ = box
        area = (x2 - x1) * (y2 - y1)
        duplicate = False
        for a, b, c, d, _ in kept:
            inter = max(0, min(x2, c) - max(x1, a)) * max(0, min(y2, d) - max(y1, b))
            smallest = min(area, (c - a) * (d - b))
            if smallest > 0 and inter / smallest > overlap:
                duplicate = True
                break
        if not duplicate:
            kept.append(box)
    return kept


def propose_shapes(
    image: np.ndarray, profiles: Sequence[ShapeProfile], *, work_width: int = 2048
) -> List[ShapeCandidate]:
    """Propose rectangles for every profile on a BGR image.

    Pure, synchronous and picklable (runs inside a process pool). Coordinates are scaled back to the
    source image and clipped to it.

    Args:
        image: BGR ``uint8`` array (HxWx3) or gray (HxW).
        profiles: Profiles to evaluate; each is de-duplicated independently.
        work_width: Detection runs on a copy downscaled to this width when the image is wider.

    Returns:
        Candidates grouped by profile order, best score first inside a profile. ``[]`` when nothing
        qualifies or ``profiles`` is empty. Never raises on a valid image.

    Raises:
        ValueError: ``image`` is not a non-empty uint8 HxW / HxWx3 array, or ``work_width`` < 1.
    """
    gray = _to_gray(image)
    if work_width < 1:
        raise ValueError(f"propose_shapes: work_width must be >= 1, got {work_width}")
    height, width = gray.shape[:2]
    scale = work_width / width if width > work_width else 1.0
    if scale < 1.0:
        work = cv2.resize(
            gray,
            (max(1, round(width * scale)), max(1, round(height * scale))),
            interpolation=cv2.INTER_AREA,
        )
    else:
        work = gray
    work_h, work_w = work.shape[:2]
    sx, sy = width / work_w, height / work_h

    candidates: List[ShapeCandidate] = []
    for profile in profiles:
        raw: List[_RawBox] = []
        for mask in _masks(work, profile):
            contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
            for contour in contours:
                box = _qualifies(contour, work, profile)
                if box is not None:
                    raw.append(box)
        kept = 0
        for x1, y1, x2, y2, score in _dedup(raw, profile.dedup_overlap):
            sx1 = min(max(round(x1 * sx), 0), width)
            sy1 = min(max(round(y1 * sy), 0), height)
            sx2 = min(max(round(x2 * sx), 0), width)
            sy2 = min(max(round(y2 * sy), 0), height)
            if sx2 <= sx1 or sy2 <= sy1:
                continue
            candidates.append(
                ShapeCandidate(profile=profile.name, kind=profile.kind, x1=sx1, y1=sy1, x2=sx2, y2=sy2, score=score)
            )
            kept += 1
        logger.debug("propose_shapes: profile %s kept %d candidate(s)", profile.name, kept)
    return candidates
