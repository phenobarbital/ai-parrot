"""GraphicPanelDisplay — zone-only graphic/signage panels on the shared cycle (FEAT-612).

Compliance is decided from configured zones only: their presence, text and illumination, observed as
neutral evidence during identification. There is no product counting and no fact-tag path.
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


def _zone_profiles() -> List[ShapeProfile]:
    """PROVISIONAL zone profiles (no accuracy claim): shelves ``backlit_zone`` copy + edge-polarity variant.

    Returns:
        New profile objects on every call.
    """
    backlit = ShapeProfile(
        name="panel_backlit_zone",
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
    graphic = backlit.model_copy(update={"name": "panel_graphic_zone", "polarity": "edge"})
    return [backlit, graphic]


class GraphicPanelDisplay(AbstractPlanogramType):
    """Zone-only graphic panel: presence, text and illumination of configured zones.

    The legacy per-type illumination penalty (1.0) is no longer a code default: migrated rows carry it as
    ``RuleBinding.params["penalty"]`` (emitted by the config converter).
    """

    requires_slots_definition: ClassVar[bool] = True  # plan.py:220 (until TASK-3871)
    uses_enhanced_image: ClassVar[bool] = False  # untouched full-resolution image (spec §2)
    min_usable_shapes: ClassVar[int] = 1  # plan.py:263 threshold (until TASK-3871); mirrors the layout

    @classmethod
    def default_layout_profile(cls) -> LayoutProfile:
        """Zone profiles only, shape-is-slot, full image, CV first, threshold 1 (spec §2 defaults table).

        Returns:
            A fresh profile with no product/fact-tag profiles and no retailer data.
        """
        return LayoutProfile(
            shape_profiles=_zone_profiles(),
            anchor_rule=AnchorRule.SHAPE_IS_SLOT,
            fill_gaps=False,
            untagged_bottom_row=False,
            identify_strategy=IdentifyStrategy.FULL_IMAGE,
            perception_mode="cv",
            min_usable_shapes=1,
        )

    async def perceive(self, image: Image.Image, image_id: str, ctx: CycleContext) -> PerceptionResult:
        """Shared CV perception (zones) with ``ctx.layout``."""
        return await perceive_image(image, image_id, ctx)

    async def identify(
        self, image: Image.Image, perception: PerceptionResult, ctx: CycleContext
    ) -> IdentificationResult:
        """Shared zone OCR/vision identification plus neutral text/illumination/presence evidence."""
        return await identify_image(image, perception, ctx)

    async def compare(
        self,
        perceptions: Sequence[PerceptionResult],
        identifications: Sequence[IdentificationResult],
        ctx: CycleContext,
    ) -> ComparisonResult:
        """Deterministic zone-only comparison; no provider call."""
        return compare_observations(perceptions, identifications, ctx, self._description())

    def _description(self) -> PlanogramDescription:
        """PlanogramDescription for thresholds; minimal fallback when the config lacks shelves keys."""
        try:
            return self.config.get_planogram_description()
        except Exception as exc:  # noqa: BLE001 - panel configs may omit the ProductOnShelves-shaped keys
            self.logger.debug("GraphicPanelDisplay: minimal PlanogramDescription (%s)", exc)
            config = self.config.planogram_config or {}
            return PlanogramDescription(
                brand=str(config.get("brand", "")),
                category=str(config.get("category", "graphic_panel")),
                aisle=AisleConfig(name=str(config.get("aisle", "graphic_panel"))),
                shelves=[],
            )
