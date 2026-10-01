"""Stage 1: configured perception and the shared geometry tail reused by the fallback (FEAT-612)."""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image

from parrot.models.detections import DetectionBox

from ..contracts import CycleContext, FixtureMembership, ObservationSource, PerceptionResult, Shape, ShapeKind
from ..identification.detector import GENERIC_DETECTION_PROMPT, llm_detect_shapes
from ..layout import LayoutProfile, ZoneSelector
from ..perception.membership import assign_membership, usable_shapes
from ..perception.profiles import ShapeCandidate, ShapeProfile
from ..perception.rows import detect_shelf_edges, group_rows
from ..perception.shapes import propose_shapes
from ..perception.slots import AnchorRule, build_slots, candidate_shape_id

logger = logging.getLogger(__name__)

_PRODUCT_KINDS = (ShapeKind.PRODUCT, ShapeKind.BOX, ShapeKind.UNKNOWN)
SELECTOR_EVIDENCE_PREFIX = "zone_selector:"


def _to_bgr(image: Image.Image) -> np.ndarray:
    """Picklable CPU helper: untouched PIL image -> contiguous BGR array."""
    return np.ascontiguousarray(np.asarray(image.convert("RGB"))[:, :, ::-1])


def _propose(bgr: np.ndarray, profiles: List[ShapeProfile], work_width: int) -> List[ShapeCandidate]:
    """Picklable positional wrapper of ``propose_shapes`` (kw-only ``work_width``)."""
    return propose_shapes(bgr, profiles, work_width=work_width)


def _group_rows(
    candidates: List[ShapeCandidate], image_width: int, min_row_items: int, max_slope: float
) -> List[List[ShapeCandidate]]:
    """Picklable positional wrapper of ``group_rows``."""
    return group_rows(candidates, image_width, min_row_items=min_row_items, max_slope=max_slope)


def _profile(ctx: CycleContext) -> LayoutProfile:
    """Return the resolved profile, raising for an incomplete cycle context."""
    if ctx.layout is None:
        raise ValueError("CycleContext.layout is not set")
    return ctx.layout


def _expected_rows(ctx: CycleContext) -> Optional[int]:
    """Shelves of the definition that carry facings; ``None`` when the run has no definition."""
    shelves = getattr(ctx.definition, "shelves", None) or []
    return sum(1 for shelf in shelves if shelf.facings) or None


def _shape_from_candidate(image_id: str, candidate: ShapeCandidate) -> Shape:
    """Convert a CV candidate to a shape using the slot-anchor id scheme."""
    try:
        kind = ShapeKind(candidate.kind)
    except ValueError:
        kind = ShapeKind.UNKNOWN
    return Shape(
        shape_id=candidate_shape_id(image_id, candidate),
        image_id=image_id,
        kind=kind,
        box=DetectionBox(
            x1=candidate.x1,
            y1=candidate.y1,
            x2=candidate.x2,
            y2=candidate.y2,
            confidence=max(0.0, min(1.0, candidate.score)),
        ),
        profile=candidate.profile,
        source=ObservationSource.CV,
    )


def _candidate_from_shape(shape: Shape) -> ShapeCandidate:
    """Convert a shape to a candidate for row and slot primitives."""
    return ShapeCandidate(
        profile=shape.profile or "shape",
        kind=shape.kind.value,
        x1=shape.box.x1,
        y1=shape.box.y1,
        x2=shape.box.x2,
        y2=shape.box.y2,
        score=shape.box.confidence,
    )


async def _rows_tag_below(
    anchors: List[Shape], size: Tuple[int, int], profile: LayoutProfile, ctx: CycleContext
) -> Tuple[List[List[ShapeCandidate]], Dict[str, str]]:
    """Build price-tag rows with the profile's row tolerances."""
    candidates = [_candidate_from_shape(shape) for shape in anchors]
    image_id = anchors[0].image_id if anchors else ""
    by_candidate = {
        candidate_shape_id(image_id, candidate): shape.shape_id
        for shape, candidate in zip(anchors, candidates, strict=False)
    }
    rows = await ctx.executor.run(_group_rows, candidates, size[0], profile.min_row_items, profile.max_row_slope)
    return rows, by_candidate


