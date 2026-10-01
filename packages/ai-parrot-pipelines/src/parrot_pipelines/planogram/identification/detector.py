"""LLM detector: fixture ROI, then box proposals inside it, through the vision adapter (detection_source="llm")."""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, List, Optional, Sequence, Tuple

import cv2
import numpy as np
from pydantic import BaseModel, Field, field_validator, model_validator

from parrot.models.detections import DetectionBox
from parrot_pipelines.planogram.contracts import CycleContext, ObservationSource, Shape, ShapeKind
from parrot_pipelines.planogram.identification.vision import VisionError, encode_png
from parrot_pipelines.planogram.perception.membership import assign_membership

logger = logging.getLogger(__name__)

DETECT_PROMPT_VERSION: str = "detect-v2"
DETECT_STAGE: str = "detect"
MAX_SIDE: int = 2048
_KIND_VALUES = ", ".join(kind.value for kind in ShapeKind)
BOX_2D_HINT: str = "box_2d = [ymin, xmin, ymax, xmax], integers normalised to 0..1000 of this image"
GENERIC_DETECTION_PROMPT: str = (
    "You are looking at a photo of a retail display. List every individual product, product box, price tag, "
    "fact tag and every header / backlit / poster zone you can see — one detection per physical object. "
    f"Set label to exactly one of: {_KIND_VALUES}. Give {BOX_2D_HINT}, "
    "a confidence 0..1, and content = the legible text on the object (null when nothing is legible). "
    "Report only what is visible; do not guess and do not invent objects."
)


ROI_PROMPT_VERSION: str = "roi-v2"
ROI_STAGE: str = "roi"
#: Labels a stored ROI prompt uses for the whole fixture and for its header panel.
ROI_FIXTURE_LABELS = ("endcap", "endcap_roi", "endcap-roi", "counter", "display", "fixture")
ROI_PANEL_LABELS = ("poster_panel", "poster", "header")
ROI_TEXT_LABELS = ("brand_logo", "poster_text")
#: Padding around the fixture box, as a fraction of its width / height.
ROI_PAD: float = 0.04
#: A fixture box smaller than this fraction of the image side is not a fixture.
ROI_MIN_SIDE: float = 0.2

#: A fixture box wider than its components by more than this fraction of their span, on one side, is
#: cut back to the components plus ``ROI_SIDE_MARGIN`` of the span on that side.
ROI_SIDE_EXCESS: float = 0.25
ROI_SIDE_MARGIN: float = 0.12
#: A detected "zone" overlapping the header panel and smaller than this fraction of it is a card on it.
ROI_CARD_AREA: float = 0.25

PixelBox = Tuple[int, int, int, int]


class _Boxed(BaseModel):
    """A detection located with ``box_2d``, the box convention vision models are trained to answer in."""

    box_2d: List[float] = Field(min_length=4, max_length=4, description="[ymin, xmin, ymax, xmax], integers 0..1000")

    @model_validator(mode="before")
    @classmethod
    def _from_bbox(cls, value: Any) -> Any:
        """Accept the older ``bbox`` answer (``x1, y1, x2, y2`` normalised to 0..1)."""
        bbox = value.get("bbox") if isinstance(value, dict) and "box_2d" not in value else None
        if isinstance(bbox, dict) and all(isinstance(bbox.get(key), (int, float)) for key in ("x1", "y1", "x2", "y2")):
            box_2d = [bbox["y1"] * 1000, bbox["x1"] * 1000, bbox["y2"] * 1000, bbox["x2"] * 1000]
            return {**{key: item for key, item in value.items() if key != "bbox"}, "box_2d": box_2d}
        return value

    @field_validator("box_2d", mode="before")
    @classmethod
    def _to_thousand(cls, value: Any) -> Any:
        """Accept a 0..1 answer by scaling it to 0..1000."""
        if isinstance(value, (list, tuple)) and len(value) == 4 and all(isinstance(v, (int, float)) for v in value):
            if max(value) <= 1 and any(isinstance(v, float) and not v.is_integer() for v in value):
                return [v * 1000 for v in value]
        return value

    def pixel_box(self, width: int, height: int) -> Tuple[int, int, int, int]:
        """``(x1, y1, x2, y2)`` in pixels of a ``width`` x ``height`` image (unclipped)."""
        ymin, xmin, ymax, xmax = self.box_2d
        return (
            int(xmin / 1000 * width),
            int(ymin / 1000 * height),
            int(xmax / 1000 * width),
            int(ymax / 1000 * height),
        )


