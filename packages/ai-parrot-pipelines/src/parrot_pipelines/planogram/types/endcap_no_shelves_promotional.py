"""EndcapNoShelvesPromotional on the shared planogram cycle (FEAT-612).

Configured promotional zones are perceived, identified, and compared by the shared cycle stages.
This type supplies only provisional zone profiles and the compatibility defaults required by the
current orchestrator.
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
    """Build provisional zone profiles without sharing mutable model instances.

    ``promo_backlit_zone`` copies the existing shelves ``backlit_zone`` candidate verbatim.
    ``promo_poster_zone`` keeps its size bands and uses edge polarity for printed posters.

    Returns:
        Fresh provisional profiles for one layout profile.
    """
    backlit = ShapeProfile(
        name="promo_backlit_zone",
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
    poster = backlit.model_copy(
        update={
            "name": "promo_poster_zone",
            "polarity": "edge",
            "thresholds": ShapeProfile.model_fields["thresholds"].default,
        }
    )
    return [backlit, poster]


class EndcapNoShelvesPromotional(AbstractPlanogramType):
    """Shelf-less promotional endcap: configured zones, text, and illumination."""

    requires_slots_definition: ClassVar[bool] = True
    uses_enhanced_image: ClassVar[bool] = False
    min_usable_shapes: ClassVar[int] = 1

    @classmethod
    def default_layout_profile(cls) -> LayoutProfile:
        """Return fresh provisional zone defaults for full-image CV perception."""
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
        """Delegate perception to the shared CV stage."""
        return await perceive_image(image, image_id, ctx)

    async def identify(
        self, image: Image.Image, perception: PerceptionResult, ctx: CycleContext
    ) -> IdentificationResult:
        """Delegate OCR, vision identification, and neutral evidence collection."""
        return await identify_image(image, perception, ctx)

    async def compare(
        self,
        perceptions: Sequence[PerceptionResult],
        identifications: Sequence[IdentificationResult],
        ctx: CycleContext,
    ) -> ComparisonResult:
        """Delegate deterministic comparison without provider calls or I/O."""
        return compare_observations(perceptions, identifications, ctx, self._description())

    def _description(self) -> PlanogramDescription:
        """Return configured weights or a minimal promotional description."""
        try:
            return self.config.get_planogram_description()
        except Exception as exc:  # noqa: BLE001 - promotional configs may omit legacy keys
            self.logger.debug("EndcapNoShelvesPromotional: minimal PlanogramDescription (%s)", exc)
            config = self.config.planogram_config or {}
            return PlanogramDescription(
                brand=str(config.get("brand", "")),
                category=str(config.get("category", "promotional")),
                aisle=AisleConfig(name=str(config.get("aisle", "promotional"))),
                shelves=[],
            )
