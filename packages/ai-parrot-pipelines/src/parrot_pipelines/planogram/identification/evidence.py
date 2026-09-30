"""Neutral, crop-tied rule evidence collected during identification (FEAT-612)."""

from __future__ import annotations

import asyncio
import logging
from typing import List, Literal, Optional, Tuple

import numpy as np
from pydantic import BaseModel, Field

from parrot_pipelines.planogram.contracts import (
    CycleContext,
    FixtureMembership,
    ObservationSource,
    PerceptionResult,
    RuleObservation,
    Shape,
)
from parrot_pipelines.planogram.identification.verify import crop_and_encode
from parrot_pipelines.planogram.identification.vision import VisionError

logger = logging.getLogger(__name__)

EVIDENCE_STAGE: str = "evidence"
EVIDENCE_PROMPT_VERSION: str = "evidence-v1"
ZONE_REGION_TARGET: str = "{image_id}:zone-region:{zone_id}"


class ZoneEvidenceAnswer(BaseModel):
    """What the model sees on one observed zone crop."""

    illumination: Literal["on", "off", "unknown"] = "unknown"
    visual_features: List[str] = Field(default_factory=list)
    raw_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: List[str] = Field(default_factory=list)


class RegionPresenceAnswer(BaseModel):
    """Whether any display element occupies an inspected region crop."""

    present: Literal["yes", "no", "unknown"] = "unknown"
    raw_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: List[str] = Field(default_factory=list)


def build_zone_prompt(ask_illumination: bool, ask_features: bool) -> str:
    """Build a neutral prompt about facts visibly present in a zone crop."""
    parts = ["Inspect this retail display-zone crop. Report only what is visibly present; do not infer intent."]
    if ask_illumination:
        parts.append(
            "For illumination, report on for uniform self-emitted glow, frame halo, or luminous translucent "
            "colours; off for ambient-lit opaque print; unknown when it cannot be determined."
        )
    if ask_features:
        parts.append(
            "List short phrases for visible logos, graphics, text, screens, or products; use an empty list when none "
            "are visible."
        )
    parts.append("Provide one concise evidence sentence.")
    return "\n".join(parts)


def build_region_prompt() -> str:
    """Build a neutral prompt about whether a display element occupies a crop."""
    return (
        "Inspect this retail display-region crop. Does any display element (sign, graphic panel, header, poster, "
        "screen, or product) occupy this area? Answer yes, no, or unknown; use unknown when blurred, occluded, or "
        "cut off. Provide one concise evidence sentence."
    )


def _region_box(region: Tuple[float, float, float, float], size: Tuple[int, int]) -> Optional[Tuple[int, int, int, int]]:
    """Convert a normalised source region to a clamped pixel box, if non-degenerate."""
    width, height = size
    x1, y1, x2, y2 = region
    box = (
        max(0, min(width, round(x1 * width))),
        max(0, min(height, round(y1 * height))),
        max(0, min(width, round(x2 * width))),
        max(0, min(height, round(y2 * height))),
    )
    return box if box[2] > box[0] and box[3] > box[1] else None


def _centre_inside(shape: Shape, box: Tuple[int, int, int, int]) -> bool:
    """Return whether a shape's box centre is inside ``box``."""
    cx = (shape.box.x1 + shape.box.x2) / 2
    cy = (shape.box.y1 + shape.box.y2) / 2
    return box[0] <= cx <= box[2] and box[1] <= cy <= box[3]


def _record_failure(ctx: CycleContext, perception: PerceptionResult, target_id: str, exc: Exception) -> None:
    """Record one isolated evidence-crop failure."""
    message = f"{perception.image_id}: evidence_failed {target_id}: {exc}"
    ctx.errors.append(message)
    logger.warning(message)


async def collect_rule_evidence(
    image: np.ndarray, perception: PerceptionResult, ctx: CycleContext
) -> List[RuleObservation]:
    """Observe requested zone facts neutrally, isolating failed crops.

    Args:
        image: Untouched full-resolution BGR image.
        perception: Stage-1 source-space observations for one image.
        ctx: Per-run services, bindings, layout, and error sink.

    Returns:
        Neutral observations ordered by observed zone, then configured region.
    """
    kinds = {binding.kind for binding in ctx.bindings}
    ask_illumination = "illumination" in kinds
    ask_features = "visual_features" in kinds
    presence_zone_ids = {binding.target_id for binding in ctx.bindings if binding.kind == "zone_present"}
    if not (ask_illumination or ask_features or presence_zone_ids):
        return []

    observations: List[RuleObservation] = []
    zones = sorted(
        (zone for zone in perception.zones if zone.membership != FixtureMembership.OFF_FIXTURE),
        key=lambda zone: (zone.box.y1, zone.box.x1),
    )
    if ask_illumination or ask_features:
        prompt = build_zone_prompt(ask_illumination, ask_features)
        for zone in zones:
            try:
                png = await ctx.executor.run(
                    crop_and_encode,
                    image,
                    (zone.box.x1, zone.box.y1, zone.box.x2, zone.box.y2),
                )
                answer = await ctx.vision.ask(
                    prompt,
                    [png],
                    ZoneEvidenceAnswer,
                    stage=EVIDENCE_STAGE,
                    prompt_version=EVIDENCE_PROMPT_VERSION,
                )
            except asyncio.CancelledError:
                raise
            except (VisionError, ValueError) as exc:
                _record_failure(ctx, perception, zone.shape_id, exc)
                continue
            if ask_illumination:
                observations.append(
                    RuleObservation(
                        image_id=perception.image_id,
                        target_id=zone.shape_id,
                        kind="illumination",
                        value=answer.illumination,
                        assessed=answer.illumination != "unknown",
                        source=ObservationSource.LLM,
                        evidence=answer.evidence,
                    )
                )
            if ask_features:
                observations.append(
                    RuleObservation(
                        image_id=perception.image_id,
                        target_id=zone.shape_id,
                        kind="visual_features",
                        value=list(answer.visual_features),
                        assessed=True,
                        source=ObservationSource.LLM,
                        evidence=answer.evidence,
                    )
                )

    selectors = list(ctx.layout.zone_selectors) if ctx.layout is not None else []
    height, width = image.shape[:2]
    prompt = build_region_prompt()
    for selector in selectors:
        if selector.zone_id not in presence_zone_ids or selector.region is None:
            continue
        target_id = ZONE_REGION_TARGET.format(image_id=perception.image_id, zone_id=selector.zone_id)
        box = _region_box(selector.region, (width, height))
        if box is None:
            _record_failure(ctx, perception, target_id, ValueError("empty crop"))
            continue
        if any(_centre_inside(zone, box) for zone in zones):
            continue
        try:
            png = await ctx.executor.run(crop_and_encode, image, box)
            answer = await ctx.vision.ask(
                prompt,
                [png],
                RegionPresenceAnswer,
                stage=EVIDENCE_STAGE,
                prompt_version=EVIDENCE_PROMPT_VERSION,
            )
        except asyncio.CancelledError:
            raise
        except (VisionError, ValueError) as exc:
            _record_failure(ctx, perception, target_id, exc)
            continue
        observations.append(
            RuleObservation(
                image_id=perception.image_id,
                target_id=target_id,
                kind="zone_present",
                value=True if answer.present == "yes" else False if answer.present == "no" else None,
                assessed=answer.present != "unknown",
                source=ObservationSource.LLM,
                evidence=answer.evidence,
            )
        )
    return observations
