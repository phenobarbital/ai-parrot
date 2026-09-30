"""ProductOnShelves — shelved-product planogram type composed from the shared cycle stages (FEAT-574, FEAT-612).

Perception, identification and comparison come from ``planogram/stages``; this type contributes its
provisional CV defaults and fact-tag corroboration of observed, occupied slots.
"""

from __future__ import annotations

from typing import ClassVar, Dict, List, Mapping, Optional, Sequence

from PIL import Image

from parrot.models.detections import AisleConfig, PlanogramDescription

from ..comparison.definition import SlotsDefinition
from ..contracts import (
    ComparisonResult,
    CycleContext,
    FixtureMembership,
    Identification,
    IdentificationResult,
    IdentifyStrategy,
    PerceptionResult,
    Shape,
    ShapeKind,
    Slot,
)
from ..layout import LayoutProfile, resolve_layout_profile
from ..perception.profiles import ShapeProfile
from ..perception.slots import AnchorRule
from ..stages.compare import compare_observations
from ..stages.identify import identify_image
from ..stages.perceive import perceive_image
from .abstract import AbstractPlanogramType

_SHELF_DESCRIPTORS = ("family", "colors", "pack", "xl")


def _shelf_shape_profiles() -> List[ShapeProfile]:
    """Return fresh copies of the provisional shelves CV candidates."""
    return [
        ShapeProfile(
            name="product_body",
            kind=ShapeKind.PRODUCT.value,
            min_width=0.06,
            max_width=0.30,
            min_height=0.08,
            max_height=0.45,
            min_aspect=0.5,
            max_aspect=2.5,
            polarity="edge",
            min_rectangularity=0.70,
            min_contrast_std=5.0,
        ),
        ShapeProfile(
            name="product_box",
            kind=ShapeKind.BOX.value,
            min_width=0.04,
            max_width=0.20,
            min_height=0.05,
            max_height=0.25,
            min_aspect=0.4,
            max_aspect=2.0,
            polarity="edge",
            min_rectangularity=0.80,
            min_contrast_std=5.0,
        ),
        ShapeProfile(
            name="fact_tag",
            kind=ShapeKind.FACT_TAG.value,
            min_width=0.03,
            max_width=0.12,
            min_height=0.02,
            max_height=0.08,
            min_aspect=1.2,
            max_aspect=4.0,
            polarity="bright",
        ),
        ShapeProfile(
            name="backlit_zone",
            kind=ShapeKind.ZONE.value,
            min_width=0.40,
            max_width=1.0,
            min_height=0.06,
            max_height=0.35,
            min_aspect=1.5,
            max_aspect=12.0,
            polarity="bright",
            min_rectangularity=0.80,
            min_contrast_std=5.0,
            thresholds=(200, 220, 240),
        ),
    ]


def _tag_text(tag: Shape, readings: Mapping[str, object], reads: Mapping[str, Identification]) -> Optional[str]:
    """Return own-box OCR of a fact tag, falling back to shape or vision text."""
    reading = readings.get(tag.shape_id)
    text = getattr(reading, "text", "") or tag.ocr_text
    if not text and tag.shape_id in reads:
        text = reads[tag.shape_id].text
    return text.strip() if text and text.strip() else None


def _slot_above(tag: Shape, slots: Sequence[Slot]) -> Optional[Slot]:
    """Return the slot whose lower area is labelled by a fact tag."""
    cx = (tag.box.x1 + tag.box.x2) / 2
    cy = (tag.box.y1 + tag.box.y2) / 2
    best: Optional[Slot] = None
    for slot in slots:
        height = max(1, slot.box.y2 - slot.box.y1)
        if not slot.box.x1 <= cx <= slot.box.x2:
            continue
        if not (slot.box.y1 + slot.box.y2) / 2 <= cy <= slot.box.y2 + height:
            continue
        if best is None or abs(tag.box.y1 - slot.box.y2) < abs(tag.box.y1 - best.box.y2):
            best = slot
    return best


