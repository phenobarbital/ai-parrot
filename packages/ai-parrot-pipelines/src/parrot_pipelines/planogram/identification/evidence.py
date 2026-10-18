"""Neutral, crop-tied rule evidence collected during identification (FEAT-612)."""

from __future__ import annotations

import asyncio
import logging
from typing import List, Literal, Optional, Sequence, Tuple

import numpy as np
from pydantic import BaseModel, Field

from parrot_pipelines.planogram.contracts import (
    APPEARANCE_UNDETERMINED,
    CycleContext,
    FixtureMembership,
    ObservationSource,
    PerceptionResult,
    RuleObservation,
    Shape,
    ZoneAppearance,
)
from parrot_pipelines.planogram.identification.verify import crop_and_encode
from parrot_pipelines.planogram.perception.bands import band_box, banded_zones, fixture_box
from parrot_pipelines.planogram.identification.vision import VisionError

logger = logging.getLogger(__name__)

EVIDENCE_STAGE: str = "evidence"
EVIDENCE_PROMPT_VERSION: str = "evidence-v2"
ZONE_REGION_TARGET: str = "{image_id}:zone-region:{zone_id}"


class ChecklistCount(BaseModel):
    """Counted instances of one checklist feature on a zone crop (-1: undeterminable)."""

    feature: str
    count: int = Field(default=-1, ge=-1)


class ZoneEvidenceAnswer(BaseModel):
    """What the model sees on one observed zone crop."""

    illumination: Literal["on", "off", "unknown"] = "unknown"
    visual_features: List[str] = Field(default_factory=list)
    appearance: ZoneAppearance = Field(default_factory=ZoneAppearance)
    raw_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: List[str] = Field(default_factory=list)
    checklist: List[ChecklistCount] = Field(default_factory=list)


class RegionPresenceAnswer(BaseModel):
    """Whether any display element occupies an inspected region crop."""

    present: Literal["yes", "no", "unknown"] = "unknown"
    raw_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: List[str] = Field(default_factory=list)


def build_zone_prompt(
    ask_illumination: bool, ask_features: bool, ask_appearance: bool = False, *, checklist: Sequence[str] = ()
) -> str:
    """Build a neutral prompt about facts visibly present in a zone crop.

    Args:
        ask_illumination: Ask for the illumination state.
        ask_features: Ask for free-text visual features.
        ask_appearance: Ask for the closed-vocabulary appearance.
        checklist: Features configured by an opt-in ``visual_features`` checklist; each one is counted.
            Empty (the default) leaves the prompt exactly as without the argument.

    Returns:
        The prompt text.
    """
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
    if ask_appearance:
        parts.append(
            "For appearance, report the dominant background colour, the colour of any border or frame "
            "(none when there is none), the surface finish (matte or glossy), and the colour of the floor or "
            "platform the element stands on (not_visible when it is not in the crop); use unknown when a value "
            "cannot be determined."
        )
    if checklist:
        items = "\n".join(f"- {feature}" for feature in checklist)
        parts.append(
            "For each checklist item below, report in checklist the number of distinct instances visibly present "
            "in the crop (0 when absent, -1 when it cannot be determined), echoing the item text exactly:\n" + items
        )
    parts.append("Provide one concise evidence sentence.")
    return "\n".join(parts)


def checklist_features(bindings: Sequence[object]) -> List[str]:
    """Checklist features of every ``visual_features`` binding, deduplicated in first-seen order.

    Args:
        bindings: The run's rule bindings.

    Returns:
        The features to count on each zone crop; empty when no binding declares a checklist.
    """
    features: List[str] = []
    for binding in bindings:
        if getattr(binding, "kind", None) != "visual_features":
            continue
        for item in (getattr(binding, "params", None) or {}).get("checklist") or []:
            feature = item.get("feature") if isinstance(item, dict) else None
            if isinstance(feature, str) and feature.strip() and feature not in features:
                features.append(feature)
    return features


def build_region_prompt() -> str:
    """Build a neutral prompt about whether a display element occupies a crop."""
    return (
        "Inspect this retail display-region crop. Does any display element (sign, graphic panel, header, poster, "
        "screen, or product) occupy this area? Answer yes, no, or unknown; use unknown when blurred, occluded, or "
        "cut off. Provide one concise evidence sentence."
    )


def _region_box(
    region: Tuple[float, float, float, float], size: Tuple[int, int]
) -> Optional[Tuple[int, int, int, int]]:
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
    ask_appearance = "appearance" in kinds
    checklist = checklist_features(ctx.bindings)
    presence_zone_ids = {binding.target_id for binding in ctx.bindings if binding.kind == "zone_present"}
    if not (ask_illumination or ask_features or ask_appearance or presence_zone_ids):
        return []

    observations: List[RuleObservation] = []
    zones = sorted(
        (zone for zone in perception.zones if zone.membership != FixtureMembership.OFF_FIXTURE),
        key=lambda zone: (zone.box.y1, zone.box.x1),
    )
    if ask_illumination or ask_features or ask_appearance:
        prompt = build_zone_prompt(ask_illumination, ask_features, ask_appearance, checklist=checklist)
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
            if ask_appearance:
                values = answer.appearance.model_dump()
                observations.append(
                    RuleObservation(
                        image_id=perception.image_id,
                        target_id=zone.shape_id,
                        kind="appearance",
                        value=values,
                        assessed=any(value not in APPEARANCE_UNDETERMINED for value in values.values()),
                        source=ObservationSource.LLM,
                        evidence=answer.evidence,
                    )
                )
            if checklist:
                # An item the model left out is unknown (-1), never absent: omission is not evidence.
                counts = {item.feature: item.count for item in answer.checklist if item.feature in checklist}
                observations.append(
                    RuleObservation(
                        image_id=perception.image_id,
                        target_id=zone.shape_id,
                        kind="visual_checklist",
                        value={feature: counts.get(feature, -1) for feature in checklist},
                        assessed=any(count >= 0 for count in counts.values()),
                        source=ObservationSource.LLM,
                        evidence=answer.evidence,
                    )
                )

    selectors = list(ctx.layout.zone_selectors) if ctx.layout is not None else []
    height, width = image.shape[:2]
    prompt = build_region_prompt()
    fixture = fixture_box(zones)
    for selector in selectors:
        if selector.zone_id not in presence_zone_ids:
            continue
        target_id = ZONE_REGION_TARGET.format(image_id=perception.image_id, zone_id=selector.zone_id)
        if selector.band is not None:
            # No fixture observed: there is no band to inspect, the zone stays unknown.
            if fixture is None or banded_zones(zones, selector.zone_id):
                continue
            box = band_box(fixture, selector.band)
        elif selector.region is not None:
            box = _region_box(selector.region, (width, height))
        else:
            continue
        if box is None:
            _record_failure(ctx, perception, target_id, ValueError("empty crop"))
            continue
        if selector.band is None and any(_centre_inside(zone, box) for zone in zones):
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
