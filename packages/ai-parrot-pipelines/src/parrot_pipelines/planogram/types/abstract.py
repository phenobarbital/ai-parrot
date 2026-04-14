"""Abstract base class for planogram type composables."""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from PIL import Image

from parrot.models.detections import (
    Detection,
    IdentifiedProduct,
    ShelfRegion,
)
from parrot.models.compliance import ComplianceResult
from parrot.models.google import GoogleModel

if TYPE_CHECKING:
    from ..plan import PlanogramCompliance
    from ..models import PlanogramConfig
    from parrot_pipelines.planogram.grid.strategy import AbstractGridStrategy

_ILLUMINATION_FEATURE_PREFIX = "illumination_status:"


class AbstractPlanogramType(ABC):
    """Contract for planogram type composables.

    Each composable receives a reference to the parent PlanogramCompliance
    pipeline for access to shared utilities (LLM, image helpers, config).

    Concrete implementations handle the type-specific logic for:
    - ROI computation (how to find the region of interest)
    - Macro object detection (poster, logo, backlit, etc.)
    - Product detection and identification
    - Planogram compliance checking

    Args:
        pipeline: Parent PlanogramCompliance instance providing shared
            utilities (LLM clients, image processing, config).
        config: The PlanogramConfig for this compliance run.
    """

    def __init__(
        self,
        pipeline: "PlanogramCompliance",
        config: "PlanogramConfig",
    ) -> None:
        self.pipeline = pipeline
        self.config = config
        self.logger = pipeline.logger

    @abstractmethod
    async def compute_roi(
        self,
        img: Image.Image,
    ) -> Tuple[
        Optional[Tuple[int, int, int, int]],
        Optional[Any],
        Optional[Any],
        Optional[Any],
        List[Any],
    ]:
        """Compute the region of interest for this planogram type.

        Args:
            img: The input PIL image.

        Returns:
            Tuple of (endcap_bbox, ad_detection, brand_detection,
            panel_text_detection, raw_detections_list).
        """

    @abstractmethod
    async def detect_objects_roi(
        self,
        img: Image.Image,
        roi: Any,
    ) -> List[Detection]:
        """Detect macro objects within the ROI.

        Identifies large, visually prominent objects such as poster panels,
        brand logos, backlit graphics, and promotional displays.

        Args:
            img: The input PIL image.
            roi: ROI data from compute_roi().

        Returns:
            List of Detection objects for macro-level items.
        """

    @abstractmethod
    async def detect_objects(
        self,
        img: Image.Image,
        roi: Any,
        macro_objects: Any,
    ) -> Tuple[List[IdentifiedProduct], List[ShelfRegion]]:
        """Detect and identify all products within the ROI.

        Args:
            img: The input PIL image.
            roi: ROI data from compute_roi().
            macro_objects: Macro detections from detect_objects_roi().

        Returns:
            Tuple of (identified_products, shelf_regions).
        """

    @abstractmethod
    def check_planogram_compliance(
        self,
        identified_products: List[IdentifiedProduct],
        planogram_description: Any,
    ) -> List[ComplianceResult]:
        """Compare detected products against the expected planogram.

        Args:
            identified_products: Products detected in the image.
            planogram_description: Expected planogram layout from config.

        Returns:
            List of ComplianceResult, one per shelf/zone.
        """

    @staticmethod
    def _extract_illumination_state(features: List[str]) -> Optional[str]:
        """Parse the illumination state from a list of visual_features strings.

        Looks for entries matching ``illumination_status: ON`` or
        ``illumination_status: OFF`` (case-insensitive).

        Args:
            features: List of visual feature strings.

        Returns:
            Normalised state string (``"on"`` or ``"off"``) or ``None`` if
            no illumination feature is present.
        """
        for feat in features or []:
            if isinstance(feat, str) and feat.lower().startswith(_ILLUMINATION_FEATURE_PREFIX.lower()):
                state = feat[len(_ILLUMINATION_FEATURE_PREFIX):].strip().lower()
                return state  # "on" or "off"
        return None

    async def _check_illumination(
        self,
        img: Image.Image,
        roi: Any,
        planogram_description: Any,
        illum_zone_bbox: Optional[Any] = None,
    ) -> str:
        """Check backlit illumination state using the illuminated zone crop.

        Crops only the zone declared as backlit (via ``illum_zone_bbox``) so
        the LLM focuses on the header panel alone, avoiding confusion from
        ambient store lighting in surrounding areas.  Falls back to the full
        endcap ROI when no zone bbox is provided.

        Args:
            img: The full input PIL image.
            roi: Endcap detection with a bbox attribute (used as fallback crop).
            planogram_description: Planogram description for brand context.
            illum_zone_bbox: DetectionBox with pixel coordinates of the
                illuminated zone (e.g. the header shelf).  When provided,
                this crop is used instead of the full endcap ROI.

        Returns:
            ``'illumination_status: ON'`` or ``'illumination_status: OFF'``
        """
        iw, ih = img.size

        if illum_zone_bbox is not None:
            # Crop only the illuminated zone for a focused check.
            x1 = max(0, int(illum_zone_bbox.x1))
            y1 = max(0, int(illum_zone_bbox.y1))
            x2 = min(iw, int(illum_zone_bbox.x2))
            y2 = min(ih, int(illum_zone_bbox.y2))
            roi_crop = img.crop((x1, y1, x2, y2))
            self.logger.debug(
                "Illumination check using zone crop (%d,%d,%d,%d)", x1, y1, x2, y2
            )
        elif roi is not None and hasattr(roi, "bbox"):
            x1 = int(roi.bbox.x1 * iw)
            y1 = int(roi.bbox.y1 * ih)
            x2 = int(roi.bbox.x2 * iw)
            y2 = int(roi.bbox.y2 * ih)
            roi_crop = img.crop((x1, y1, x2, y2))
        else:
            roi_crop = img.copy()

        roi_small = self.pipeline._downscale_image(roi_crop, max_side=800, quality=82)
        brand = (getattr(planogram_description, "brand", "") or "").strip()
        brand_hint = f" {brand}" if brand else ""

        prompt = (
            f"You are a retail display inspector evaluating a{brand_hint} backlit "
            "lightbox panel (the kind that has fluorescent or LED tubes BEHIND the "
            "graphic, making the sign glow from within).\n\n"
            "This image shows ONLY the header panel crop. Analyze it carefully.\n\n"
            "A backlit lightbox that is ON shows ALL of these signs:\n"
            "  1. The panel surface has a UNIFORM, EVEN glow — the brightness is "
            "consistent across the entire face of the sign, not just where the store "
            "lights happen to hit it.\n"
            "  2. The aluminum or silver frame around the panel appears BRIGHT or has "
            "a HALO/GLOW along its inner edge.\n"
            "  3. The colors in the graphic look VIVID and SATURATED — backlit prints "
            "appear translucent and luminous, not opaque like a regular poster.\n"
            "  4. The panel is DISTINCTLY BRIGHTER than non-illuminated surfaces "
            "nearby (ceiling, walls, shelving).\n\n"
            "A backlit lightbox that is OFF shows:\n"
            "  1. The graphic is visible but ONLY because of ambient store ceiling "
            "lights — NOT because the sign itself is emitting light.\n"
            "  2. The panel looks like a regular PRINTED POSTER or VINYL PRINT — "
            "opaque, matte, with no translucent glow.\n"
            "  3. The frame is dull/matte metal with NO halo.\n"
            "  4. Brightness across the panel surface is UNEVEN — brighter where "
            "overhead lights hit, darker in corners.\n\n"
            "CRITICAL: A well-lit store can make ANY sign look bright. That does NOT "
            "mean the backlight is ON. Look for self-emission, even luminosity, and "
            "frame glow — these only occur when the internal light source is active.\n\n"
            "First, briefly state what you observe (1-2 sentences). "
            "Then on a new line write EXACTLY one word: LIGHT_ON or LIGHT_OFF"
        )

        raw_answer = ""
        try:
            async with self.pipeline.roi_client as client:
                msg = await client.ask_to_image(
                    image=roi_small,
                    prompt=prompt,
                    model=GoogleModel.GEMINI_3_FLASH_PREVIEW,
                    no_memory=True,
                    max_tokens=128,
                )
            raw_answer = (msg.output or "").strip().upper()
        except Exception as exc:
            self.logger.warning(
                "Illumination check failed: %s — defaulting to ON", exc
            )

        state = (
            "illumination_status: OFF"
            if "LIGHT_OFF" in raw_answer
            else "illumination_status: ON"
        )
        self.logger.info(
            "Endcap illumination check → answer=%r  state=%s", raw_answer, state
        )
        return state

    @staticmethod
    def _base_model_from_str(
        s: str, brand: str = None, patterns: Optional[List[str]] = None
    ) -> str:
        """Extract normalized base model from any text, supporting multiple brands.

        If ``patterns`` is provided (from planogram_config.model_normalization_patterns),
        those regex patterns are tried first and replace the generic defaults.
        Each pattern's captured groups are joined with ``'-'`` to form the key.
        Brand-specific and generic fallbacks only run when no configured patterns exist.

        Args:
            s: Raw product name or model string to normalize.
            brand: Optional brand name for brand-specific normalization rules.
            patterns: Optional list of regex patterns from the planogram config
                that override the generic defaults.

        Returns:
            Normalized base model string, or ``""`` if no match is found.
        """
        if not s:
            return ""

        t = s.lower().strip()
        t = t.replace("\u2014", "-").replace("\u2013", "-").replace("_", "-")

        # Configured patterns (from DB) -- replace generic defaults when present
        if patterns:
            for pat in patterns:
                m = re.search(pat, t)
                if m:
                    groups = [g for g in m.groups() if g]
                    if groups:
                        return "-".join(groups)
            return ""

        # Brand-specific fallback (kept for backward compatibility)
        if brand and brand.lower() == "epson":
            m = re.search(r"(et)[- ]?(\d{4})", t)
            if m:
                return f"{m.group(1)}-{m.group(2)}"

        elif brand and brand.lower() == "hisense":
            if re.search(r"canvas[\s-]*tv", t):
                return "canvas-tv"
            if re.search(r"canvas", t):
                return "canvas"
            hisense_patterns = [
                r"(\d*)(u\d+)([a-z]*)",
                r"(u\d+)",
            ]
            for pattern in hisense_patterns:
                m = re.search(pattern, t)
                if m:
                    if len(m.groups()) >= 2:
                        size = m.group(1) if m.group(1) else ""
                        series = m.group(2)
                        variant = m.group(3) if len(m.groups()) > 2 and m.group(3) else ""
                        return f"{size}{series}{variant}".lower()
                    else:
                        return m.group(1).lower()

        # Generic default
        generic_patterns = [
            r"([a-z]+)[- ]?(\d{2,4})",
            r"([a-z]\d+)",
            r"(\d{4})",
        ]
        for pattern in generic_patterns:
            m = re.search(pattern, t)
            if m:
                if len(m.groups()) >= 2:
                    return f"{m.group(1)}-{m.group(2)}"
                else:
                    return m.group(1).lower()
        return ""

    def get_render_colors(self) -> Dict[str, Tuple[int, int, int]]:
        """Return color scheme for rendering compliance overlays.

        Override in concrete types to customize colors per planogram type.

        Returns:
            Dict mapping color role to RGB tuple.
        """
        return {
            "roi": (0, 255, 0),
            "detection": (255, 165, 0),
            "product": (0, 255, 255),
            "compliant": (0, 200, 0),
            "non_compliant": (255, 0, 0),
        }

    def get_grid_strategy(self) -> "AbstractGridStrategy":
        """Return the grid decomposition strategy for this planogram type.

        Override in concrete types to return a type-specific strategy.
        Default returns NoGrid (single cell = full ROI), which preserves
        current single-image detection behavior for all existing types.

        Uses a lazy import to avoid circular import issues.

        Returns:
            AbstractGridStrategy instance (NoGrid by default).
        """
        from parrot_pipelines.planogram.grid.strategy import NoGrid
        return NoGrid()