class ProductOnShelves(AbstractPlanogramType):
    """Shelved products: shared perceive/identify/compare plus fact-tag corroboration."""

    identify_strategy: ClassVar[IdentifyStrategy] = IdentifyStrategy.FULL_IMAGE
    requires_slots_definition: ClassVar[bool] = True
    min_usable_shapes: ClassVar[int] = 3
    uses_enhanced_image: ClassVar[bool] = False

    @classmethod
    def default_layout_profile(cls) -> LayoutProfile:
        """Return a fresh profile with no retailer-specific expectations."""
        return LayoutProfile(
            shape_profiles=_shelf_shape_profiles(),
            anchor_rule=AnchorRule.SHAPE_IS_SLOT,
            fill_gaps=False,
            untagged_bottom_row=False,
            identify_strategy=IdentifyStrategy.FULL_IMAGE,
            perception_mode="cv",
            min_usable_shapes=3,
            descriptor_fields=list(_SHELF_DESCRIPTORS),
            required_descriptor_fields=[],
        )

    def _ensure_layout(self, ctx: CycleContext) -> LayoutProfile:
        """Resolve defaults and configuration when the orchestrator has not populated the context."""
        if ctx.layout is None:
            ctx.layout = resolve_layout_profile(
                self.default_layout_profile(),
                dict(self.config.planogram_config or {}),
                config_name=str(getattr(self.config, "config_name", None) or type(self).__name__),
            )
        return ctx.layout

    async def perceive(self, image: Image.Image, image_id: str, ctx: CycleContext) -> PerceptionResult:
        """Compose shared perception with the resolved type profile."""
        self._ensure_layout(ctx)
        return await perceive_image(image, image_id, ctx)

    async def identify(
        self, image: Image.Image, perception: PerceptionResult, ctx: CycleContext
    ) -> IdentificationResult:
        """Compose shared OCR, vision and rule-evidence collection."""
        self._ensure_layout(ctx)
        return await identify_image(image, perception, ctx)

    async def compare(
        self,
        perceptions: Sequence[PerceptionResult],
        identifications: Sequence[IdentificationResult],
        ctx: CycleContext,
    ) -> ComparisonResult:
        """Run deterministic comparison after fact-tag evidence corroboration."""
        self._ensure_layout(ctx)
        by_image = {perception.image_id: perception for perception in perceptions}
        corroborated = [
            self._corroborate_with_fact_tags(by_image[result.image_id], result, ctx.definition)
            if result.image_id in by_image
            else result
            for result in identifications
        ]
        return compare_observations(perceptions, corroborated, ctx, self._cycle_description())

    @staticmethod
    def _corroborate_with_fact_tags(
        perception: PerceptionResult, result: IdentificationResult, definition: Optional[SlotsDefinition]
    ) -> IdentificationResult:
        """Add fact-tag text to occupied, uncatalogued slot reads without creating observations."""
        tags = [
            shape
            for shape in perception.shapes
            if shape.kind == ShapeKind.FACT_TAG and shape.membership != FixtureMembership.OFF_FIXTURE
        ]
        if not tags or not perception.slots:
            return result
        catalogue = {
            facing.product.casefold() for facing in definition.all_facings() if facing.product
        } if definition else set()
        readings = getattr(perception, "ocr_readings", None) or {}
        reads = {identification.shape_id: identification for identification in result.identifications}
        slot_of: Dict[str, Slot] = {}
        for slot in perception.slots:
            slot_of[slot.slot_id] = slot
            if slot.anchor_shape_id:
                slot_of.setdefault(slot.anchor_shape_id, slot)
        extra: Dict[str, List[str]] = {}
        for tag in tags:
            text = _tag_text(tag, readings, reads)
            slot = _slot_above(tag, perception.slots) if text else None
            if slot is not None:
                extra.setdefault(slot.slot_id, []).append(f"fact_tag | {text}")
        updated: List[Identification] = []
        for identification in result.identifications:
            slot = slot_of.get(identification.shape_id)
            lines = extra.get(slot.slot_id, []) if slot is not None else []
            known = (identification.product or "").casefold().strip() in catalogue
            if lines and identification.occupancy == "occupied" and not known:
                identification = identification.model_copy(update={"evidence": [*identification.evidence, *lines]})
            updated.append(identification)
        return result.model_copy(update={"identifications": updated})

    def _cycle_description(self) -> PlanogramDescription:
        """PlanogramDescription for weights/thresholds; minimal when the config no longer describes shelves."""
        try:
            return self.config.get_planogram_description()
        except Exception as exc:  # noqa: BLE001 - migrated configs may omit the legacy keys
            self.logger.debug("ProductOnShelves: minimal PlanogramDescription (%s)", exc)
            cfg = self.config.planogram_config or {}
            return PlanogramDescription(
                brand=str(cfg.get("brand", "")),
                category=str(cfg.get("category", "")),
                aisle=AisleConfig(name=str(cfg.get("aisle", "") or "aisle")),
                shelves=[],
            )
