"""InkWall — price-tag anchored planogram type for dense walls (FEAT-574)."""

from __future__ import annotations

import asyncio
import re
from statistics import median
from typing import Dict, List, Optional, Sequence, Set, Tuple

import numpy as np
from PIL import Image
from rapidfuzz import fuzz

from parrot.models.detections import AisleConfig, DetectionBox, PlanogramDescription

from ..comparison.definition import FacingDefinition, SlotsDefinition
from ..comparison.projection import finalize_comparison, project_compliance
from ..comparison.registration import ImageRegistration, register_image
from ..comparison.scoring import merge_positions, score_shelves, summarize
from ..contracts import (
    ComparisonResult,
    CycleContext,
    FixtureMembership,
    Identification,
    IdentificationResult,
    IdentifyStrategy,
    ObservationSource,
    PerceptionResult,
    PositionResult,
    Shape,
    ShapeKind,
    Slot,
)
from ..identification.identify import identify_strips
from ..identification.verify import verify_unresolved
from ..perception.membership import assign_membership
from ..perception.ocr import read_crop
from ..perception.profiles import PRICE_TAG_PROFILE
from ..perception.rows import group_rows
from ..perception.shapes import propose_shapes
from ..perception.slots import AnchorRule, build_slots, candidate_shape_id
from .abstract import AbstractPlanogramType

ALIAS_MIN_RATIO = 92.0
OCR_BATCH = 16
_VOCABULARY_FIELDS = ("family", "colors", "pack", "xl")
_PRICE = re.compile(r"(\d+)[.,](\d{2})")
_LINE_SPLIT = re.compile(r"\s*(?:\n|\|)\s*")


def _norm(text: Optional[str]) -> str:
    """Casefold/strip; empty string for None."""
    return str(text).casefold().strip() if text else ""


def _text_lines(identification: Identification) -> List[str]:
    """Normalised text lines the identification carries: read product, text (OCR/LLM) and evidence."""
    raw: List[str] = []
    for chunk in (identification.product, identification.text, *identification.evidence):
        if chunk:
            raw.extend(_LINE_SPLIT.split(str(chunk)))
    return [line for line in (_norm(r) for r in raw) if line]


def _dedupe(facings: Sequence[FacingDefinition]) -> List[str]:
    """Distinct product ids in definition order."""
    seen: List[str] = []
    for facing in facings:
        if facing.product not in seen:
            seen.append(facing.product)
    return seen


def resolve_identity(identification: Identification, definition: SlotsDefinition) -> Tuple[Optional[str], List[str]]:
    """(facing product id or None, candidate ids). Reference: plancheck/reference.py:255.

    Rules in order — identifier, descriptor signature, alias. Never uses the expected facing of the slot.
    Several matches => (None, candidates); nothing => (None, []).

    Args:
        identification: What the model / OCR read for one slot.
        definition: The slots definition (the only catalogue of product ids and descriptors).

    Returns:
        ``(product_id, candidates)``.
    """
    facings: List[FacingDefinition] = [f for s in definition.shelves for f in s.facings]
    brand = _norm(identification.brand)
    pool = [f for f in facings if not brand or _norm(f.brand) == brand]
    if brand and not pool:
        return None, []
    lines = set(_text_lines(identification))

    # Rule 1: an identifier of the definition equals a line of what was read.
    if lines:
        by_identifier = [f for f in pool if any(_norm(i) in lines for i in f.descriptors.identifiers if i)]
        ids = _dedupe(by_identifier)
        if len(ids) == 1:
            return ids[0], ids
        if ids:
            return None, ids

    # Rule 2: descriptor signature (family + non-contradicting colors / pack / xl).
    read = identification.descriptors or {}
    family = _norm(read.get("family"))
    if family:
        matches: List[FacingDefinition] = []
        for facing in pool:
            d = facing.descriptors
            if not d.family or _norm(d.family) != family:
                continue
            colors = read.get("colors")
            if d.colors and colors:
                if {_norm(c) for c in d.colors} != {_norm(c) for c in colors}:
                    continue
            if read.get("pack") is not None and d.pack is not None and str(read.get("pack")) != str(d.pack):
                continue
            xl = read.get("xl")
            if xl is not None and d.xl is not None and bool(xl) != d.xl:
                continue
            matches.append(facing)
        ids = _dedupe(matches)
        if ids:
            # An unknown `xl` can only produce candidates, never a resolution.
            if len(ids) == 1 and read.get("xl") is not None:
                return ids[0], ids
            return None, ids

    # Rule 3: alias (fuzzy token-set match against what was read).
    if lines:
        alias_matches = [
            f
            for f in pool
            if any(
                fuzz.token_set_ratio(_norm(alias), line) >= ALIAS_MIN_RATIO
                for alias in f.descriptors.aliases
                if alias
                for line in lines
            )
        ]
        ids = _dedupe(alias_matches)
        if len(ids) == 1:
            return ids[0], ids
        if ids:
            return None, ids
    return None, []