class KindDetection(_Boxed):
    """One detector proposal; ``label`` is required and restricted to the shape kinds."""

    label: ShapeKind
    confidence: float = Field(ge=0.0, le=1.0)
    content: Optional[str] = None


class KindDetections(BaseModel):
    """Answer schema of the detector call."""

    detections: List[KindDetection] = Field(default_factory=list)


class RoiDetection(_Boxed):
    """One ROI component; ``label`` is the name the ROI prompt asked for."""

    label: str
    confidence: float = Field(ge=0.0, le=1.0)
    content: Optional[str] = None


class RoiDetections(BaseModel):
    """Answer schema of the ROI call."""

    detections: List[RoiDetection] = Field(default_factory=list)


def _pixels(detection: Any, size: Tuple[int, int]) -> Tuple[int, int, int, int]:
    """Pixel box of a detection in either convention (``box_2d`` or a normalised ``bbox``)."""
    width, height = size
    if hasattr(detection, "pixel_box"):
        return detection.pixel_box(width, height)
    return detection.bbox.get_pixel_coordinates(width, height)


class FixtureRoi(BaseModel):
    """Region of interest of one image: the fixture, and its header panel when the model located it."""

    fixture: Optional[PixelBox] = None  # None: the prompt names no fixture box, detection sees the whole image
    panel: Optional[PixelBox] = None
    panel_text: Optional[str] = None
    #: ``(label, box, text)`` of the ROI components the layout declares as zones (``roi_zone_labels``).
    zones: List[Tuple[str, PixelBox, Optional[str]]] = Field(default_factory=list)


def render_roi_prompt(template: Optional[str], *, brand: str = "", tags: Sequence[str] = ()) -> Optional[str]:
    """Fill the placeholders of a stored ROI prompt (``{brand}``, ``{tag_hint}``, ``{image_size}``).

    Args:
        template: ``PlanogramConfig.roi_detection_prompt``.
        brand: Brand of the fixture.
        tags: Phrases expected on the header (``{tag_hint}``).

    Returns:
        The prompt, or ``None`` without a template. A template with stray braces is used as written.
    """
    if not template or not template.strip():
        return None
    values = defaultdict(
        str, brand=brand, tag_hint=", ".join(sorted({f"'{tag.strip()}'" for tag in tags if tag and tag.strip()}))
    )
    try:
        prompt = template.format_map(values)
    except (ValueError, IndexError, KeyError):
        prompt = template
    return f"{prompt.rstrip()}\n\nLocate every detection with {BOX_2D_HINT}; this replaces any other box format."


def _roi_label(detection: Any) -> str:
    return (detection.label or "").strip().lower().replace(" ", "_")


def _best(detections: Sequence[Any], labels: Sequence[str], size: Tuple[int, int]) -> Optional[PixelBox]:
    """Pixel box of the most confident detection carrying one of ``labels``; ``None`` when degenerate."""
    width, height = size
    found = [detection for detection in detections if _roi_label(detection) in labels]
    if not found:
        return None
    x1, y1, x2, y2 = _pixels(max(found, key=lambda d: d.confidence), size)
    x1, x2 = max(0, min(x1, width)), max(0, min(x2, width))
    y1, y2 = max(0, min(y1, height)), max(0, min(y2, height))
    return (x1, y1, x2, y2) if x2 > x1 and y2 > y1 else None


