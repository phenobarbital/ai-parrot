"""EndcapBacklitMultitier — backlit header + product shelves composed from the shared cycle stages (FEAT-612).

Perception, identification and comparison come from ``planogram/stages``; this type contributes its
defaults and keeps fact tags out of product counts. Header backlight and campaign text are bound rules
decided from rule evidence, never from an LLM call during comparison.
"""

from __future__ import annotations

from typing import ClassVar, List, Sequence, Set, Tuple

from PIL import Image

from parrot.models.detections import AisleConfig, PlanogramDescription

from ..contracts import (
    ComparisonResult,
    CycleContext,
    IdentificationResult,
    IdentifyStrategy,
    PerceptionResult,
    Shape,
    ShapeKind,
)
from ..layout import LayoutProfile, resolve_layout_profile
from ..perception.profiles import ShapeProfile
from ..perception.slots import AnchorRule
from ..stages.compare import compare_observations
from ..stages.identify import identify_image
from ..stages.perceive import perceive_image, rebuild_geometry
from .abstract import AbstractPlanogramType

_BACKLIT_DESCRIPTORS = ("family", "colors", "pack", "xl")
_PRODUCT_KINDS = frozenset({ShapeKind.PRODUCT, ShapeKind.BOX})

# Fact-tag overlap discard heuristic.  When a product detection overlaps an
# already-detected fact-tag by more than this fraction of the product's area,
# the detection is candidate for discard.  See ``_is_fact_tag_misdetection``.
_FACT_TAG_OVERLAP_THRESHOLD: float = 0.30

# A detection is considered occluded (kept) rather than a misdetected fact-tag
# (discarded) when its height is at least this multiple of the overlapping
# fact-tag's height AND the fact-tag sits in the detection's lower half.
_PRODUCT_HEIGHT_VS_TAG_RATIO: float = 1.5


def _is_fact_tag_misdetection(
    det_px: Tuple[int, int, int, int],
    ft: Tuple[int, int, int, int],
    overlap_ratio: float,
) -> bool:
    """Decide whether a detection overlapping a fact-tag is itself a fact-tag.

    Two failure modes produce the same overlap signal and must be distinguished:

    * **(A) Real fact-tag misdetected as product** — the detection has roughly
      the same height as the fact-tag and sits at the same vertical position.
      → Discard.
    * **(B) Tall product occluded at its lower edge by the fact-tag hanging in
      front of the shelf** — the detection is significantly taller than the
      tag and the tag is concentrated in its lower half.
      → Keep (normal occlusion).

    Args:
        det_px: Detection bbox in pixel coordinates ``(x1, y1, x2, y2)``.
        ft: Fact-tag bbox in pixel coordinates ``(x1, y1, x2, y2)``.
        overlap_ratio: ``intersection_area / detection_area`` already
            computed by the caller.

    Returns:
        ``True`` if the detection looks like a misdetected fact-tag and should
        be discarded.  ``False`` if it looks like normal bottom-edge occlusion
        and should be kept.
    """
    if overlap_ratio <= _FACT_TAG_OVERLAP_THRESHOLD:
        return False
    det_h = max(1, det_px[3] - det_px[1])
    ft_h = max(1, ft[3] - ft[1])
    ft_center_y = (ft[1] + ft[3]) / 2.0
    det_center_y = (det_px[1] + det_px[3]) / 2.0
    ft_in_lower_half = ft_center_y > det_center_y
    product_is_taller = det_h > ft_h * _PRODUCT_HEIGHT_VS_TAG_RATIO
    # Normal occlusion → not a misdetect.
    if ft_in_lower_half and product_is_taller:
        return False
    return True


def _backlit_shape_profiles() -> List[ShapeProfile]:
    """Fresh copies of the provisional shelves CV candidates (not an accuracy claim)."""
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


def _px(shape: Shape) -> Tuple[int, int, int, int]:
    """Source-pixel box tuple of a shape."""
    return (shape.box.x1, shape.box.y1, shape.box.x2, shape.box.y2)


