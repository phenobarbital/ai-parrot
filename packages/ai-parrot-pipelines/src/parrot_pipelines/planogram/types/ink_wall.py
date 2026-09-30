"""InkWall — price-tag anchored planogram type composed from the shared cycle stages (FEAT-574, FEAT-612)."""

from __future__ import annotations

import re
from statistics import median
from typing import Dict, List, Optional, Sequence, Set, Tuple

import numpy as np
from PIL import Image

from parrot.models.detections import AisleConfig, PlanogramDescription

from ..comparison.definition import SlotsDefinition
from ..comparison.identity import resolve_identity  # noqa: F401 - historical import path (spec §2 Stage 3)
from ..contracts import (
    ComparisonResult,
    CycleContext,
    FixtureMembership,
    Identification,
    IdentificationResult,
    IdentifyStrategy,
    PerceptionResult,
    PositionResult,
    Shape,
    Slot,
)
from ..identification.verify import verify_unresolved
from ..layout import LayoutProfile, resolve_layout_profile
from ..perception.profiles import PRICE_TAG_PROFILE
from ..perception.slots import AnchorRule
from ..stages.compare import compare_observations
from ..stages.identify import identify_image
from ..stages.perceive import perceive_image
from .abstract import AbstractPlanogramType

_PRICE = re.compile(r"(\d+)[.,](\d{2})")
_INK_DESCRIPTORS = ("family", "colors", "pack", "xl")
_INK_REQUIRED = ("family", "xl")

__all__ = ["InkWall", "resolve_identity"]


def _to_bgr(image: Image.Image) -> np.ndarray:
    """Untouched full-resolution PIL image -> contiguous BGR array."""
    return np.asarray(image.convert("RGB"))[:, :, ::-1].copy()


def _parse_price(text: Optional[str]) -> Optional[float]:
    """First ``12.99`` / ``12,99`` amount in a text, or None."""
    match = _PRICE.search(text or "")
    return float(f"{match.group(1)}.{match.group(2)}") if match else None