async def detect_roi(image: np.ndarray, image_id: str, ctx: CycleContext) -> Optional[FixtureRoi]:
    """Locate the fixture with the configured ROI prompt, so detection ignores neighbouring fixtures.

    Args:
        image: Untouched full-resolution BGR image.
        image_id: Image id.
        ctx: Per-run services; ``ctx.roi_prompt`` is the rendered ROI prompt.

    Returns:
        The padded fixture box in source pixels, or ``None`` when no ROI prompt is configured, the call
        fails, or the answer holds no usable fixture box (the caller then detects on the whole image).
    """
    if not ctx.roi_prompt:
        return None
    height, width = image.shape[:2]
    try:
        png = await ctx.executor.run(downscale_and_encode, image, MAX_SIDE)
        answer = await ctx.vision.ask(
            ctx.roi_prompt, [png], RoiDetections, stage=ROI_STAGE, prompt_version=ROI_PROMPT_VERSION
        )
    except VisionError as exc:
        logger.warning("ROI detection failed for %s: %s", image_id, exc)
        ctx.errors.append(f"roi {image_id}: {exc}")
        return None
    zone_labels = [label.strip().lower() for label in getattr(ctx.layout, "roi_zone_labels", None) or []]
    zones = [
        (label, box, next((d.content.strip() for d in answer.detections if _roi_label(d) == label and d.content), None))
        for label, box in ((label, _best(answer.detections, (label,), (width, height))) for label in zone_labels)
        if box is not None
    ]
    fixture = _best(answer.detections, ROI_FIXTURE_LABELS, (width, height))
    if (
        fixture is None
        or fixture[2] - fixture[0] < ROI_MIN_SIDE * width
        or fixture[3] - fixture[1] < ROI_MIN_SIDE * height
    ):
        if zones:
            logger.debug("detect_roi[%s]: no fixture box, zones=%s", image_id, [label for label, _, _ in zones])
            return FixtureRoi(zones=zones)
        ctx.errors.append(f"roi {image_id}: no usable fixture box; detection ran on the whole image")
        return None
    panel = _best(answer.detections, ROI_PANEL_LABELS, (width, height))
    # Every component the ROI prompt asks for is part of the fixture: a fixture box that leaves one out
    # (a top edge mislocated when the header touches the photo border) is stretched to hold them all.
    components = [
        box
        for box in (
            _best([detection], (_roi_label(detection),), (width, height))
            for detection in answer.detections
            if _roi_label(detection) not in ROI_FIXTURE_LABELS
        )
        if box is not None
    ]
    fixture = (
        min([fixture[0], *(box[0] for box in components)]),
        min([fixture[1], *(box[1] for box in components)]),
        max([fixture[2], *(box[2] for box in components)]),
        max([fixture[3], *(box[3] for box in components)]),
    )
    if components:
        # ...and a fixture box that runs far past them sideways has swallowed the neighbouring fixture.
        left, right = min(box[0] for box in components), max(box[2] for box in components)
        span = right - left
        fixture = (
            left - round(ROI_SIDE_MARGIN * span) if left - fixture[0] > ROI_SIDE_EXCESS * span else fixture[0],
            fixture[1],
            right + round(ROI_SIDE_MARGIN * span) if fixture[2] - right > ROI_SIDE_EXCESS * span else fixture[2],
            fixture[3],
        )
    pad_x, pad_y = round(ROI_PAD * (fixture[2] - fixture[0])), round(ROI_PAD * (fixture[3] - fixture[1]))
    padded = (
        max(0, fixture[0] - pad_x),
        max(0, fixture[1] - pad_y),
        min(width, fixture[2] + pad_x),
        min(height, fixture[3] + pad_y),
    )
    texts = [d.content.strip() for d in answer.detections if _roi_label(d) in ROI_TEXT_LABELS and d.content]
    logger.debug("detect_roi[%s]: fixture=%s panel=%s", image_id, padded, panel)
    return FixtureRoi(fixture=padded, panel=panel, panel_text=" ".join(texts) or None, zones=zones)


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


def _kind(label: Any) -> ShapeKind:
    """Map a detection label to a ShapeKind (anything unknown ⇒ UNKNOWN)."""
    if isinstance(label, ShapeKind):
        return label
    try:
        return ShapeKind((label or "").strip().lower())
    except ValueError:
        return ShapeKind.UNKNOWN


def _to_shape(detection: Any, index: int, image_id: str, size: Tuple[int, int]) -> Optional[Shape]:
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
    x1, y1, x2, y2 = _pixels(detection, size)
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