class EndcapBacklitMultitier(AbstractPlanogramType):
    """Backlit header + product shelves: shared perceive/identify/compare; fact tags never count as products."""

    identify_strategy: ClassVar[IdentifyStrategy] = IdentifyStrategy.STRIPS  # plan.py reads until TASK-3871
    requires_slots_definition: ClassVar[bool] = True
    min_usable_shapes: ClassVar[int] = 3
    uses_enhanced_image: ClassVar[bool] = False

    @classmethod
    def default_layout_profile(cls) -> LayoutProfile:
        """Return a fresh profile; never retailer product names, expected counts or shared mutable defaults."""
        return LayoutProfile(
            shape_profiles=_backlit_shape_profiles(),
            anchor_rule=AnchorRule.SHAPE_IS_SLOT,
            fill_gaps=False,
            untagged_bottom_row=False,
            identify_strategy=IdentifyStrategy.STRIPS,
            perception_mode="cv",
            min_usable_shapes=3,
            descriptor_fields=list(_BACKLIT_DESCRIPTORS),
            required_descriptor_fields=[],
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
        kept = self._drop_fact_tag_misdetections(perception.shapes)
        if len(kept) == len(perception.shapes):
            return perception
        self.logger.debug("Backlit %s: %d fact-tag misdetections dropped", image_id, len(perception.shapes) - len(kept))
        rebuilt = await rebuild_geometry(
            image, [*kept, *perception.zones], image_id, ctx, detection_source=perception.detection_source
        )
        return rebuilt.model_copy(update={"errors": [*perception.errors, *rebuilt.errors]})

    async def identify(
        self, image: Image.Image, perception: PerceptionResult, ctx: CycleContext
    ) -> IdentificationResult:
        """Compose shared OCR/vision/evidence collection; drop any claim on a fact tag."""
        self._ensure_layout(ctx)
        result = await identify_image(image, perception, ctx)
        tags: Set[str] = {s.shape_id for s in perception.shapes if s.kind == ShapeKind.FACT_TAG}
        added_tags = {s.shape_id for s in result.added if s.kind == ShapeKind.FACT_TAG}
        drop = tags | added_tags
        return result.model_copy(
            update={
                "identifications": [i for i in result.identifications if i.shape_id not in drop],
                "added": [s for s in result.added if s.shape_id not in added_tags],
            }
        )

    async def compare(
        self,
        perceptions: Sequence[PerceptionResult],
        identifications: Sequence[IdentificationResult],
        ctx: CycleContext,
    ) -> ComparisonResult:
        """Run deterministic comparison and the type's evidence-based rule projection."""
        self._ensure_layout(ctx)
        return compare_observations(perceptions, identifications, ctx, self._description())

    @staticmethod
    def _drop_fact_tag_misdetections(shapes: Sequence[Shape]) -> List[Shape]:
        """Remove product/box shapes that are really fact tags; keep occluded tall products (pure)."""
        tags = [s for s in shapes if s.kind == ShapeKind.FACT_TAG]
        if not tags:
            return list(shapes)
        kept: List[Shape] = []
        for shape in shapes:
            if shape.kind in _PRODUCT_KINDS:
                det = _px(shape)
                area = max(1, (det[2] - det[0]) * (det[3] - det[1]))
                misdetected = False
                for tag in tags:
                    ft = _px(tag)
                    inter_w = max(0, min(det[2], ft[2]) - max(det[0], ft[0]))
                    inter_h = max(0, min(det[3], ft[3]) - max(det[1], ft[1]))
                    if _is_fact_tag_misdetection(det, ft, (inter_w * inter_h) / area):
                        misdetected = True
                        break
                if misdetected:
                    continue
            kept.append(shape)
        return kept

    def _description(self) -> PlanogramDescription:
        """PlanogramDescription for weights/thresholds; minimal when the config no longer describes shelves."""
        try:
            return self.config.get_planogram_description()
        except Exception as exc:  # noqa: BLE001 - migrated configs may omit the legacy keys
            self.logger.debug("EndcapBacklitMultitier: minimal PlanogramDescription (%s)", exc)
            cfg = self.config.planogram_config or {}
            return PlanogramDescription(
                brand=str(cfg.get("brand", "")),
                category=str(cfg.get("category", "")),
                aisle=AisleConfig(name=str(cfg.get("aisle", "") or "aisle")),
                shelves=[],
            )