def _to_bgr(image: Image.Image) -> np.ndarray:
    """Untouched full-resolution PIL image -> contiguous BGR array."""
    return np.asarray(image.convert("RGB"))[:, :, ::-1].copy()


def _parse_price(text: Optional[str]) -> Optional[float]:
    """First ``12.99`` / ``12,99`` amount in a text, or None."""
    match = _PRICE.search(text or "")
    return float(f"{match.group(1)}.{match.group(2)}") if match else None


class InkWall(AbstractPlanogramType):
    """Price-tag anchored type: tags -> rows -> slots above tags -> strips -> descriptor identity."""

    identify_strategy = IdentifyStrategy.STRIPS
    requires_slots_definition = True
    min_usable_shapes = 8
    uses_enhanced_image = False

    async def perceive(self, image: Image.Image, image_id: str, ctx: CycleContext) -> PerceptionResult:
        """Deterministic stage: price tags, rows, slots, tag OCR, fixture membership.

        Args:
            image: Untouched full-resolution image.
            image_id: Image identifier.
            ctx: Per-run services.

        Returns:
            The perception result (CV source).
        """
        bgr = _to_bgr(image)
        size = (image.width, image.height)
        candidates = await ctx.executor.run(propose_shapes, bgr, [PRICE_TAG_PROFILE])
        rows = group_rows(candidates, image.width)
        slots = build_slots(
            rows, size, image_id=image_id, rule=AnchorRule.TAG_BELOW_PRODUCT, fill_gaps=True, untagged_bottom_row=True
        )
        position: Dict[str, Tuple[int, int]] = {
            s.anchor_shape_id: (s.row_index, s.slot_index) for s in slots if s.anchor_shape_id
        }
        shapes: List[Shape] = []
        for candidate in candidates:
            shape_id = candidate_shape_id(image_id, candidate)
            row_index, slot_index = position.get(shape_id, (None, None))
            shapes.append(
                Shape(
                    shape_id=shape_id,
                    image_id=image_id,
                    kind=ShapeKind.PRICE_TAG,
                    box=DetectionBox(
                        x1=candidate.x1,
                        y1=candidate.y1,
                        x2=candidate.x2,
                        y2=candidate.y2,
                        confidence=max(0.0, min(1.0, candidate.score)),
                    ),
                    profile=candidate.profile,
                    row_index=row_index,
                    slot_index=slot_index,
                    source=ObservationSource.CV,
                )
            )
        ocr_available = bool(getattr(ctx.ocr, "available", False))
        if ocr_available and shapes:
            shapes = await self._read_tags(bgr, shapes, ctx)
        shapes = assign_membership(shapes, [], size)
        self.logger.info("InkWall %s: %d tags, %d rows, %d slots", image_id, len(shapes), len(rows), len(slots))
        return PerceptionResult(
            image_id=image_id,
            image_size=size,
            shapes=shapes,
            slots=slots,
            zones=[],
            row_count=len(rows),
            detection_source=ObservationSource.CV.value,
            ocr_available=ocr_available,
            legacy=None,
            errors=[],
        )

    async def _read_tags(self, bgr: np.ndarray, shapes: List[Shape], ctx: CycleContext) -> List[Shape]:
        """Local OCR of every tag through the CPU executor, in bounded batches."""
        results: List[Tuple[str, float]] = []
        for start in range(0, len(shapes), OCR_BATCH):
            batch = shapes[start : start + OCR_BATCH]
            crops = [bgr[s.box.y1 : s.box.y2, s.box.x1 : s.box.x2] for s in batch]
            results.extend(await asyncio.gather(*(ctx.executor.run(read_crop, crop) for crop in crops)))
        return [
            s.model_copy(update={"ocr_text": text or None, "ocr_confidence": conf if text else None})
            for s, (text, conf) in zip(shapes, results, strict=True)
        ]

    async def identify(
        self, image: Image.Image, perception: PerceptionResult, ctx: CycleContext
    ) -> IdentificationResult:
        """LLM stage: one call per row strip (Set-of-Marks), optional closed-set verification.

        Args:
            image: Untouched full-resolution image.
            perception: Stage-1 output.
            ctx: Per-run services.

        Returns:
            The identification result.
        """
        bgr = _to_bgr(image)
        result = await identify_strips(bgr, perception, ctx, vocabulary=self._vocabulary(ctx.definition))
        if (self.config.planogram_config or {}).get("verify_pass") and ctx.definition is not None:
            boxes = {s.slot_id: s.box for s in perception.slots}
            boxes.update({s.shape_id: s.box for s in perception.shapes})
            verified = await verify_unresolved(bgr, list(result.identifications), ctx.definition, ctx, boxes=boxes)
            return result.model_copy(update={"identifications": verified})
        return result

    async def compare(
        self,
        perceptions: Sequence[PerceptionResult],
        identifications: Sequence[IdentificationResult],
        ctx: CycleContext,
    ) -> ComparisonResult:
        """Deterministic stage: identity -> registration per image -> merge -> scores -> projection.

        Only on-fixture slots are registered, and only rows holding at least one read identity: a row
        without any evidence cannot be placed and would only make the registration ambiguous.

        Args:
            perceptions: Stage-1 outputs.
            identifications: Stage-2 outputs (same order).
            ctx: Per-run services (definition, bindings, credit policy, evidence weights).

        Returns:
            The finalised comparison.
        """
        definition: SlotsDefinition = ctx.definition
        description = self._description()
        canonical: List[Identification] = []
        registrations: List[ImageRegistration] = []
        slots_by_image: Dict[str, List[Slot]] = {}
        for perception, ident_result in zip(perceptions, identifications, strict=True):
            idents = [self._canonicalise(i, definition) for i in ident_result.identifications]
            slots = self._registrable_slots(perception, idents)
            slots_by_image[perception.image_id] = slots
            registrations.append(register_image(perception.image_id, slots, idents, definition))
            canonical.extend(idents)
        positions = merge_positions(definition, registrations, canonical, ctx.credit_policy)
        positions = self._price_notes(positions, definition, perceptions, registrations, slots_by_image)
        shelves = score_shelves(positions, definition, ctx.bindings, {}, description, ctx.credit_policy)
        comparison = summarize(shelves, positions, definition, ctx.evidence_weights)
        comparison = comparison.model_copy(update={"position_results": positions, "shelf_scores": shelves})
        return finalize_comparison(comparison, project_compliance(shelves, positions, definition, description))

    def _registrable_slots(self, perception: PerceptionResult, idents: Sequence[Identification]) -> List[Slot]:
        """On-fixture slots of rows with occupancy or identity evidence (fallback: one slot per shape)."""
        slots = list(perception.slots) or self._fallback_slots(perception)
        on_tags = {s.shape_id for s in perception.shapes if s.membership == FixtureMembership.ON_FIXTURE}
        on_rows = {s.row_index for s in slots if s.anchor_shape_id in on_tags}
        last_row = max(on_rows) if on_rows else None

        def on_fixture(slot: Slot) -> bool:
            if slot.anchor_shape_id:
                return slot.anchor_shape_id in on_tags
            return slot.row_index in on_rows or (last_row is not None and slot.row_index == last_row + 1)

        kept = [s for s in slots if on_fixture(s)]
        read = {
            i.shape_id
            for i in idents
            if i.image_id == perception.image_id
            and not i.uncertain
            and (i.occupancy in ("occupied", "empty") or i.product or i.brand)
        }
        rows_with_evidence = {s.row_index for s in kept if s.slot_id in read or s.anchor_shape_id in read}
        return [s for s in kept if s.row_index in rows_with_evidence]

    @staticmethod
    def _fallback_slots(perception: PerceptionResult) -> List[Slot]:
        """LLM-detector fallback (no slots): every on-fixture shape is its own slot, rows by vertical centre."""
        shapes = sorted(
            (s for s in perception.shapes if s.membership == FixtureMembership.ON_FIXTURE),
            key=lambda s: ((s.box.y1 + s.box.y2) / 2, s.box.x1),
        )
        if not shapes:
            return []
        height = median(s.box.y2 - s.box.y1 for s in shapes)
        rows: List[List[Shape]] = [[shapes[0]]]
        for shape in shapes[1:]:
            previous = rows[-1][-1]
            if abs((shape.box.y1 + shape.box.y2) / 2 - (previous.box.y1 + previous.box.y2) / 2) > height / 2:
                rows.append([shape])
            else:
                rows[-1].append(shape)
        slots: List[Slot] = []
        for row_index, row in enumerate(rows):
            for slot_index, shape in enumerate(sorted(row, key=lambda s: s.box.x1), start=1):
                slots.append(
                    Slot(
                        slot_id=f"{perception.image_id}:r{row_index}:s{slot_index}",
                        image_id=perception.image_id,
                        row_index=row_index,
                        slot_index=slot_index,
                        box=shape.box,
                        anchor_shape_id=shape.shape_id,
                    )
                )
        return slots

    @staticmethod
    def _price_notes(
        positions: List[PositionResult],
        definition: SlotsDefinition,
        perceptions: Sequence[PerceptionResult],
        registrations: Sequence[ImageRegistration],
        slots_by_image: Dict[str, List[Slot]],
    ) -> List[PositionResult]:
        """Append ``price_mismatch`` notes (tag OCR vs descriptors.price); credits are never touched."""
        expected = {f.facing_id: f.descriptors.price for f in definition.all_facings() if f.descriptors.price}
        if not expected:
            return positions
        tag_text: Dict[Tuple[str, str], Optional[str]] = {}
        for perception in perceptions:
            shapes = {s.shape_id: s.ocr_text for s in perception.shapes}
            for slot in slots_by_image.get(perception.image_id, []):
                text = shapes.get(slot.anchor_shape_id) if slot.anchor_shape_id else None
                tag_text[(perception.image_id, slot.slot_id)] = text
                if slot.anchor_shape_id:
                    tag_text[(perception.image_id, slot.anchor_shape_id)] = text
        read_prices: Dict[str, Set[float]] = {}
        for reg in registrations:
            for shape_id, facing_id in reg.assignments.items():
                amount = _parse_price(tag_text.get((reg.image_id, shape_id)))
                if amount is not None:
                    read_prices.setdefault(facing_id, set()).add(amount)
        updated: List[PositionResult] = []
        for position in positions:
            price = expected.get(position.facing_id)
            seen = sorted(read_prices.get(position.facing_id, set()))
            if price is not None and seen and any(abs(amount - price) > 0.005 for amount in seen):
                note = f"price_mismatch: expected {price:.2f}, tag reads {', '.join(f'{a:.2f}' for a in seen)}"
                position = position.model_copy(update={"notes": [*position.notes, note]})
            updated.append(position)
        return updated

    def _canonicalise(self, identification: Identification, definition: SlotsDefinition) -> Identification:
        """Copy with ``product`` set to the definition's product id, or unresolved with candidates recorded."""
        product, candidates = resolve_identity(identification, definition)
        descriptors = dict(identification.descriptors or {})
        descriptors["candidates"] = candidates
        return identification.model_copy(update={"product": product, "descriptors": descriptors})

    def _vocabulary(self, definition: Optional[SlotsDefinition]) -> List[str]:
        """Descriptor fields the definition actually uses (field NAMES only — never a SKU or a per-slot value)."""
        if definition is None:
            return []
        used = [
            name
            for name in _VOCABULARY_FIELDS
            if any(getattr(f.descriptors, name) not in (None, [], "") for f in definition.all_facings())
        ]
        return used

    def _description(self) -> PlanogramDescription:
        """PlanogramDescription for weights/thresholds; minimal fallback when the config has no shelves."""
        try:
            return self.config.get_planogram_description()
        except Exception as exc:  # noqa: BLE001 - ink-wall configs may omit the ProductOnShelves-shaped keys
            self.logger.debug("InkWall: minimal PlanogramDescription (%s)", exc)
            cfg = self.config.planogram_config or {}
            return PlanogramDescription(
                brand=str(cfg.get("brand", "")),
                category=str(cfg.get("category", "ink")),
                aisle=AisleConfig(name=str(cfg.get("aisle", "ink"))),
                shelves=[],
            )