class InkWall(AbstractPlanogramType):
    """Price-tag anchored type: shared perceive/identify/compare plus ink price notes and verify pass."""

    identify_strategy = IdentifyStrategy.STRIPS  # read by plan.py until TASK-3870/3871
    requires_slots_definition = True
    min_usable_shapes = 8
    uses_enhanced_image = False

    @classmethod
    def default_layout_profile(cls) -> LayoutProfile:
        """Return a fresh ink-wall profile; never retailer product names, counts or shared mutable defaults."""
        return LayoutProfile(
            shape_profiles=[PRICE_TAG_PROFILE.model_copy(deep=True)],
            anchor_rule=AnchorRule.TAG_BELOW_PRODUCT,
            fill_gaps=True,
            untagged_bottom_row=True,
            identify_strategy=IdentifyStrategy.STRIPS,
            perception_mode="cv",
            min_usable_shapes=8,
            min_row_items=4,
            descriptor_fields=list(_INK_DESCRIPTORS),
            required_descriptor_fields=list(_INK_REQUIRED),
        )

    def _ensure_layout(self, ctx: CycleContext) -> LayoutProfile:
        """Resolve defaults + config onto the run context when the orchestrator has not (pre-TASK-3871)."""
        if ctx.layout is None:
            ctx.layout = resolve_layout_profile(
                self.default_layout_profile(),
                dict(self.config.planogram_config or {}),
                config_name=str(getattr(self.config, "config_name", None) or type(self).__name__),
            )
        return ctx.layout

    async def perceive(self, image: Image.Image, image_id: str, ctx: CycleContext) -> PerceptionResult:
        """Compose shared perception and type-specific observed geometry only."""
        self._ensure_layout(ctx)
        perception = await perceive_image(image, image_id, ctx)
        self.logger.info(
            "InkWall %s: %d shapes, %d rows, %d slots",
            image_id,
            len(perception.shapes),
            perception.row_count,
            len(perception.slots),
        )
        return perception

    async def identify(
        self, image: Image.Image, perception: PerceptionResult, ctx: CycleContext
    ) -> IdentificationResult:
        """Compose shared OCR/vision/evidence collection, then the optional closed-set verify pass."""
        self._ensure_layout(ctx)
        result = await identify_image(image, perception, ctx)
        if (self.config.planogram_config or {}).get("verify_pass") and ctx.definition is not None:
            boxes = {slot.slot_id: slot.box for slot in perception.slots}
            boxes.update({shape.shape_id: shape.box for shape in perception.shapes})
            verified = await verify_unresolved(
                _to_bgr(image), list(result.identifications), ctx.definition, ctx, boxes=boxes
            )
            return result.model_copy(update={"identifications": verified})
        return result

    async def compare(
        self,
        perceptions: Sequence[PerceptionResult],
        identifications: Sequence[IdentificationResult],
        ctx: CycleContext,
    ) -> ComparisonResult:
        """Run deterministic comparison on registrable ink slots, then append price notes (no I/O)."""
        self._ensure_layout(ctx)
        by_image = {identification.image_id: identification for identification in identifications}
        filtered: List[PerceptionResult] = []
        for perception in perceptions:
            identification = by_image.get(perception.image_id)
            kept = self._registrable_slots(perception, identification.identifications if identification else [])
            filtered.append(perception.model_copy(update={"slots": kept}))
        comparison = compare_observations(filtered, identifications, ctx, self._description())
        positions = self._price_notes(list(comparison.position_results), ctx.definition, filtered)
        return comparison.model_copy(update={"position_results": positions})

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
    ) -> List[PositionResult]:
        """Append ``price_mismatch`` notes (tag OCR vs descriptors.price); credits are never touched."""
        expected = {
            facing.facing_id: facing.descriptors.price
            for facing in definition.all_facings()
            if facing.descriptors.price
        }
        if not expected:
            return positions
        tag_text: Dict[Tuple[str, str], Optional[str]] = {}
        for perception in perceptions:
            readings = perception.ocr_readings
            shapes = {shape.shape_id: shape for shape in perception.shapes}
            for slot in perception.slots:
                if not slot.anchor_shape_id:
                    continue
                reading = readings.get(slot.anchor_shape_id)
                anchor = shapes.get(slot.anchor_shape_id)
                text = (reading.text if reading is not None and reading.text else None) or (
                    anchor.ocr_text if anchor is not None else None
                )
                tag_text[(perception.image_id, slot.slot_id)] = text
                tag_text[(perception.image_id, slot.anchor_shape_id)] = text
        updated: List[PositionResult] = []
        for position in positions:
            price = expected.get(position.facing_id)
            seen: Set[float] = set()
            for reference in position.observations:
                amount = _parse_price(tag_text.get((reference.image_id, reference.shape_id)))
                if amount is not None:
                    seen.add(amount)
            ordered = sorted(seen)
            if price is not None and ordered and any(abs(amount - price) > 0.005 for amount in ordered):
                note = f"price_mismatch: expected {price:.2f}, tag reads {', '.join(f'{amount:.2f}' for amount in ordered)}"
                position = position.model_copy(update={"notes": [*position.notes, note]})
            updated.append(position)
        return updated

    def _description(self) -> PlanogramDescription:
        """PlanogramDescription for weights/thresholds; minimal fallback when the config has no shelves."""
        try:
            return self.config.get_planogram_description()
        except Exception as exc:  # noqa: BLE001 - ink-wall configs may omit the ProductOnShelves-shaped keys
            self.logger.debug("InkWall: minimal PlanogramDescription (%s)", exc)
            config = self.config.planogram_config or {}
            return PlanogramDescription(
                brand=str(config.get("brand", "")),
                category=str(config.get("category", "ink")),
                aisle=AisleConfig(name=str(config.get("aisle", "ink"))),
                shelves=[],
            )
