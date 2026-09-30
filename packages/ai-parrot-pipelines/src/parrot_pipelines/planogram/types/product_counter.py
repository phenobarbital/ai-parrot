"""ProductCounter — product-on-counter displays on the shared cycle (FEAT-612).

Products are expected facings; the promotional background and the information label are configured zones.
Scores use the shared product/text/visual weighting with the configured ``ShelfConfig`` weights.
"""

from __future__ import annotations

from typing import ClassVar, List, Sequence

from PIL import Image

from parrot.models.detections import AisleConfig, PlanogramDescription

from ..contracts import (
    ComparisonResult,
    CycleContext,
    IdentificationResult,
    IdentifyStrategy,
    PerceptionResult,
    ShapeKind,
)
from ..layout import LayoutProfile
from ..perception.profiles import ShapeProfile
from ..perception.slots import AnchorRule
from ..stages.compare import compare_observations
from ..stages.identify import identify_image
from ..stages.perceive import perceive_image
from .abstract import AbstractPlanogramType


def _counter_profiles() -> List[ShapeProfile]:
    """PROVISIONAL body + zone profiles copied from the shelves candidates (no accuracy claim).

    Returns:
        ``[counter_product_body, counter_backlit_zone, counter_panel_zone]`` as new objects on every call.
    """
    body = ShapeProfile(
        name="counter_product_body",
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
    )
    backlit = ShapeProfile(
        name="counter_backlit_zone",
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
    )
    panel = backlit.model_copy(
        update={"name": "counter_panel_zone", "polarity": "edge", "thresholds": ShapeProfile.model_fields["thresholds"].default}
    )
    return [body, backlit, panel]


class ProductCounter(AbstractPlanogramType):
    """Counter/podium display: products as facings, background and information label as zones.

    Legacy ``planogram_config["scoring_weights"]`` is accepted and ignored; the config converter maps it to
    ``ShelfConfig`` weights, which the shared scorer applies.
    """

    requires_slots_definition: ClassVar[bool] = True
    uses_enhanced_image: ClassVar[bool] = False
    min_usable_shapes: ClassVar[int] = 1

    @classmethod
    def default_layout_profile(cls) -> LayoutProfile:
        """Body + zone profiles, shape-is-slot, full image, CV first, threshold 1 (spec §2 defaults table).

        Returns:
            A fresh profile with a neutral, non-mandatory descriptor vocabulary.
        """
        return LayoutProfile(
            shape_profiles=_counter_profiles(),
            anchor_rule=AnchorRule.SHAPE_IS_SLOT,
            fill_gaps=False,
            untagged_bottom_row=False,
            identify_strategy=IdentifyStrategy.FULL_IMAGE,
            perception_mode="cv",
            min_usable_shapes=1,
            descriptor_fields=["family", "colors", "pack"],
            required_descriptor_fields=[],
        )

    async def perceive(self, image: Image.Image, image_id: str, ctx: CycleContext) -> PerceptionResult:
        """Shared CV perception (product bodies + zones) with ``ctx.layout``."""
        return await perceive_image(image, image_id, ctx)

    async def identify(
        self, image: Image.Image, perception: PerceptionResult, ctx: CycleContext
    ) -> IdentificationResult:
        """Shared OCR/vision identification plus neutral zone evidence."""
        return await identify_image(image, perception, ctx)

    async def compare(
        self,
        perceptions: Sequence[PerceptionResult],
        identifications: Sequence[IdentificationResult],
        ctx: CycleContext,
    ) -> ComparisonResult:
        """Deterministic facing + zone comparison with configured weights; no provider call."""
        return compare_observations(perceptions, identifications, ctx, self._description())

    def _description(self) -> PlanogramDescription:
        """PlanogramDescription for weights/thresholds; minimal fallback when the config has no shelves."""
        try:
            return self.config.get_planogram_description()
        except Exception as exc:  # noqa: BLE001 - counter configs may omit the ProductOnShelves-shaped keys
            self.logger.debug("ProductCounter: minimal PlanogramDescription (%s)", exc)
            config = self.config.planogram_config or {}
            return PlanogramDescription(
                brand=str(config.get("brand", "")),
                category=str(config.get("category", "counter")),
                aisle=AisleConfig(name=str(config.get("aisle", "counter"))),
                shelves=[],
            )