def _card_on_panel(shape: Shape, panel: PixelBox) -> Shape:
    """Re-kind a small "zone" that sits on a far larger zone: it is a card stuck on it, not a second header."""
    if shape.kind != ShapeKind.ZONE:
        return shape
    width = min(shape.box.x2, panel[2]) - max(shape.box.x1, panel[0])
    height = min(shape.box.y2, panel[3]) - max(shape.box.y1, panel[1])
    area = (shape.box.x2 - shape.box.x1) * (shape.box.y2 - shape.box.y1)
    panel_area = (panel[2] - panel[0]) * (panel[3] - panel[1])
    if width > 0 and height > 0 and area < ROI_CARD_AREA * panel_area:
        return shape.model_copy(update={"kind": ShapeKind.FACT_TAG})
    return shape


async def llm_detect_shapes(image: np.ndarray, image_id: str, ctx: CycleContext, *, prompt: str) -> List[Shape]:
    """LLM proposals inside the fixture's region of interest; every shape has source=llm.

    With an ROI prompt on the context the fixture is located first and only its crop is sent to the
    detector, so products of neighbouring fixtures are never proposed; shapes come back in SOURCE-image
    pixels. Without one (or when the ROI call yields nothing) the whole image is sent.

    Args:
        image: Untouched full-resolution BGR image.
        image_id: Image id.
        ctx: Per-run services (vision adapter, CPU executor, error sink, ROI prompt).
        prompt: Detection prompt (types may pass ``GENERIC_DETECTION_PROMPT``).

    Returns:
        Zones first, then the other shapes with membership assigned; ``[]`` on failure.
    """
    roi = await detect_roi(image, image_id, ctx)
    if roi is None:
        return await _detect_shapes(image, image_id, ctx, prompt=prompt)
    left, top, right, bottom = roi.fixture or (0, 0, image.shape[1], image.shape[0])
    shapes = await _detect_shapes(np.ascontiguousarray(image[top:bottom, left:right]), image_id, ctx, prompt=prompt)
    shapes = [
        shape.model_copy(
            update={
                "box": shape.box.model_copy(
                    update={
                        "x1": shape.box.x1 + left,
                        "y1": shape.box.y1 + top,
                        "x2": shape.box.x2 + left,
                        "y2": shape.box.y2 + top,
                    }
                )
            }
        )
        for shape in shapes
    ]
    if roi.panel is not None:
        shapes = [_card_on_panel(shape, roi.panel) for shape in shapes]
    if shapes and roi.panel is not None and not any(shape.kind == ShapeKind.ZONE for shape in shapes):
        # The detector missed the header the ROI call located: keep it as the fixture's zone.
        panel = Shape(
            shape_id=f"{image_id}:roi:panel",
            image_id=image_id,
            kind=ShapeKind.ZONE,
            box=DetectionBox(x1=roi.panel[0], y1=roi.panel[1], x2=roi.panel[2], y2=roi.panel[3], confidence=1.0),
            profile="roi",
            ocr_text=roi.panel_text,
            source=ObservationSource.LLM,
        )
        shapes = [panel, *shapes]
    # Zones the ROI prompt locates by name are observations of their own, next to the detector's.
    named = [
        Shape(
            shape_id=f"{image_id}:roi:{label}",
            image_id=image_id,
            kind=ShapeKind.ZONE,
            box=DetectionBox(x1=box[0], y1=box[1], x2=box[2], y2=box[3], confidence=1.0),
            profile="roi",
            ocr_text=text,
            source=ObservationSource.LLM,
        )
        for label, box, text in roi.zones
    ]
    return [*named, *shapes]


async def _detect_shapes(image: np.ndarray, image_id: str, ctx: CycleContext, *, prompt: str) -> List[Shape]:
    """One detector call over ``image``; shapes in the pixels of ``image``. [] on failure
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
            prompt, [png], KindDetections, stage=DETECT_STAGE, prompt_version=DETECT_PROMPT_VERSION
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
    if len(zones) > 1:
        largest = max(zones, key=lambda zone: (zone.box.x2 - zone.box.x1) * (zone.box.y2 - zone.box.y1))
        panel = (largest.box.x1, largest.box.y1, largest.box.x2, largest.box.y2)
        shapes = [shape if shape is largest else _card_on_panel(shape, panel) for shape in shapes]
        zones = [s for s in shapes if s.kind == ShapeKind.ZONE]
    rest = [s for s in shapes if s.kind != ShapeKind.ZONE]
    return [*zones, *assign_membership(rest, zones, (width, height))]
