"""EndcapNoShelvesPromotional planogram type composable.

Handles planogram compliance for shelf-less promotional endcaps: a
retro-illuminated upper panel (brand/promo graphic) and a lower poster.
No physical products are expected — compliance is determined by verifying
that both zones are present and that the backlit panel is correctly
illuminated.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image

from .abstract import AbstractPlanogramType
from parrot.models.detections import (
    Detection,
    DetectionBox,
    BoundingBox,
    Detections,
    IdentifiedProduct,
    ShelfRegion,
)
from parrot.models.compliance import (
    ComplianceResult,
    ComplianceStatus,
    TextComplianceResult,
    TextMatcher,
)

# Default illumination penalty: 1.0 means illumination score → 0 when state contradicts config.
_DEFAULT_ILLUMINATION_PENALTY: float = 1.0

# Expected zone element labels for this display type.
_EXPECTED_ELEMENTS = ["backlit_panel", "lower_poster"]


class EndcapNoShelvesPromotional(AbstractPlanogramType):
    """Planogram type for shelf-less promotional endcap displays.

    Validates compliance for a display consisting of:
    - A retro-illuminated upper panel (backlit_panel) showing brand / promo graphics.
    - A lower poster (lower_poster) showing promotional content.

    There are no physical products.  Compliance is scored by zone presence
    and illumination state of the backlit panel.

    Args:
        pipeline: Parent PlanogramCompliance instance providing shared
            utilities (LLM clients, image helpers, config).
        config: The PlanogramConfig for this compliance run.
    """

    def __init__(self, pipeline: Any, config: Any) -> None:
        super().__init__(pipeline, config)

    # ------------------------------------------------------------------
    # Abstract method implementations
    # ------------------------------------------------------------------

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
        """Compute the region of interest by locating the promotional endcap.

        Uses the LLM to find the retro-illuminated upper panel and then
        expands the bounding box downward to encompass the full endcap
        (including the lower poster).

        Args:
            img: The input PIL image.

        Returns:
            Tuple of (endcap_detection, endcap_detection, None, None,
            raw_detections_list).  Returns (None, None, None, None, []) if
            the endcap cannot be found.
        """
        planogram_description = self.config.get_planogram_description()
        brand = (getattr(planogram_description, "brand", "") or "").strip()
        brand_hint = f" {brand}" if brand else ""

        partial_prompt = self.config.roi_detection_prompt or ""
        image_small = self.pipeline._downscale_image(img, max_side=1024, quality=78)

        prompt = partial_prompt or (
            f"Identify the full promotional endcap display in this{brand_hint} retail "
            "image.  Focus on the retro-illuminated upper panel.  Return a bounding box "
            "labeled 'endcap' that covers the complete endcap area from the top of the "
            "backlit panel down to the bottom of the lower poster."
        )

        max_attempts = 2
        msg = None
        for attempt in range(max_attempts):
            try:
                async with self.pipeline.roi_client as client:
                    msg = await client.ask_to_image(
                        image=image_small,
                        prompt=prompt,
                        model="gemini-2.5-flash",
                        no_memory=True,
                        structured_output=Detections,
                        max_tokens=8192,
                    )
                break
            except Exception as exc:
                if attempt < max_attempts - 1:
                    self.logger.warning(
                        "ROI detection attempt %d failed: %s; retrying…",
                        attempt + 1,
                        exc,
                    )
                    await asyncio.sleep(10)
                else:
                    self.logger.error(
                        "ROI detection failed after %d attempts: %s", max_attempts, exc
                    )
                    return None, None, None, None, []

        data = msg.structured_output or msg.output or {}

        # Pixel-coordinate recovery (same pattern as GraphicPanelDisplay)
        if isinstance(data, str):
            try:
                raw = json.loads(data)
                iw_s, ih_s = image_small.size
                for d in raw.get("detections", []):
                    b = d.get("bbox", {})
                    if any(
                        v > 1.0
                        for v in (
                            b.get("x1", 0),
                            b.get("y1", 0),
                            b.get("x2", 0),
                            b.get("y2", 0),
                        )
                    ):
                        b["x1"] = min(1.0, max(0.0, b.get("x1", 0) / iw_s))
                        b["y1"] = min(1.0, max(0.0, b.get("y1", 0) / ih_s))
                        b["x2"] = min(1.0, max(0.0, b.get("x2", 0) / iw_s))
                        b["y2"] = min(1.0, max(0.0, b.get("y2", 0) / ih_s))
                data = Detections(**raw)
                self.logger.info(
                    "Recovered ROI detections after normalizing pixel coordinates."
                )
            except Exception as parse_err:
                self.logger.warning("ROI coordinate recovery failed: %s", parse_err)
                return None, None, None, None, []

        dets = data.detections or []
        if not dets:
            self.logger.warning("No endcap ROI detected in image.")
            return None, None, None, None, []

        def _norm_label(det: Detection) -> str:
            return (det.label or "").strip().lower()

        endcap_det = next(
            (
                d
                for d in dets
                if _norm_label(d)
                in (
                    "endcap",
                    "endcap_roi",
                    "endcap-roi",
                    "promotional_endcap",
                    "backlit_panel",
                    "poster",
                    "poster_panel",
                )
            ),
            max(dets, key=lambda d: float(d.confidence)) if dets else None,
        )

        if not endcap_det:
            self.logger.error("Could not locate the promotional endcap boundary.")
            return None, None, None, None, []

        # Expand bbox downward to include the full endcap (lower poster)
        # The LLM may only detect the upper panel; extend y2 to cover the display.
        expanded_bbox = BoundingBox(
            x1=endcap_det.bbox.x1,
            y1=endcap_det.bbox.y1,
            x2=endcap_det.bbox.x2,
            y2=min(1.0, endcap_det.bbox.y2 + (endcap_det.bbox.y2 - endcap_det.bbox.y1)),
        )
        # Only expand if the detected box is small (< 50% height) — it likely
        # captured only the upper panel and missed the lower poster.
        bbox_height = endcap_det.bbox.y2 - endcap_det.bbox.y1
        if bbox_height < 0.5:
            endcap_det = Detection(
                label=endcap_det.label,
                confidence=endcap_det.confidence,
                bbox=expanded_bbox,
            )
            self.logger.info(
                "Expanded endcap ROI downward to include lower poster (height was %.2f).",
                bbox_height,
            )

        return endcap_det, endcap_det, None, None, dets

    async def detect_objects_roi(
        self,
        img: Image.Image,
        roi: Any,
    ) -> List[Detection]:
        """Detect the backlit panel and lower poster zones within the endcap ROI.

        Sends the cropped endcap area to the LLM and asks it to label the
        two expected zones (backlit_panel and lower_poster).

        Args:
            img: The input PIL image.
            roi: Endcap detection returned by ``compute_roi()``.

        Returns:
            List of Detection objects for each detected zone.
        """
        if roi is None:
            self.logger.warning("No ROI found — cannot detect endcap zones.")
            return []

        # Crop to ROI bbox
        iw, ih = img.size
        bbox = roi.bbox
        x1 = int(bbox.x1 * iw)
        y1 = int(bbox.y1 * ih)
        x2 = int(bbox.x2 * iw)
        y2 = int(bbox.y2 * ih)
        cropped = img.crop((x1, y1, x2, y2))

        prompt = (
            "Within this promotional endcap display, identify the following zones and "
            "return their bounding boxes:\n"
            "1) 'backlit_panel' — the upper retro-illuminated graphic panel (lightbox)\n"
            "2) 'lower_poster' — the promotional poster at the bottom of the display\n"
            "Return each detected zone with its label and bounding box."
        )
        image_small = self.pipeline._downscale_image(cropped, max_side=1024, quality=78)

        max_attempts = 2
        msg = None
        for attempt in range(max_attempts):
            try:
                async with self.pipeline.roi_client as client:
                    msg = await client.ask_to_image(
                        image=image_small,
                        prompt=prompt,
                        model="gemini-2.5-flash",
                        no_memory=True,
                        structured_output=Detections,
                        max_tokens=8192,
                    )
                break
            except Exception as exc:
                if attempt < max_attempts - 1:
                    self.logger.warning(
                        "Zone detection attempt %d failed: %s; retrying…",
                        attempt + 1,
                        exc,
                    )
                    await asyncio.sleep(10)
                else:
                    raise

        data = msg.structured_output or msg.output or {}

        # Pixel-coordinate recovery
        if isinstance(data, str):
            try:
                raw = json.loads(data)
                iw_s, ih_s = image_small.size
                for d in raw.get("detections", []):
                    b = d.get("bbox", {})
                    if any(
                        v > 1.0
                        for v in (
                            b.get("x1", 0),
                            b.get("y1", 0),
                            b.get("x2", 0),
                            b.get("y2", 0),
                        )
                    ):
                        b["x1"] = min(1.0, max(0.0, b.get("x1", 0) / iw_s))
                        b["y1"] = min(1.0, max(0.0, b.get("y1", 0) / ih_s))
                        b["x2"] = min(1.0, max(0.0, b.get("x2", 0) / iw_s))
                        b["y2"] = min(1.0, max(0.0, b.get("y2", 0) / ih_s))
                data = Detections(**raw)
                self.logger.info(
                    "Recovered zone detections after normalizing pixel coordinates."
                )
            except Exception as parse_err:
                self.logger.warning(
                    "Zone coordinate recovery failed: %s", parse_err
                )
                return []

        return data.detections or []

    async def detect_objects(
        self,
        img: Image.Image,
        roi: Any,
        macro_objects: Any,
    ) -> Tuple[List[IdentifiedProduct], List[ShelfRegion]]:
        """Detect zone presence and illumination state from config-defined zones.

        Reads zones from ``config.planogram_config["shelves"]``.  For each zone
        that declares ``illumination_status`` in its ``visual_features`` config,
        calls ``_check_illumination`` once (result cached across zones).

        Args:
            img: The input PIL image.
            roi: ROI detection from ``compute_roi()``.
            macro_objects: Unused — identity is determined from config labels.

        Returns:
            Tuple of (identified_products, shelf_regions), one entry per
            configured zone.
        """
        planogram_description = self.config.get_planogram_description()
        pcfg = getattr(self.config, "planogram_config", {}) or {}
        shelves = pcfg.get("shelves") or [
            {
                "level": "backlit_panel",
                "products": [
                    {"name": "backlit_panel", "visual_features": ["illumination_status: ON"]},
                ],
            },
            {
                "level": "lower_poster",
                "products": [
                    {"name": "lower_poster", "visual_features": []},
                ],
            },
        ]

        iw, ih = img.size
        identified_products: List[IdentifiedProduct] = []
        shelf_regions: List[ShelfRegion] = []

        # Illumination state is evaluated at most once per image (one LLM call).
        roi_illumination: Optional[str] = None

        for shelf_idx, shelf_cfg in enumerate(shelves):
            if isinstance(shelf_cfg, dict):
                shelf_level = shelf_cfg.get("level", f"zone_{shelf_idx}")
                products_cfg = shelf_cfg.get("products") or []
                y_start = float(shelf_cfg.get("y_start_ratio", 0.0))
                height = float(shelf_cfg.get("height_ratio", 1.0))
            else:
                shelf_level = getattr(shelf_cfg, "level", f"zone_{shelf_idx}")
                products_cfg = getattr(shelf_cfg, "products", None) or []
                y_start = float(getattr(shelf_cfg, "y_start_ratio", 0.0))
                height = float(getattr(shelf_cfg, "height_ratio", 1.0))

            # Zone bbox in pixel coordinates for OCR enrichment in plan.py.
            zone_bbox = DetectionBox(
                x1=0,
                y1=int(ih * y_start),
                x2=iw,
                y2=min(ih, int(ih * (y_start + height))),
                confidence=0.0,
            )

            for prod_cfg in products_cfg:
                if isinstance(prod_cfg, dict):
                    prod_name = prod_cfg.get("name", "")
                    prod_visual_features = prod_cfg.get("visual_features") or []
                    prod_type = prod_cfg.get("product_type", "graphic_zone") or "graphic_zone"
                    prod_illum_required = prod_cfg.get("illumination_required")
                else:
                    prod_name = getattr(prod_cfg, "name", "")
                    prod_visual_features = getattr(prod_cfg, "visual_features", None) or []
                    prod_type = getattr(prod_cfg, "product_type", "graphic_zone") or "graphic_zone"
                    prod_illum_required = getattr(prod_cfg, "illumination_required", None)

                # illumination_required takes priority; fall back to scanning visual_features
                # for backwards-compatibility with configs that still use illumination_status:.
                if prod_illum_required is not None:
                    zone_has_illum = True
                else:
                    zone_has_illum = any(
                        f.lower().startswith("illumination_status:")
                        for f in prod_visual_features
                    )

                visual_features: List[str] = []

                if zone_has_illum:
                    # Evaluate illumination once per image (cache result).
                    if roi_illumination is None:
                        roi_illumination = await self._check_illumination(
                            img, roi, planogram_description, illum_zone_bbox=zone_bbox
                        )
                    # Seed first so _extract_illumination_state uses first-match.
                    visual_features = [roi_illumination]
                    self.logger.debug(
                        "Zone '%s': illumination_state=%s", prod_name, roi_illumination
                    )

                product = IdentifiedProduct(
                    product_model=prod_name,
                    product_type=prod_type,
                    shelf_location=shelf_level,
                    confidence=0.5,
                    brand=getattr(planogram_description, "brand", None),
                    visual_features=visual_features,
                    detection_box=zone_bbox,
                )
                identified_products.append(product)

            shelf_regions.append(
                ShelfRegion(
                    shelf_id=f"{shelf_level}_{shelf_idx}",
                    bbox=DetectionBox(x1=0, y1=0, x2=iw, y2=ih, confidence=0.0),
                    level=shelf_level,
                    detections=[],
                )
            )

        self.logger.info(
            "EndcapNoShelvesPromotional.detect_objects: %d products from %d shelves",
            len(identified_products),
            len(shelves),
        )
        return identified_products, shelf_regions

    def _generate_virtual_shelves(
        self,
        roi_bbox: Any,
        image_size: Any,
        planogram: Any,
    ) -> List[ShelfRegion]:
        """No-op — shelf regions are produced by detect_objects from config zones."""
        return []

    def _assign_products_to_shelves(self, *args: Any, **kwargs: Any) -> None:
        """No-op — products are already assigned to zones in detect_objects."""
        return

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
                    model="gemini-2.5-flash",
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

    def check_planogram_compliance(
        self,
        identified_products: List[IdentifiedProduct],
        planogram_description: Any,
    ) -> List[ComplianceResult]:
        """Score compliance per config-defined zone.

        Iterates over ``planogram_config["shelves"]``, matching each zone to
        its detected ``IdentifiedProduct`` by ``shelf_location``.  Applies
        illumination penalty and text-requirement checks per zone.

        Status rules:
        - Zone absent (confidence=0 or not in products) → ``MISSING``
        - Zone found, illumination wrong → ``NON_COMPLIANT``
        - Zone found, illumination correct (or not configured) → ``COMPLIANT``

        Args:
            identified_products: Zone products from ``detect_objects()``.
            planogram_description: Expected planogram layout from config.

        Returns:
            List of ComplianceResult, one per shelf/zone level.
        """
        pcfg = getattr(self.config, "planogram_config", {}) or {}
        shelves = pcfg.get("shelves") or [
            {
                "level": "backlit_panel",
                "products": [
                    {"name": "backlit_panel", "visual_features": ["illumination_status: ON"],
                     "mandatory": True, "compliance_threshold": 0.8},
                ],
            },
            {
                "level": "lower_poster",
                "products": [
                    {"name": "lower_poster", "visual_features": [],
                     "mandatory": True, "compliance_threshold": 0.8},
                ],
            },
        ]
        global_threshold = (
            getattr(planogram_description, "global_compliance_threshold", None) or 0.8
        )

        # Index products by shelf_location for O(1) lookup
        by_shelf: Dict[str, List[IdentifiedProduct]] = {}
        for p in identified_products:
            by_shelf.setdefault(p.shelf_location, []).append(p)

        results: List[ComplianceResult] = []

        for shelf_cfg in shelves:
            if isinstance(shelf_cfg, dict):
                shelf_level = shelf_cfg.get("level", "")
                products_cfg = shelf_cfg.get("products") or []
                shelf_threshold = shelf_cfg.get("compliance_threshold", global_threshold)
            else:
                shelf_level = getattr(shelf_cfg, "level", "")
                products_cfg = getattr(shelf_cfg, "products", None) or []
                shelf_threshold = getattr(shelf_cfg, "compliance_threshold", global_threshold)
            if shelf_threshold is None:
                shelf_threshold = global_threshold

            products_on_shelf = by_shelf.get(shelf_level, [])
            expected_names: List[str] = []
            found_names: List[str] = []
            missing: List[str] = []
            text_results: List[TextComplianceResult] = []
            zone_scores: List[float] = []
            text_score = 1.0
            overall_text_ok = True

            for prod_idx, prod_cfg in enumerate(products_cfg):
                if isinstance(prod_cfg, dict):
                    prod_name = prod_cfg.get("name", "")
                    prod_visual_features = prod_cfg.get("visual_features") or []
                    prod_mandatory = prod_cfg.get("mandatory", True)
                    prod_text_requirements = prod_cfg.get("text_requirements") or []
                    prod_illum_penalty = prod_cfg.get("illumination_penalty", None)
                    prod_illum_required = prod_cfg.get("illumination_required")
                else:
                    prod_name = getattr(prod_cfg, "name", "")
                    prod_visual_features = getattr(prod_cfg, "visual_features", None) or []
                    prod_mandatory = getattr(prod_cfg, "mandatory", True)
                    prod_text_requirements = getattr(prod_cfg, "text_requirements", None) or []
                    prod_illum_penalty = getattr(prod_cfg, "illumination_penalty", None)
                    prod_illum_required = getattr(prod_cfg, "illumination_required", None)

                expected_names.append(prod_name)

                detected = (
                    products_on_shelf[prod_idx]
                    if prod_idx < len(products_on_shelf)
                    else None
                )
                zone_found = detected is not None and detected.confidence > 0.0

                if zone_found:
                    found_names.append(prod_name)
                else:
                    missing.append(prod_name)

                zone_score = 1.0 if zone_found else 0.0

                # ----------------------------------------------------------
                # Illumination check
                # illumination_required field takes priority over scanning
                # visual_features for backwards-compatibility.
                # ----------------------------------------------------------
                if prod_illum_required is not None:
                    expected_illum: Optional[str] = str(prod_illum_required).strip().lower()
                else:
                    expected_illum = self._extract_illumination_state(prod_visual_features)

                if zone_found and expected_illum is not None:
                    detected_features = (
                        detected.visual_features if detected else []
                    ) or []
                    detected_illum = self._extract_illumination_state(detected_features)
                    if detected_illum is not None and detected_illum != expected_illum:
                        penalty = float(max(0.0, min(1.0,
                            prod_illum_penalty
                            if prod_illum_penalty is not None
                            else _DEFAULT_ILLUMINATION_PENALTY
                        )))
                        zone_score *= (1.0 - penalty)
                        self.logger.debug(
                            "Illumination mismatch on zone '%s': expected=%s "
                            "detected=%s penalty=%s → score=%.3f",
                            prod_name, expected_illum, detected_illum,
                            penalty, zone_score,
                        )
                        # Replace the found_name with one that reflects actual state
                        actual_label = f"{prod_name} (LIGHT_{detected_illum.upper()})"
                        if found_names and found_names[-1] == prod_name:
                            found_names[-1] = actual_label
                        missing.append(
                            f"{prod_name} — backlight {detected_illum.upper()} "
                                f"(required: {expected_illum.upper()})"
                            )

                # ----------------------------------------------------------
                # Text requirements check
                # ----------------------------------------------------------
                text_score = 1.0
                overall_text_ok = True
                if zone_found and prod_text_requirements:
                    detected_features = (
                        detected.visual_features if detected else []
                    ) or []
                    for text_req in prod_text_requirements:
                        if isinstance(text_req, dict):
                            req_text = text_req.get("required_text", "")
                            match_type = text_req.get("match_type", "contains")
                            case_sensitive = text_req.get("case_sensitive", False)
                            conf_threshold = text_req.get("confidence_threshold", 0.8)
                            req_mandatory = text_req.get("mandatory", True)
                        else:
                            req_text = getattr(text_req, "required_text", "")
                            match_type = getattr(text_req, "match_type", "contains")
                            case_sensitive = getattr(text_req, "case_sensitive", False)
                            conf_threshold = getattr(text_req, "confidence_threshold", 0.8)
                            req_mandatory = getattr(text_req, "mandatory", True)
                        tr = TextMatcher.check_text_match(
                            required_text=req_text,
                            visual_features=detected_features,
                            match_type=match_type,
                            case_sensitive=case_sensitive,
                            confidence_threshold=conf_threshold,
                        )
                        text_results.append(tr)
                        if not tr.found and req_mandatory:
                            overall_text_ok = False
                    if text_results:
                        text_score = sum(
                            r.confidence for r in text_results if r.found
                        ) / len(text_results)

                # Optional zones that are absent don't penalise the shelf score
                effective_score = zone_score if (zone_found or prod_mandatory) else 1.0
                zone_scores.append(effective_score)

            combined_score = (
                sum(zone_scores) / len(zone_scores) if zone_scores else 0.0
            )
            combined_score = min(1.0, max(0.0, combined_score))

            # MISSING only when no zone was actually detected; NON_COMPLIANT
            # when something was found but failed illumination/text checks.
            has_found = len(found_names) > 0
            if combined_score >= shelf_threshold:
                status = ComplianceStatus.COMPLIANT
            elif not has_found:
                status = ComplianceStatus.MISSING
            else:
                status = ComplianceStatus.NON_COMPLIANT

            self.logger.info(
                "EndcapNoShelvesPromotional compliance zone=%s score=%.3f "
                "status=%s missing=%s",
                shelf_level, combined_score, status, missing,
            )

            results.append(
                ComplianceResult(
                    shelf_level=shelf_level,
                    expected_products=expected_names,
                    found_products=found_names,
                    missing_products=missing,
                    unexpected_products=[],
                    compliance_status=status,
                    compliance_score=round(combined_score, 4),
                    text_compliance_results=text_results,
                    text_compliance_score=min(
                        1.0, max(0.0, text_score if text_results else 1.0)
                    ),
                    overall_text_compliant=overall_text_ok,
                    brand_compliance_result=None,
                )
            )

        return results
