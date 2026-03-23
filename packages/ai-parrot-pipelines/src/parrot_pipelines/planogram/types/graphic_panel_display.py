"""GraphicPanelDisplay planogram type composable.

Handles planogram compliance for graphic-panel / signage endcap displays
(EcoTank endcaps, projector displays, Bose audio displays, etc.).

These displays contain no physical products — compliance is determined by
verifying that the correct graphic zones are present in the correct
positions, with the correct text content and (where applicable) the
correct illumination state.
"""
import asyncio
import json
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image

from .abstract import AbstractPlanogramType
from parrot.models.detections import (
    Detection,
    BoundingBox,
    Detections,
    ShelfRegion,
    IdentifiedProduct,
)
from parrot.models.compliance import (
    ComplianceResult,
    TextComplianceResult,
    ComplianceStatus,
    TextMatcher,
)

# Default illumination penalty: 1.0 means zone score → 0 when state contradicts config.
_DEFAULT_ILLUMINATION_PENALTY: float = 1.0

# Key prefix used in visual_features to declare expected illumination state.
_ILLUMINATION_FEATURE_PREFIX = "illumination_status:"


class GraphicPanelDisplay(AbstractPlanogramType):
    """Composable type for graphic-panel / signage endcap compliance.

    Handles displays where compliance is based on the presence, text
    content, and illumination state of named graphic zones — not on
    physical product counting or fact-tag detection.

    Each shelf level in the planogram config maps to one named graphic
    zone (e.g., header → top graphic, middle → comparison table,
    bottom → special offer panel).  The LLM is asked to detect those
    zones via the ``roi_detection_prompt`` defined in the DB config, so
    no changes to the DB schema are needed.

    Args:
        pipeline: Parent PlanogramCompliance instance.
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
        """Compute the region of interest by locating the graphic endcap boundary.

        Reuses the same LLM ROI prompt logic as ``ProductOnShelves`` —
        the ``roi_detection_prompt`` stored in the DB config already
        describes the endcap shape and the model should return an
        ``endcap`` or ``poster_panel`` detection bounding the whole display.

        Args:
            img: The input PIL image.

        Returns:
            Tuple of (endcap_detection, panel_detection, brand_detection,
            text_detection, raw_detections_list).
        """
        planogram_description = self.config.get_planogram_description()
        return await self._find_display_roi(img, planogram_description)

    async def detect_objects_roi(
        self,
        img: Image.Image,
        roi: Any,
    ) -> List[Detection]:
        """Detect named graphic zones within the endcap ROI.

        Sends the cropped ROI image to the LLM using the planogram's
        ``roi_detection_prompt``.  The prompt should instruct the model to
        label zones (e.g. ``top_zone``, ``middle_zone``, ``bottom_zone``)
        corresponding to the graphic panels on the display.

        Args:
            img: The input PIL image.
            roi: ROI detection returned by ``compute_roi()``.

        Returns:
            List of Detection objects for each detected graphic zone.
        """
        planogram_description = self.config.get_planogram_description()
        endcap_det = roi  # roi is the endcap Detection from compute_roi

        if endcap_det is None:
            self.logger.warning("No ROI found — cannot detect graphic zones.")
            return []

        # Crop the image to the ROI bbox
        iw, ih = img.size
        bbox = endcap_det.bbox
        x1 = int(bbox.x1 * iw)
        y1 = int(bbox.y1 * ih)
        x2 = int(bbox.x2 * iw)
        y2 = int(bbox.y2 * ih)
        cropped = img.crop((x1, y1, x2, y2))

        prompt = self.config.roi_detection_prompt or (
            "Identify all graphic zones in this display. "
            "Label each zone (top_zone, middle_zone, bottom_zone, etc.) "
            "and return its bounding box."
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
                        f"Zone detection attempt {attempt + 1} failed: {exc}; retrying…"
                    )
                    await asyncio.sleep(10)
                else:
                    raise

        data = msg.structured_output or msg.output or {}

        # Pixel-coordinate recovery (same pattern as ProductOnShelves)
        if isinstance(data, str):
            try:
                raw = json.loads(data)
                iw_s, ih_s = image_small.size
                for d in raw.get("detections", []):
                    b = d.get("bbox", {})
                    if any(v > 1.0 for v in (b.get("x1", 0), b.get("y1", 0),
                                             b.get("x2", 0), b.get("y2", 0))):
                        b["x1"] = min(1.0, max(0.0, b.get("x1", 0) / iw_s))
                        b["y1"] = min(1.0, max(0.0, b.get("y1", 0) / ih_s))
                        b["x2"] = min(1.0, max(0.0, b.get("x2", 0) / iw_s))
                        b["y2"] = min(1.0, max(0.0, b.get("y2", 0) / ih_s))
                data = Detections(**raw)
                self.logger.info("Recovered zone detections after normalizing pixel coordinates.")
            except Exception as parse_err:
                self.logger.warning(f"Zone coordinate recovery failed: {parse_err}")
                return []

        return data.detections or []

    async def detect_objects(
        self,
        img: Image.Image,
        roi: Any,
        macro_objects: Any,
    ) -> Tuple[List[IdentifiedProduct], List[ShelfRegion]]:
        """OCR + visual feature verification for each detected graphic zone.

        Maps LLM-detected zone labels (e.g. ``top_zone``) to the planogram
        config product names (e.g. ``Epson_Top_Not_Backlit``) by position
        order within each shelf level.  Then runs OCR / visual enrichment
        on each zone and checks illumination state where the config
        specifies ``illumination_status`` in ``visual_features``.

        Args:
            img: The input PIL image.
            roi: Endcap detection from ``compute_roi()``.
            macro_objects: Zone detections from ``detect_objects_roi()``.

        Returns:
            Tuple of (identified_products, shelf_regions).  One
            ``IdentifiedProduct`` per detected zone, one ``ShelfRegion``
            per shelf level.
        """
        planogram_description = self.config.get_planogram_description()
        zone_detections: List[Detection] = macro_objects or []
        shelves = planogram_description.shelves or []

        identified_products: List[IdentifiedProduct] = []
        shelf_regions: List[ShelfRegion] = []

        # Sort zone detections top-to-bottom so positional mapping is stable.
        sorted_zones = sorted(
            zone_detections,
            key=lambda d: (d.bbox.y1 + d.bbox.y2) / 2.0
        )

        for shelf_idx, shelf_cfg in enumerate(shelves):
            shelf_level = shelf_cfg.level
            products_cfg = shelf_cfg.products or []

            # Map: one zone detection per configured product (by position order)
            for prod_idx, prod_cfg in enumerate(products_cfg):
                zone_det: Optional[Detection] = None
                if prod_idx < len(sorted_zones):
                    zone_det = sorted_zones[prod_idx]

                visual_features: List[str] = []

                if zone_det is not None:
                    # Run OCR + visual enrichment on the zone crop
                    visual_features = await self._enrich_zone(
                        img=img,
                        zone_det=zone_det,
                        roi=roi,
                        prod_cfg=prod_cfg,
                        planogram_description=planogram_description,
                    )

                product = IdentifiedProduct(
                    product_model=prod_cfg.name,
                    product_type="graphic_zone",
                    shelf_location=shelf_level,
                    confidence=zone_det.confidence if zone_det else 0.0,
                    brand=getattr(planogram_description, "brand", None),
                    visual_features=visual_features,
                )
                identified_products.append(product)

            shelf_regions.append(
                ShelfRegion(
                    level=shelf_level,
                    detections=[p.detection_box for p in identified_products
                                if p.shelf_location == shelf_level
                                and p.detection_box is not None],
                )
            )

        return identified_products, shelf_regions

    def check_planogram_compliance(
        self,
        identified_products: List[IdentifiedProduct],
        planogram_description: Any,
    ) -> List[ComplianceResult]:
        """Compare detected graphic zones against the expected planogram layout.

        For each shelf level (zone):
        - Checks zone presence (confidence > 0 → found).
        - Evaluates text requirements from ``visual_features`` (same mechanism
          as ``ProductOnShelves``).
        - Applies illumination check: if ``illumination_status`` is in the
          config's ``visual_features`` and the detected state contradicts
          the expected state, applies the configurable ``illumination_penalty``
          to the zone score (default: 1.0 → score becomes 0).

        No fact-tag, physical product counting, or brand-logo logic is run.

        Args:
            identified_products: Zone products detected by ``detect_objects()``.
            planogram_description: Expected planogram layout from config.

        Returns:
            List of ComplianceResult, one per shelf/zone.
        """
        by_shelf: Dict[str, List[IdentifiedProduct]] = {}
        for p in identified_products:
            by_shelf.setdefault(p.shelf_location, []).append(p)

        results: List[ComplianceResult] = []

        for shelf_cfg in planogram_description.shelves:
            shelf_level = shelf_cfg.level
            products_on_shelf = by_shelf.get(shelf_level, [])
            products_cfg = shelf_cfg.products or []

            expected_names: List[str] = [p.name for p in products_cfg]
            found_names: List[str] = []
            missing: List[str] = []
            text_results: List[TextComplianceResult] = []

            zone_scores: List[float] = []

            for prod_idx, prod_cfg in enumerate(products_cfg):
                detected = (
                    products_on_shelf[prod_idx]
                    if prod_idx < len(products_on_shelf)
                    else None
                )

                zone_found = detected is not None and detected.confidence > 0.0

                if zone_found:
                    found_names.append(prod_cfg.name)
                else:
                    missing.append(prod_cfg.name)

                # Base zone score: 1.0 if found, 0.0 if missing
                zone_score = 1.0 if zone_found else 0.0

                # ----------------------------------------------------------
                # Illumination check (configurable penalty)
                # ----------------------------------------------------------
                if zone_found and prod_cfg.visual_features:
                    expected_illum = self._extract_illumination_state(
                        prod_cfg.visual_features
                    )
                    if expected_illum is not None:
                        detected_features = (
                            detected.visual_features if detected else []
                        ) or []
                        detected_illum = self._extract_illumination_state(
                            detected_features
                        )
                        if detected_illum is not None and detected_illum != expected_illum:
                            penalty = self._get_illumination_penalty(shelf_cfg)
                            zone_score *= (1.0 - penalty)
                            self.logger.debug(
                                f"Illumination mismatch on zone '{prod_cfg.name}': "
                                f"expected={expected_illum}, detected={detected_illum}, "
                                f"penalty={penalty} → zone_score={zone_score:.3f}"
                            )

                # ----------------------------------------------------------
                # Text requirement check
                # ----------------------------------------------------------
                text_score = 1.0
                overall_text_ok = True
                if zone_found and getattr(prod_cfg, "text_requirements", None):
                    detected_features = (
                        detected.visual_features if detected else []
                    ) or []
                    for text_req in prod_cfg.text_requirements:
                        result = TextMatcher.check_text_match(
                            required_text=text_req.required_text,
                            visual_features=detected_features,
                            match_type=text_req.match_type,
                            case_sensitive=text_req.case_sensitive,
                            confidence_threshold=text_req.confidence_threshold,
                        )
                        text_results.append(result)
                        if not result.found and text_req.mandatory:
                            overall_text_ok = False
                    if text_results:
                        text_score = sum(
                            r.confidence for r in text_results if r.found
                        ) / len(text_results)

                zone_scores.append(zone_score)

            # Aggregate score across all zones in this shelf
            combined_score = (
                sum(zone_scores) / len(zone_scores) if zone_scores else 0.0
            )
            combined_score = min(1.0, max(0.0, combined_score))

            threshold = getattr(
                shelf_cfg,
                "compliance_threshold",
                planogram_description.global_compliance_threshold or 0.8,
            )

            if combined_score >= threshold:
                status = ComplianceStatus.COMPLIANT
            elif combined_score == 0.0 and expected_names:
                status = ComplianceStatus.MISSING
            else:
                status = ComplianceStatus.NON_COMPLIANT

            results.append(
                ComplianceResult(
                    shelf_level=shelf_level,
                    expected_products=expected_names,
                    found_products=found_names,
                    missing_products=missing,
                    unexpected_products=[],  # no unexpected logic for graphic panels
                    compliance_status=status,
                    compliance_score=combined_score,
                    text_compliance_results=text_results,
                    text_compliance_score=min(1.0, max(0.0, text_score if text_results else 1.0)),
                    overall_text_compliant=overall_text_ok,
                    brand_compliance_result=None,
                )
            )

        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _find_display_roi(
        self,
        image: Image.Image,
        planogram_description: Any,
    ) -> Tuple[Optional[Any], Optional[Any], None, None, List[Any]]:
        """Locate the endcap boundary using the LLM ROI prompt.

        Mirrors the logic of ``ProductOnShelves._find_poster()`` but
        simplified: we only need the endcap bounding box, not poster/brand/
        text sub-detections.

        Args:
            image: The input PIL image.
            planogram_description: Planogram config description.

        Returns:
            Tuple of (endcap_detection, endcap_detection, None, None, raw_dets).
        """
        partial_prompt = self.config.roi_detection_prompt or ""
        brand = (getattr(planogram_description, "brand", "") or "").strip()
        tags = [t.strip() for t in getattr(planogram_description, "tags", []) or []]
        tag_hint = ", ".join(sorted({f"'{t}'" for t in tags if t}))

        image_small = self.pipeline._downscale_image(image, max_side=1024, quality=78)
        prompt = partial_prompt.format(
            brand=brand,
            tag_hint=tag_hint,
            image_size=image_small.size,
        ) if partial_prompt else (
            f"Find the complete endcap display boundary for a {brand} graphic panel. "
            "Return a bounding box labeled 'endcap' that covers the full display."
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
                        f"ROI detection attempt {attempt + 1} failed: {exc}; retrying…"
                    )
                    await asyncio.sleep(10)
                else:
                    raise

        data = msg.structured_output or msg.output or {}

        # Pixel-coordinate recovery (same as ProductOnShelves)
        if isinstance(data, str):
            try:
                raw = json.loads(data)
                iw, ih = image_small.size
                for d in raw.get("detections", []):
                    b = d.get("bbox", {})
                    if any(v > 1.0 for v in (b.get("x1", 0), b.get("y1", 0),
                                             b.get("x2", 0), b.get("y2", 0))):
                        b["x1"] = min(1.0, max(0.0, b.get("x1", 0) / iw))
                        b["y1"] = min(1.0, max(0.0, b.get("y1", 0) / ih))
                        b["x2"] = min(1.0, max(0.0, b.get("x2", 0) / iw))
                        b["y2"] = min(1.0, max(0.0, b.get("y2", 0) / ih))
                data = Detections(**raw)
                self.logger.info("Recovered Step 1 detections after normalizing pixel coordinates.")
            except Exception as parse_err:
                self.logger.warning(f"Step 1 coordinate recovery failed: {parse_err}")
                return None, None, None, None, []

        dets = data.detections or []
        if not dets:
            return None, None, None, None, []

        def _norm_label(det: Detection) -> str:
            return (det.label or "").strip().lower()

        # Prefer explicit endcap label; fall back to highest-confidence detection.
        endcap_det = next(
            (d for d in dets if _norm_label(d) in ("endcap", "endcap_roi", "endcap-roi", "poster_panel", "poster")),
            max(dets, key=lambda d: float(d.confidence)) if dets else None,
        )

        if not endcap_det:
            self.logger.error("Could not detect the display endcap boundary.")
            return None, None, None, None, []

        return endcap_det, endcap_det, None, None, dets

    async def _enrich_zone(
        self,
        img: Image.Image,
        zone_det: Detection,
        roi: Any,
        prod_cfg: Any,
        planogram_description: Any,
    ) -> List[str]:
        """Run OCR + visual enrichment on a graphic zone.

        Crops the zone from the (already ROI-cropped) image and asks the
        LLM to verify text and visual features.  Returns the list of
        confirmed ``visual_features`` strings (e.g.
        ``["illumination_status: OFF", "ocr: EcoTank"]``).

        Args:
            img: The full input PIL image.
            zone_det: The Detection for this zone (normalized to ROI space).
            roi: The endcap Detection (provides the ROI bbox offset).
            prod_cfg: The config entry for this zone/product.
            planogram_description: Full planogram description for context.

        Returns:
            List of confirmed visual feature strings.
        """
        # Determine absolute bbox from ROI-relative zone detection
        iw, ih = img.size
        if roi is not None:
            roi_x1 = roi.bbox.x1 * iw
            roi_y1 = roi.bbox.y1 * ih
            roi_x2 = roi.bbox.x2 * iw
            roi_y2 = roi.bbox.y2 * ih
            roi_w = roi_x2 - roi_x1
            roi_h = roi_y2 - roi_y1
        else:
            roi_x1, roi_y1, roi_w, roi_h = 0.0, 0.0, float(iw), float(ih)

        abs_x1 = int(roi_x1 + zone_det.bbox.x1 * roi_w)
        abs_y1 = int(roi_y1 + zone_det.bbox.y1 * roi_h)
        abs_x2 = int(roi_x1 + zone_det.bbox.x2 * roi_w)
        abs_y2 = int(roi_y1 + zone_det.bbox.y2 * roi_h)

        # Clamp to image
        abs_x1 = max(0, min(abs_x1, iw))
        abs_y1 = max(0, min(abs_y1, ih))
        abs_x2 = max(abs_x1 + 1, min(abs_x2, iw))
        abs_y2 = max(abs_y1 + 1, min(abs_y2, ih))

        zone_crop = img.crop((abs_x1, abs_y1, abs_x2, abs_y2))
        zone_small = self.pipeline._downscale_image(zone_crop, max_side=512, quality=78)

        expected_features = getattr(prod_cfg, "visual_features", []) or []
        brand = (getattr(planogram_description, "brand", "") or "").strip()
        zone_name = prod_cfg.name

        features_hint = (
            "Expected visual features: " + ", ".join(f"'{f}'" for f in expected_features)
            if expected_features
            else ""
        )
        prompt = (
            f"This is the '{zone_name}' graphic zone of a {brand} endcap display. "
            f"{features_hint}\n\n"
            "Please verify:\n"
            "1. What text is visible? (prefix with 'ocr:')\n"
            "2. Is this zone illuminated (backlit/lit) or not? "
            "   (respond with 'illumination_status: ON' or 'illumination_status: OFF')\n"
            "3. Any other notable visual features.\n\n"
            "Return a JSON list of strings, e.g.: "
            '["illumination_status: OFF", "ocr: EcoTank", "graphic_visible: true"]'
        )

        visual_features: List[str] = []
        try:
            async with self.pipeline.roi_client as client:
                msg = await client.ask_to_image(
                    image=zone_small,
                    prompt=prompt,
                    model="gemini-2.5-flash",
                    no_memory=True,
                    max_tokens=512,
                )
            raw_output = msg.output or ""
            # Extract JSON list from the response
            import re
            match = re.search(r'\[.*?\]', raw_output, re.DOTALL)
            if match:
                visual_features = json.loads(match.group(0))
                if not isinstance(visual_features, list):
                    visual_features = []
        except Exception as exc:
            self.logger.warning(
                f"Zone enrichment failed for '{zone_name}': {exc}"
            )

        return visual_features

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

    @staticmethod
    def _get_illumination_penalty(shelf_cfg: Any) -> float:
        """Read the configurable illumination penalty from a shelf config.

        The penalty is read from ``shelf_cfg.illumination_penalty`` if set.
        Defaults to 1.0 (full deduction → score becomes 0).

        Args:
            shelf_cfg: Shelf configuration object from ``PlanogramConfig``.

        Returns:
            Penalty weight in [0.0, 1.0].
        """
        penalty = getattr(shelf_cfg, "illumination_penalty", None)
        if penalty is None:
            # Also check first product in shelf for per-product config
            products = getattr(shelf_cfg, "products", []) or []
            if products:
                penalty = getattr(products[0], "illumination_penalty", None)
        if penalty is None:
            penalty = _DEFAULT_ILLUMINATION_PENALTY
        return float(max(0.0, min(1.0, penalty)))
