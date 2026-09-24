"""Abstract base class for planogram type composables."""

from __future__ import annotations

import re
from abc import ABC
from typing import Any, ClassVar, Dict, List, Optional, Sequence, Tuple, TYPE_CHECKING

from PIL import Image

from parrot.models.detections import (
    Detection,
    DetectionBox,
    IdentifiedProduct,
    ShelfRegion,
)
from parrot.models.compliance import ComplianceResult, ComplianceStatus
from ..contracts import (
    AssessmentStatus,
    ComparisonResult,
    CycleContext,
    IdentificationResult,
    IdentifyStrategy,
    PerceptionResult,
)

if TYPE_CHECKING:
    from ..plan import PlanogramCompliance
    from ..models import PlanogramConfig
    from parrot_pipelines.planogram.grid.strategy import AbstractGridStrategy

_ILLUMINATION_FEATURE_PREFIX = "illumination_status:"
_DEFAULT_ILLUMINATION_PENALTY: float = 1.0


class AbstractPlanogramType(ABC):  # noqa: B024 - contract enforced by validate_contract() (FEAT-574)
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

    identify_strategy: ClassVar[IdentifyStrategy] = IdentifyStrategy.FULL_IMAGE
    requires_slots_definition: ClassVar[bool] = False
    min_usable_shapes: ClassVar[int] = 0  # fallback threshold; 0 disables the LLM-detector fallback
    uses_enhanced_image: ClassVar[bool] = True  # legacy default; migrated types set False

    _LEGACY_CONTRACT: ClassVar[Tuple[str, ...]] = ("compute_roi", "detect_objects", "check_planogram_compliance")
    _CYCLE_HOOKS: ClassVar[Tuple[str, ...]] = ("perceive", "identify", "compare")
    _LEGACY_PROMPTS: ClassVar[Tuple[str, ...]] = ("roi_detection_prompt", "object_identification_prompt")

    def __init__(
        self,
        pipeline: "PlanogramCompliance",
        config: "PlanogramConfig",
    ) -> None:
        self.pipeline = pipeline
        self.config = config
        self.logger = pipeline.logger
        self.validate_contract()

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
        raise NotImplementedError(f"{type(self).__name__} does not implement the legacy contract")

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
        raise NotImplementedError(f"{type(self).__name__} does not implement the legacy contract")

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
        raise NotImplementedError(f"{type(self).__name__} does not implement the legacy contract")

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
        raise NotImplementedError(f"{type(self).__name__} does not implement the legacy contract")

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
                state = feat[len(_ILLUMINATION_FEATURE_PREFIX) :].strip().lower()
                return state  # "on" or "off"
        return None

    async def _check_illumination(
        self,
        img: Image.Image,
        zone_bbox: Optional[Any] = None,
        roi: Optional[Any] = None,
        planogram_description: Optional[Any] = None,
    ) -> Optional[str]:
        """Check illumination state via LLM vision call on a cropped zone.

        Promoted from ``EndcapNoShelvesPromotional``. Crops ``zone_bbox``
        (pixel coords) if provided, falls back to ``roi.bbox`` (fractional
        coords), then the full image.  Sends a chain-of-thought prompt to
        Gemini Flash and parses ``LIGHT_ON`` / ``LIGHT_OFF`` from the response.

        Args:
            img: Full input PIL image.
            zone_bbox: Optional pixel-coordinate bbox of the illuminated zone.
                Must have ``.x1``, ``.y1``, ``.x2``, ``.y2`` float attributes.
            roi: Optional Detection with a ``.bbox`` attribute (fractional
                coords ``[0, 1]``).  Used as fallback when ``zone_bbox``
                is ``None``.
            planogram_description: Optional planogram description; used only to
                extract brand name for the LLM prompt hint.

        Returns:
            ``'illumination_status: ON'``, ``'illumination_status: OFF'``, or
            ``None`` on LLM failure.  A ``None`` return signals the caller
            to skip any illumination penalty rather than defaulting.
        """
        iw, ih = img.size

        if zone_bbox is not None:
            x1 = max(0, int(zone_bbox.x1))
            y1 = max(0, int(zone_bbox.y1))
            x2 = min(iw, int(zone_bbox.x2))
            y2 = min(ih, int(zone_bbox.y2))
            roi_crop = img.crop((x1, y1, x2, y2))
            self.logger.debug("Illumination check using zone crop (%d,%d,%d,%d)", x1, y1, x2, y2)
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
            async with self.pipeline.llm as client:
                msg = await client.ask_to_image(
                    image=roi_small,
                    prompt=prompt,
                    **self._vision_kwargs(),
                    max_tokens=128,
                )
            raw_answer = (msg.output or "").strip().upper()
        except Exception as exc:
            self.logger.warning("Illumination check failed: %s — returning None", exc)
            return None

        state = "illumination_status: OFF" if "LIGHT_OFF" in raw_answer else "illumination_status: ON"
        self.logger.info("Illumination check → answer=%r  state=%s", raw_answer, state)
        return state

    @staticmethod
    def _base_model_from_str(s: str, brand: str = None, patterns: Optional[List[str]] = None) -> str:
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

    # ------------------------------------------------------------------
    # Fact-tag shelf-boundary refinement (shared by all types)
    # ------------------------------------------------------------------

    def _cluster_fact_tag_rows(
        self,
        fact_tags: List[Any],
        cluster_threshold: int = 50,
    ) -> List[int]:
        """Group fact tags into horizontal rows by Y2 proximity.

        Returns a sorted list of Y values (one per row), representing the
        bottom edge of each price-tag row (i.e., the physical shelf board level).

        Args:
            fact_tags: List of IdentifiedProduct with ``detection_box`` attribute.
            cluster_threshold: Maximum Y-pixel gap to consider two tags on
                the same row.

        Returns:
            Sorted list of average Y2 values, one per cluster.
        """
        if not fact_tags:
            return []
        y2_vals = sorted(p.detection_box.y2 for p in fact_tags if p.detection_box is not None)
        clusters: List[List[int]] = [[y2_vals[0]]]
        for y in y2_vals[1:]:
            if y - clusters[-1][-1] <= cluster_threshold:
                clusters[-1].append(y)
            else:
                clusters.append([y])
        return [int(sum(c) / len(c)) for c in clusters]

    def _refine_shelves_from_fact_tags(
        self,
        shelf_regions: List[ShelfRegion],
        identified_products: List[Any],
    ) -> List[ShelfRegion]:
        """Refine non-header shelf boundaries using detected fact-tag row positions.

        Each fact-tag row marks the base (shelf board) of a product shelf.
        Products sit ABOVE their corresponding fact-tag row.  The refined zones
        are::

            shelf[0]: header_end -> row[0]
            shelf[1]: row[0]     -> row[1]
            shelf[2]: row[1]     -> row[2]
            ...

        When fewer rows are detected than needed, computes a shift correction
        from the first detected row vs. its static boundary and extrapolates
        the missing boundaries.  Falls back to static only when zero rows found.

        Args:
            shelf_regions: Current shelf regions (may contain background shelves).
            identified_products: All identified products including fact tags.

        Returns:
            Updated list of ShelfRegion with refined boundaries.
        """
        fact_tags = [p for p in identified_products if p.product_type == "fact_tag" and p.detection_box is not None]
        row_ys = self._cluster_fact_tag_rows(fact_tags)

        bg_shelves = [s for s in shelf_regions if getattr(s, "is_background", False)]
        fg_shelves = [s for s in shelf_regions if not getattr(s, "is_background", False)]

        if not row_ys or not fg_shelves:
            self.logger.info("use_fact_tag_boundaries: no fact-tag rows detected " "— keeping static boundaries")
            return shelf_regions

        if len(row_ys) < len(fg_shelves) - 1:
            static_first_y2 = fg_shelves[0].bbox.y2
            shift = row_ys[0] - static_first_y2
            self.logger.info(
                "use_fact_tag_boundaries: found %d fact-tag rows for %d shelves "
                "— extrapolating with shift=%+dpx (detected row=%d, "
                "static boundary=%d)",
                len(row_ys),
                len(fg_shelves),
                shift,
                row_ys[0],
                static_first_y2,
            )
            extrapolated = list(row_ys)
            for i in range(len(row_ys), len(fg_shelves) - 1):
                static_boundary = fg_shelves[i].bbox.y2
                extrapolated.append(int(static_boundary + shift))
            row_ys = extrapolated
        else:
            self.logger.info(
                "use_fact_tag_boundaries: refining %d shelves from fact-tag " "rows at y=%s",
                len(fg_shelves),
                row_ys,
            )

        r_x1 = shelf_regions[0].bbox.x1
        r_x2 = shelf_regions[0].bbox.x2
        r_y2 = shelf_regions[-1].bbox.y2

        prev_y = fg_shelves[0].bbox.y1

        new_fg: List[ShelfRegion] = []
        for i, shelf in enumerate(fg_shelves):
            base_y = row_ys[i] if i < len(row_ys) else r_y2
            new_fg.append(
                ShelfRegion(
                    shelf_id=shelf.shelf_id,
                    level=shelf.level,
                    bbox=DetectionBox(
                        x1=int(r_x1),
                        y1=int(prev_y),
                        x2=int(r_x2),
                        y2=int(base_y),
                        confidence=1.0,
                    ),
                    is_background=shelf.is_background,
                )
            )
            prev_y = base_y

        return bg_shelves + new_fg

    def _implements(self, name: str) -> bool:
        """Return True when the concrete class overrides ``name``."""
        return getattr(type(self), name, None) is not getattr(AbstractPlanogramType, name)

    def validate_contract(self) -> None:
        """Reject incomplete types and unusable configurations at construction.

        Raises:
            TypeError: The type supplies neither the complete legacy contract nor all cycle hooks.
            ValueError: A legacy type lacks a required prompt, or a type that requires a
                slots definition has none.
        """
        legacy = all(self._implements(n) for n in self._LEGACY_CONTRACT)
        cycle = all(self._implements(n) for n in self._CYCLE_HOOKS)
        if not (legacy or cycle):
            raise TypeError(
                f"Can't instantiate {type(self).__name__} with an incomplete planogram contract: implement the "
                f"abstract legacy contract {self._LEGACY_CONTRACT} or all cycle hooks {self._CYCLE_HOOKS}"
            )
        config_name = getattr(self.config, "config_name", None)
        if legacy and not cycle:
            for name in self._LEGACY_PROMPTS:
                if not getattr(self.config, name, None):
                    raise ValueError(
                        f"{type(self).__name__} (config {config_name!r}) uses the legacy contract and requires "
                        f"'{name}'; set it, or migrate the type as described in the FEAT-574 planogram cycle "
                        "migration runbook under docs/pipelines"
                    )
        if self.requires_slots_definition and getattr(self.config, "slots_definition", None) is None:
            raise ValueError(
                f"{type(self).__name__} (config {config_name!r}) requires a slots_definition; see the FEAT-574 "
                "planogram cycle migration runbook under docs/pipelines"
            )

    async def perceive(self, image: Image.Image, image_id: str, ctx: CycleContext) -> PerceptionResult:
        """Stage 1. Default: the complete legacy preparation + detection sequence (``detection_source='legacy_llm'``).

        Args:
            image: The opened image (enhanced for legacy types).
            image_id: Image identifier.
            ctx: Per-run context.

        Returns:
            The perception result (with a ``LegacyPayload`` on the legacy path).
        """
        from .legacy_adapter import legacy_perceive  # lazy: legacy_adapter imports this module

        return await legacy_perceive(self, image, image_id, ctx)

    async def identify(
        self, image: Image.Image, perception: PerceptionResult, ctx: CycleContext
    ) -> IdentificationResult:
        """Stage 2. Default: pass-through — legacy types identify during detection.

        Args:
            image: The opened image.
            perception: Stage-1 output.
            ctx: Per-run context.

        Returns:
            An empty identification result for the image.
        """
        return IdentificationResult(image_id=perception.image_id, identifications=[], added=[], errors=[])

    async def compare(
        self,
        perceptions: Sequence[PerceptionResult],
        identifications: Sequence[IdentificationResult],
        ctx: CycleContext,
    ) -> ComparisonResult:
        """Stage 3. Default: ``check_planogram_compliance`` on the first image's legacy payload.

        An empty result list is never a pass (the one intended deviation from the legacy ``run()``).

        Args:
            perceptions: Stage-1 outputs (the first one carries the legacy payload).
            identifications: Stage-2 outputs (unused on the legacy path).
            ctx: Per-run context.

        Returns:
            The comparison result with ``assessment_status=LEGACY_UNMEASURED``.
        """
        payload = perceptions[0].legacy if perceptions else None
        results: List[ComplianceResult] = []
        errors: List[str] = []
        if payload is None:
            errors.append("legacy compare: no legacy payload to evaluate")
        else:
            description = self.config.get_planogram_description()
            results = self.check_planogram_compliance(payload.identified_products, description)
        score = sum(r.compliance_score for r in results) / len(results) if results else 0.0
        compliant = bool(results) and all(r.compliance_status == ComplianceStatus.COMPLIANT for r in results)
        return ComparisonResult(
            compliance_results=results,
            position_results=[],
            shelf_scores=[],
            overall_compliance_score=score,
            strict_compliance_score=None,
            overall_compliant=compliant,
            coverage=None,
            definition_coverage=None,
            evidence_quality=None,
            assessment_status=AssessmentStatus.LEGACY_UNMEASURED,
            errors=errors,
        )

    def fallback_detection_prompt(self) -> Optional[str]:
        """Prompt for the LLM detector fallback; ``None`` selects the generic prompt."""
        return None

    def _vision_kwargs(self, **extra: Any) -> Dict[str, Any]:
        """Build the provider-neutral kwargs for an auxiliary ``ask_to_image`` call.

        Args:
            **extra: Additional keyword arguments merged into the result.

        Returns:
            ``{"no_memory": True, **extra}`` plus ``"model"`` when the pipeline's
            resolved backend pins a model id. When the backend leaves the model
            unset, ``"model"`` is omitted so the client's own default applies.
        """
        kwargs: Dict[str, Any] = {"no_memory": True, **extra}
        backend = getattr(self.pipeline, "resolved_backend", None)
        model = getattr(backend, "model", None)
        if isinstance(model, str) and model:
            kwargs["model"] = model
        return kwargs

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
