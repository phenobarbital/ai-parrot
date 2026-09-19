"""LLM detector fallback: full-image box proposals through the vision adapter (detection_source="llm")."""

from __future__ import annotations

import logging
from typing import List, Optional, Tuple

import cv2
import numpy as np

from parrot.models.detections import Detection, Detections, DetectionBox
from parrot_pipelines.planogram.contracts import CycleContext, ObservationSource, Shape, ShapeKind
from parrot_pipelines.planogram.identification.vision import VisionError, encode_png
from parrot_pipelines.planogram.perception.membership import assign_membership

logger = logging.getLogger(__name__)

DETECT_PROMPT_VERSION: str = "detect-v1"
DETECT_STAGE: str = "detect"
MAX_SIDE: int = 2048
_KIND_VALUES = ", ".join(kind.value for kind in ShapeKind)
GENERIC_DETECTION_PROMPT: str = (
    "You are looking at a photo of a retail display. List every individual product, product box, price tag, "
    "fact tag and every header / backlit / poster zone you can see — one detection per physical object. "
    f"Set label to exactly one of: {_KIND_VALUES}. Give bbox as x1, y1, x2, y2 normalised to 0..1 of this "
    "image, a confidence 0..1, and content = the legible text on the object (null when nothing is legible). "
    "Report only what is visible; do not guess and do not invent objects."
)


def downscale_and_encode(image: np.ndarray, max_side: int = MAX_SIDE) -> bytes:
    """Resize so the longest side is <= max_side (never upscale) and PNG-encode. Picklable (CPU executor).

    Args:
        image: Source BGR image.
        max_side: Longest side of the encoded copy.

    Returns:
        PNG bytes.
    """
    height, width = image.shape[:2]
    scale = min(1.0, max_side / float(max(height, width)))
    if scale < 1.0:
        image = cv2.resize(image, (int(width * scale), int(height * scale)), interpolation=cv2.INTER_AREA)
    return encode_png(image)


def _kind(label: Optional[str]) -> ShapeKind:
    """Map a detection label to a ShapeKind (anything unknown ⇒ UNKNOWN)."""
    try:
        return ShapeKind((label or "").strip().lower())
    except ValueError:
        return ShapeKind.UNKNOWN


def _to_shape(detection: Detection, index: int, image_id: str, size: Tuple[int, int]) -> Optional[Shape]:
    """Pixel Shape in SOURCE-image coordinates, or None for a degenerate box.

    Args:
        detection: One normalised detection.
        index: 1-based index used for the pipeline-owned id.
        image_id: Image id.
        size: ``(width, height)`` of the SOURCE image.

    Returns:
        The shape, or ``None`` when the box has no area inside the image.
    """
    width, height = size
    x1, y1, x2, y2 = detection.bbox.get_pixel_coordinates(width, height)
    x1, x2 = max(0, min(x1, width)), max(0, min(x2, width))
    y1, y2 = max(0, min(y1, height)), max(0, min(y2, height))
    if x2 <= x1 or y2 <= y1:
        return None
    return Shape(
        shape_id=f"{image_id}:llm:{index}",
        image_id=image_id,
        kind=_kind(detection.label),
        box=DetectionBox(x1=x1, y1=y1, x2=x2, y2=y2, confidence=detection.confidence),
        profile="llm_detector",
        ocr_text=detection.content,
        source=ObservationSource.LLM,
    )


async def llm_detect_shapes(image: np.ndarray, image_id: str, ctx: CycleContext, *, prompt: str) -> List[Shape]:
    """Full-image LLM proposals through VisionAdapter; every shape has source=llm. [] on failure
    (the failure is appended to ctx.errors).

    Args:
        image: Untouched full-resolution BGR image.
        image_id: Image id.
        ctx: Per-run services (vision adapter, CPU executor, error sink).
        prompt: Detection prompt (types may pass ``GENERIC_DETECTION_PROMPT``).

    Returns:
        Zones first, then the other shapes with membership assigned.
    """
    height, width = image.shape[:2]
    try:
        png = await ctx.executor.run(downscale_and_encode, image, MAX_SIDE)
        answer = await ctx.vision.ask(
            prompt, [png], Detections, stage=DETECT_STAGE, prompt_version=DETECT_PROMPT_VERSION
        )
    except VisionError as exc:
        logger.warning("LLM detector failed for %s: %s", image_id, exc)
        ctx.errors.append(f"llm_detector {image_id}: {exc}")
        return []
    shapes: List[Shape] = []
    for detection in answer.detections:
        shape = _to_shape(detection, len(shapes) + 1, image_id, (width, height))
        if shape is not None:
            shapes.append(shape)
    zones = [s for s in shapes if s.kind == ShapeKind.ZONE]
    rest = [s for s in shapes if s.kind != ShapeKind.ZONE]
    return [*zones, *assign_membership(rest, zones, (width, height))]
