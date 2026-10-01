"""Own-box local OCR of identification targets (FEAT-612, spec §2 Stage 2 / Module 3)."""

from __future__ import annotations

import asyncio
import logging
from typing import Dict, List, Sequence, Tuple, Union

import numpy as np

from parrot_pipelines.planogram.contracts import CycleContext, OcrReading, PerceptionResult, Shape, ShapeKind, Slot
from parrot_pipelines.planogram.perception.membership import usable_shapes
from parrot_pipelines.planogram.perception.ocr import read_crop

logger = logging.getLogger(__name__)

_DEFAULT_OCR_TARGETS: Tuple[str, ...] = ("slot", "tag", "zone")
_DEFAULT_BATCH: int = 16
_TAG_KINDS = frozenset({ShapeKind.PRICE_TAG, ShapeKind.FACT_TAG})
OcrTarget = Union[Slot, Shape]


def target_id(target: OcrTarget) -> str:
    """Return the stable identifier for a slot or shape target."""
    return target.slot_id if isinstance(target, Slot) else target.shape_id


def ocr_targets(perception: PerceptionResult, kinds: Sequence[str]) -> List[OcrTarget]:
    """Build a de-duplicated, deterministic list of requested OCR targets."""
    requested = set(kinds)
    candidates: List[OcrTarget] = []
    if "slot" in requested:
        if perception.slots:
            candidates.extend(perception.slots)
        else:
            candidates.extend(shape for shape in usable_shapes(perception.shapes) if shape.kind != ShapeKind.ZONE)
    if "tag" in requested:
        candidates.extend(shape for shape in perception.shapes if shape.kind in _TAG_KINDS)
    if "zone" in requested:
        candidates.extend(perception.zones)

    result: List[OcrTarget] = []
    seen: set[str] = set()
    for candidate in candidates:
        identifier = target_id(candidate)
        if identifier not in seen:
            seen.add(identifier)
            result.append(candidate)
    return result


def crop_box(image: np.ndarray, box: Tuple[int, int, int, int]) -> np.ndarray:
    """Clamp ``box`` to image bounds and return a contiguous crop copy."""
    x1, y1, x2, y2 = box
    height, width = image.shape[:2]
    x1 = max(0, min(width, x1))
    y1 = max(0, min(height, y1))
    x2 = max(0, min(width, x2))
    y2 = max(0, min(height, y2))
    return image[y1:y2, x1:x2].copy()


async def read_target_text(image: np.ndarray, perception: PerceptionResult, ctx: CycleContext) -> Dict[str, OcrReading]:
    """Read each configured target's own source-pixel box through the CPU pool."""
    if ctx.ocr is None or not getattr(ctx.ocr, "available", False):
        return {}
    layout = ctx.layout
    kinds = tuple(layout.ocr_targets) if layout is not None else _DEFAULT_OCR_TARGETS
    batch = int(layout.ocr_batch_size) if layout is not None else _DEFAULT_BATCH
    targets = ocr_targets(perception, kinds)
    readings: Dict[str, OcrReading] = {}
    for start in range(0, len(targets), batch):
        chunk = targets[start : start + batch]
        crops = [crop_box(image, (target.box.x1, target.box.y1, target.box.x2, target.box.y2)) for target in chunk]
        try:
            results = await asyncio.gather(*(ctx.executor.run(read_crop, crop) for crop in crops))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - one OCR batch must not abort later batches
            message = f"{perception.image_id}: ocr_failed: {exc}"
            ctx.errors.append(message)
            logger.warning(message)
            continue
        for target, (text, confidence) in zip(chunk, results, strict=True):
            readings[target_id(target)] = OcrReading(text=text, confidence=confidence)
    logger.debug("read_target_text[%s]: %d targets, %d readings", perception.image_id, len(targets), len(readings))
    return readings