async def _rows_shape_is_slot(
    bgr: np.ndarray, anchors: List[Shape], size: Tuple[int, int], profile: LayoutProfile, ctx: CycleContext
) -> Tuple[List[List[ShapeCandidate]], Dict[str, str]]:
    """Build shelf-edge bands, falling back to vertical-centre bands."""
    if not anchors:
        return [], {}
    edges = await ctx.executor.run(detect_shelf_edges, bgr)
    image_id = anchors[0].image_id

    def centre_y(shape: Shape) -> float:
        return (shape.box.y1 + shape.box.y2) / 2.0

    bands: Dict[int, List[Shape]] = {}
    if edges:
        bounds = [0, *sorted(edges), size[1]]
        for shape in anchors:
            band = next(
                (index for index in range(len(bounds) - 1) if bounds[index] <= centre_y(shape) < bounds[index + 1]), 0
            )
            bands.setdefault(band, []).append(shape)
    else:
        ordered = sorted(anchors, key=lambda shape: (centre_y(shape), shape.box.x1))
        height = sorted(shape.box.y2 - shape.box.y1 for shape in ordered)[len(ordered) // 2]
        band = 0
        bands[band] = [ordered[0]]
        for shape in ordered[1:]:
            if abs(centre_y(shape) - centre_y(bands[band][-1])) > height / 2:
                band += 1
                bands[band] = []
            bands[band].append(shape)

    rows: List[List[ShapeCandidate]] = []
    by_candidate: Dict[str, str] = {}
    for band in sorted(bands):
        shapes = sorted(bands[band], key=lambda shape: shape.box.x1)
        if len(shapes) < profile.min_row_items:
            continue
        row = [_candidate_from_shape(shape) for shape in shapes]
        rows.append(row)
        by_candidate.update(
            {
                candidate_shape_id(image_id, candidate): shape.shape_id
                for shape, candidate in zip(shapes, row, strict=False)
            }
        )
    return rows, by_candidate


def _match_zone_selectors(zones: List[Shape], selectors: Sequence[ZoneSelector], size: Tuple[int, int]) -> List[Shape]:
    """Copy zones and mark only unambiguously selector-matched observations as on-fixture."""
    grouped: Dict[Tuple[str | None, str | None, Tuple[float, float, float, float] | None], List[ZoneSelector]] = {}
    for selector in selectors:
        grouped.setdefault((selector.profile, selector.kind, selector.region), []).append(selector)
    matches: Dict[str, str] = {}
    width, height = size
    for (profile, kind, region), selector_group in grouped.items():
        candidates = [
            zone
            for zone in zones
            if (profile is None or zone.profile == profile)
            and (kind is None or zone.kind.value == kind)
            and (
                region is None
                or (
                    region[0] * width <= (zone.box.x1 + zone.box.x2) / 2.0 <= region[2] * width
                    and region[1] * height <= (zone.box.y1 + zone.box.y2) / 2.0 <= region[3] * height
                )
            )
        ]
        if len(selector_group) == 1 and len(candidates) == 1:
            matches[candidates[0].shape_id] = selector_group[0].zone_id
        elif len(selector_group) > 1 and len(candidates) == len(selector_group):
            ordered = sorted(candidates, key=lambda zone: (zone.box.y1, zone.box.x1))
            for selector in selector_group:
                if selector.ordinal is not None and selector.ordinal < len(ordered):
                    matches[ordered[selector.ordinal].shape_id] = selector.zone_id
    return [
        (
            zone.model_copy(
                update={
                    "membership": FixtureMembership.ON_FIXTURE,
                    "membership_evidence": [
                        *zone.membership_evidence,
                        f"{SELECTOR_EVIDENCE_PREFIX}{matches[zone.shape_id]}",
                    ],
                }
            )
            if zone.shape_id in matches
            else zone.model_copy()
        )
        for zone in zones
    ]


def _detection_source(shapes: Sequence[Shape], requested: str) -> str:
    """Return requested provenance only when every observation agrees with it."""
    sources = {
        (
            "cv"
            if shape.source == ObservationSource.CV
            else "llm" if shape.source in (ObservationSource.LLM, ObservationSource.LLM_ADDED) else shape.source.value
        )
        for shape in shapes
    }
    return requested if not sources or sources == {requested} else "mixed"


async def rebuild_geometry(
    image: Image.Image, shapes: Sequence[Shape], image_id: str, ctx: CycleContext, *, detection_source: str
) -> PerceptionResult:
    """Rebuild rows, slots, zones and membership from replacement source-pixel shapes."""
    profile = _profile(ctx)
    size = (image.width, image.height)
    bgr = await ctx.executor.run(_to_bgr, image)
    zones = [shape for shape in shapes if shape.kind == ShapeKind.ZONE]
    others = [shape for shape in shapes if shape.kind != ShapeKind.ZONE]
    if profile.anchor_rule == AnchorRule.TAG_BELOW_PRODUCT:
        anchors = [shape for shape in others if shape.kind == ShapeKind.PRICE_TAG]
        rows, by_candidate = await _rows_tag_below(anchors, size, profile, ctx)
    else:
        anchors = [shape for shape in others if shape.kind in _PRODUCT_KINDS]
        rows, by_candidate = await _rows_shape_is_slot(bgr, anchors, size, profile, ctx)
    slots = build_slots(
        rows,
        size,
        image_id=image_id,
        rule=profile.anchor_rule,
        fill_gaps=profile.fill_gaps,
        untagged_bottom_row=profile.untagged_bottom_row,
        max_rows=_expected_rows(ctx),
    )
    slots = [
        slot.model_copy(update={"anchor_shape_id": by_candidate.get(slot.anchor_shape_id or "", slot.anchor_shape_id)})
        for slot in slots
    ]
    positions = {
        slot.anchor_shape_id: (slot.row_index, slot.slot_index) for slot in slots if slot.anchor_shape_id is not None
    }
    others = [
        (
            shape.model_copy(
                update={"row_index": positions[shape.shape_id][0], "slot_index": positions[shape.shape_id][1]}
            )
            if shape.shape_id in positions
            else shape.model_copy()
        )
        for shape in others
    ]
    zones = _match_zone_selectors(zones, profile.zone_selectors, size)
    others = assign_membership(others, zones, size)
    source = _detection_source([*zones, *others], detection_source)
    logger.debug(
        "rebuild_geometry[%s] source=%s shapes=%d slots=%d rows=%d",
        image_id,
        source,
        len(others),
        len(slots),
        len(rows),
    )
    return PerceptionResult(
        image_id=image_id,
        image_size=size,
        shapes=others,
        slots=slots,
        zones=zones,
        row_count=len(rows),
        detection_source=source,
        ocr_available=False,
        errors=[],
    )


async def perceive_image(image: Image.Image, image_id: str, ctx: CycleContext) -> PerceptionResult:
    """Run configured perception only; automatic fallback remains orchestrator-owned."""
    profile = _profile(ctx)
    bgr = await ctx.executor.run(_to_bgr, image)
    if profile.perception_mode == "llm_detector":
        shapes = await llm_detect_shapes(bgr, image_id, ctx, prompt=GENERIC_DETECTION_PROMPT)
        result = await rebuild_geometry(image, shapes, image_id, ctx, detection_source=ObservationSource.LLM.value)
        if not shapes:
            return result.model_copy(update={"errors": [f"{image_id}: llm_detector produced no shapes"]})
        return result
    candidates = await ctx.executor.run(_propose, bgr, list(profile.shape_profiles), profile.work_width)
    shapes = [_shape_from_candidate(image_id, candidate) for candidate in candidates]
    return await rebuild_geometry(image, shapes, image_id, ctx, detection_source=ObservationSource.CV.value)


def count_usable_targets(perception: PerceptionResult, profile: LayoutProfile) -> int:
    """Count only on-fixture targets relevant to the anchor or zone strategy."""
    profile_kinds = {shape_profile.kind for shape_profile in profile.shape_profiles}
    if profile_kinds and profile_kinds == {ShapeKind.ZONE.value}:
        if profile.zone_selectors:
            return sum(
                any(evidence.startswith(SELECTOR_EVIDENCE_PREFIX) for evidence in zone.membership_evidence)
                for zone in perception.zones
            )
        return len(perception.zones)
    on_fixture = usable_shapes(perception.shapes)
    if profile.anchor_rule == AnchorRule.TAG_BELOW_PRODUCT:
        return sum(shape.kind == ShapeKind.PRICE_TAG for shape in on_fixture)
    return sum(shape.kind in _PRODUCT_KINDS for shape in on_fixture)
