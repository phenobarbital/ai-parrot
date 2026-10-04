"""Shared stage 2: OCR, configured identification, and neutral rule evidence."""

from __future__ import annotations

import logging

import numpy as np
from PIL import Image

from parrot_pipelines.planogram.contracts import CycleContext, IdentificationResult, IdentifyStrategy, PerceptionResult
from parrot_pipelines.planogram.identification.evidence import collect_rule_evidence
from parrot_pipelines.planogram.identification.identify import identify_full_image, identify_slots, identify_strips
from parrot_pipelines.planogram.identification.targets import read_target_text

logger = logging.getLogger(__name__)


def to_bgr(image: Image.Image) -> np.ndarray:
    """Convert an untouched full-resolution PIL image to contiguous BGR pixels."""
    return np.asarray(image.convert("RGB"))[:, :, ::-1].copy()


async def identify_image(image: Image.Image, perception: PerceptionResult, ctx: CycleContext) -> IdentificationResult:
    """Read OCR, dispatch the layout strategy, then attach neutral rule observations."""
    layout = ctx.layout
    if layout is None:
        raise ValueError("identify_image requires a resolved layout profile (ctx.layout)")
    bgr = await ctx.executor.run(to_bgr, image)
    perception.ocr_readings = await read_target_text(bgr, perception, ctx)
    perception.ocr_available = bool(getattr(ctx.ocr, "available", False))
    vocabulary = list(layout.descriptor_fields)
    strategy = IdentifyStrategy(layout.identify_strategy)
    if strategy == IdentifyStrategy.FULL_IMAGE:
        result = await identify_full_image(bgr, perception, ctx, vocabulary=vocabulary)
    elif strategy == IdentifyStrategy.STRIPS:
        result = await identify_strips(
            bgr,
            perception,
            ctx,
            vocabulary=vocabulary,
            substrip_max_slots=layout.substrip_max_slots,
        )
    elif strategy == IdentifyStrategy.SLOTS:
        result = await identify_slots(bgr, perception, ctx, vocabulary=vocabulary)
    else:  # pragma: no cover - IdentifyStrategy validates layout values.
        raise ValueError(f"unsupported identify strategy: {strategy}")
    observations = await collect_rule_evidence(bgr, perception, ctx)
    logger.debug(
        "identify_image[%s]: strategy=%s readings=%d observations=%d",
        perception.image_id,
        strategy.value,
        len(perception.ocr_readings),
        len(observations),
    )
    return result.model_copy(update={"rule_observations": observations})
