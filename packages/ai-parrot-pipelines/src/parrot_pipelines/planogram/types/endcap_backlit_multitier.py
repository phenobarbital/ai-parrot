"""EndcapBacklitMultitier planogram type composable.

Handles planogram compliance for backlit multi-tier endcap displays: a
retro-illuminated header panel (lightbox) combined with one or more product
shelves.  Shelves may be sub-divided into named sections detected in parallel.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image

from .abstract import AbstractPlanogramType
from parrot.models.google import GoogleModel
from parrot.models.detections import (
    BoundingBox,
    Detection,
    DetectionBox,
    Detections,
    IdentifiedProduct,
    SectionRegion,
    ShelfRegion,
    ShelfSection,
)
from parrot.models.compliance import (
    ComplianceResult,
    ComplianceStatus,
)

# Default fractional padding added to each section boundary when
# ``shelf.section_padding`` is not explicitly set.
_DEFAULT_SECTION_PADDING: float = 0.05


class EndcapBacklitMultitier(AbstractPlanogramType):
    """Planogram type for backlit multi-tier endcap displays.

    Validates compliance for a display that combines:
    - A retro-illuminated header panel (backlit lightbox).
    - One or more product shelves, each optionally sub-divided into named
      ``ShelfSection`` regions that are detected IN PARALLEL via
      ``asyncio.gather()``.

    For shelves with ``sections`` defined, one LLM detection call is launched
    per section concurrently.  Flat shelves (``sections=None``) use a single
    full-shelf LLM call.  Section-local bounding boxes are remapped to
    full-image normalized coordinates before being stored on each
    ``IdentifiedProduct``.

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
        Optional[Any],
        Optional[Any],
        Optional[Any],
        Optional[Any],
        List[Any],
    ]:
        """Detect endcap ROI, promotional graphic, and brand logo via LLM.

        Follows the same vision-LLM pattern as ``EndcapNoShelvesPromotional``:
        the model returns bboxes for the endcap area.  Bbox expansion logic
        accommodates models that detect only the header panel instead of the
        full endcap height.

        Args:
            img: The input PIL image.

        Returns:
            Tuple of ``(endcap_det, ad_det, brand_det, panel_text_det,
            raw_dets)``.  Returns ``(None, None, None, None, [])`` when
            detection fails.
        """
        planogram_description = self.config.get_planogram_description()
        brand = (getattr(planogram_description, "brand", "") or "").strip()
        brand_hint = f" {brand}" if brand else ""

        partial_prompt = self.config.roi_detection_prompt or ""
        image_small = self.pipeline._downscale_image(img, max_side=1024, quality=78)

        prompt = partial_prompt or (
            f"Identify the full promotional endcap display in this{brand_hint} retail "
            "image. Focus on the retro-illuminated upper panel. Return a bounding box "
            "labeled 'endcap' that covers the complete endcap area from the top of the "
            "backlit panel down to the bottom shelf."
        )

        max_attempts = 2
        msg = None
        for attempt in range(max_attempts):
            try:
                async with self.pipeline.roi_client as client:
                    msg = await client.ask_to_image(
                        image=image_small,
                        prompt=prompt,
                        model=GoogleModel.GEMINI_3_FLASH_PREVIEW,
                        no_memory=True,
                        structured_output=Detections,
                        max_tokens=8192,
                    )
                break
            except Exception as exc:
                if attempt < max_attempts - 1:
                    self.logger.warning(
                        "ROI detection attempt %d failed: %s; retrying...",
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

        # Pixel-coordinate recovery (same pattern as EndcapNoShelvesPromotional)
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

        dets: List[Detection] = getattr(data, "detections", None) or []
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

        # Expand bbox downward if the LLM only detected the upper panel
        bbox_height = endcap_det.bbox.y2 - endcap_det.bbox.y1
        if bbox_height < 0.5:
            expanded_bbox = BoundingBox(
                x1=endcap_det.bbox.x1,
                y1=endcap_det.bbox.y1,
                x2=endcap_det.bbox.x2,
                y2=min(1.0, endcap_det.bbox.y2 + bbox_height),
            )
            endcap_det = Detection(
                label=endcap_det.label,
                confidence=endcap_det.confidence,
                bbox=expanded_bbox,
            )
            self.logger.info(
                "Expanded endcap ROI downward (height was %.2f).", bbox_height
            )

        ad_det = next(
            (
                d
                for d in dets
                if _norm_label(d) in ("advertisement", "promotional_graphic", "ad")
            ),
            endcap_det,
        )
        brand_det = next(
            (d for d in dets if _norm_label(d) in ("brand", "brand_logo", "logo")),
            None,
        )

        return endcap_det, ad_det, brand_det, None, dets

    async def detect_objects_roi(
        self,
        img: Image.Image,
        roi: Any,
    ) -> List[Detection]:
        """Detect structural zones (backlit panel, logo area) within the ROI.

        Sends the cropped endcap area to the LLM to identify high-level
        structural zones used for header-level illumination assessment.

        Args:
            img: The full input PIL image.
            roi: Endcap detection returned by ``compute_roi()``.

        Returns:
            List of Detection objects found in the header/ROI area.
            Returns ``[]`` if ``roi`` is ``None`` or the LLM call fails.
        """
        if roi is None:
            self.logger.warning("No ROI — skipping detect_objects_roi.")
            return []

        iw, ih = img.size
        bbox = roi.bbox
        x1 = int(bbox.x1 * iw)
        y1 = int(bbox.y1 * ih)
        x2 = int(bbox.x2 * iw)
        y2 = int(bbox.y2 * ih)
        cropped = img.crop((x1, y1, x2, y2))
        image_small = self.pipeline._downscale_image(cropped, max_side=1024, quality=78)

        prompt = (
            "Within this backlit multi-tier endcap display, identify the following "
            "structural zones and return their bounding boxes:\n"
            "1) 'backlit_panel' — the retro-illuminated upper graphic panel (lightbox)\n"
            "2) 'logo_zone' — the brand logo area on the panel\n"
            "Return each detected zone with its label, confidence, and bounding box."
        )

        max_attempts = 2
        msg = None
        for attempt in range(max_attempts):
            try:
                async with self.pipeline.roi_client as client:
                    msg = await client.ask_to_image(
                        image=image_small,
                        prompt=prompt,
                        model=GoogleModel.GEMINI_3_FLASH_PREVIEW,
                        no_memory=True,
                        structured_output=Detections,
                        max_tokens=8192,
                    )
                break
            except Exception as exc:
                if attempt < max_attempts - 1:
                    self.logger.warning(
                        "detect_objects_roi attempt %d failed: %s; retrying...",
                        attempt + 1,
                        exc,
                    )
                    await asyncio.sleep(10)
                else:
                    self.logger.warning(
                        "detect_objects_roi failed after %d attempts: %s",
                        max_attempts,
                        exc,
                    )
                    return []

        data = msg.structured_output or msg.output or {}
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
            except Exception:
                return []

        return getattr(data, "detections", None) or []

    async def detect_objects(
        self,
        img: Image.Image,
        roi: Any,
        macro_objects: Any,
    ) -> Tuple[List[IdentifiedProduct], List[ShelfRegion]]:
        """Detect products per shelf using parallel section detection when configured.

        For each shelf in ``planogram_description.shelves``:

        - If ``shelf.sections`` is set, one LLM detection call is launched per
          section concurrently via ``asyncio.gather()``.
        - Flat shelves (``sections=None``) use a single full-shelf LLM call.
        - Section-local bboxes are remapped to full-image normalized coordinates.
        - On LLM failure for any section, that section yields no detections
          (graceful degradation — the shelf is treated as empty for that section).

        Args:
            img: The full input PIL image.
            roi: Endcap detection returned by ``compute_roi()``.
            macro_objects: Unused — detection is config-driven per section.

        Returns:
            Tuple of ``(identified_products, shelf_regions)``.
        """
        planogram_description = self.config.get_planogram_description()
        brand = (getattr(planogram_description, "brand", "") or "").strip()
        category = (getattr(planogram_description, "category", "") or "").strip()
        patterns = getattr(planogram_description, "model_normalization_patterns", None)

        iw, ih = img.size
        identified_products: List[IdentifiedProduct] = []
        shelf_regions: List[ShelfRegion] = []

        # Illumination state evaluated at most once per image
        roi_illumination: Optional[str] = None

        shelves = getattr(planogram_description, "shelves", []) or []

        for shelf_idx, shelf in enumerate(shelves):
            shelf_level = getattr(shelf, "level", f"shelf_{shelf_idx}")
            y_start = float(getattr(shelf, "y_start_ratio", None) or 0.0)
            height = float(getattr(shelf, "height_ratio", 0.30) or 0.30)
            padding = float(
                getattr(shelf, "section_padding", None) or _DEFAULT_SECTION_PADDING
            )

            # Shelf pixel bbox
            shelf_y1 = int(ih * y_start)
            shelf_y2 = min(ih, int(ih * (y_start + height)))
            shelf_bbox: Tuple[int, int, int, int] = (0, shelf_y1, iw, shelf_y2)

            shelf_products_cfg = getattr(shelf, "products", []) or []
            sections: Optional[List[ShelfSection]] = getattr(shelf, "sections", None)

            # For the header shelf, run illumination check
            if shelf_level == "header" and roi_illumination is None:
                header_illum_box = DetectionBox(
                    x1=0,
                    y1=shelf_y1,
                    x2=iw,
                    y2=shelf_y2,
                    confidence=0.0,
                )
                roi_illumination = await self._check_illumination(
                    img, roi, planogram_description, illum_zone_bbox=header_illum_box
                )

            # Parallel section detection or single flat call
            shelf_detections: List[Detection] = []
            if sections:
                section_tasks = [
                    self._detect_section(
                        img=img,
                        section=sec,
                        shelf_bbox=shelf_bbox,
                        padding=padding,
                        category=category,
                        brand=brand,
                        patterns=patterns,
                    )
                    for sec in sections
                ]
                section_results: List[List[Detection]] = await asyncio.gather(
                    *section_tasks
                )
                merged = [d for sublist in section_results for d in sublist]
                shelf_detections = self._deduplicate_cross_section(merged)
            else:
                product_names = [getattr(p, "name", "") for p in shelf_products_cfg]
                shelf_detections = await self._detect_flat_shelf(
                    img=img,
                    shelf_bbox=shelf_bbox,
                    product_names=product_names,
                    category=category,
                    brand=brand,
                )

            # Visual features (illumination state applied to header shelf only)
            visual_feats: List[str] = []
            if roi_illumination and shelf_level == "header":
                visual_feats = [roi_illumination]

            # Convert detections to IdentifiedProduct objects
            for det in shelf_detections:
                prod = IdentifiedProduct(
                    product_type=category.lower() or "product",
                    product_model=det.label or "",
                    brand=brand or None,
                    confidence=det.confidence,
                    shelf_location=shelf_level,
                    visual_features=list(visual_feats),
                    detection_box=DetectionBox(
                        x1=int(det.bbox.x1 * iw),
                        y1=int(det.bbox.y1 * ih),
                        x2=int(det.bbox.x2 * iw),
                        y2=int(det.bbox.y2 * ih),
                        confidence=det.confidence,
                    ),
                )
                identified_products.append(prod)

            # When no detections on this shelf, register expected products as absent
            if not shelf_detections and shelf_products_cfg:
                for sp in shelf_products_cfg:
                    prod = IdentifiedProduct(
                        product_type=category.lower() or "product",
                        product_model=getattr(sp, "name", ""),
                        brand=brand or None,
                        confidence=0.0,
                        shelf_location=shelf_level,
                        visual_features=list(visual_feats),
                    )
                    identified_products.append(prod)

            shelf_regions.append(
                ShelfRegion(
                    shelf_id=f"{shelf_level}_{shelf_idx}",
                    bbox=DetectionBox(
                        x1=0,
                        y1=shelf_y1,
                        x2=iw,
                        y2=shelf_y2,
                        confidence=0.0,
                    ),
                    level=shelf_level,
                    detections=[],
                )
            )

        self.logger.info(
            "EndcapBacklitMultitier.detect_objects: %d products from %d shelves",
            len(identified_products),
            len(shelves),
        )
        return identified_products, shelf_regions

    def check_planogram_compliance(
        self,
        identified_products: List[IdentifiedProduct],
        planogram_description: Any,
    ) -> List[ComplianceResult]:
        """Score compliance per shelf by comparing detected vs. expected products.

        Groups ``identified_products`` by ``shelf_location``.  For each shelf
        in ``planogram_description.shelves``, computes a simple intersection
        score between expected product names and found product models (both
        normalized via ``_base_model_from_str``).  Applies an illumination
        penalty for the header shelf when the backlit panel is expected ON but
        detected as OFF.

        Args:
            identified_products: Products from ``detect_objects()``.
            planogram_description: Expected planogram layout from config.

        Returns:
            List of ComplianceResult, one per shelf.
        """
        brand = (getattr(planogram_description, "brand", "") or "").strip()
        patterns = getattr(planogram_description, "model_normalization_patterns", None)
        shelves = getattr(planogram_description, "shelves", []) or []

        # Group products by shelf level
        products_by_shelf: Dict[str, List[IdentifiedProduct]] = {}
        for p in identified_products:
            key = p.shelf_location or "unknown"
            products_by_shelf.setdefault(key, []).append(p)

        results: List[ComplianceResult] = []

        for shelf in shelves:
            shelf_level = getattr(shelf, "level", "unknown")
            shelf_products_cfg = getattr(shelf, "products", []) or []
            threshold = float(getattr(shelf, "compliance_threshold", 0.8))

            expected = [
                self._base_model_from_str(
                    getattr(sp, "name", ""),
                    brand=brand,
                    patterns=patterns,
                )
                for sp in shelf_products_cfg
            ]
            expected = [e for e in expected if e]

            shelf_identified = products_by_shelf.get(shelf_level, [])
            found = [
                self._base_model_from_str(
                    p.product_model or "",
                    brand=brand,
                    patterns=patterns,
                )
                for p in shelf_identified
                if p.confidence > 0.0
            ]
            found = [f for f in found if f]

            expected_set = set(expected)
            found_set = set(found)
            missing = sorted(expected_set - found_set)
            unexpected = sorted(found_set - expected_set)

            score = (
                len(expected_set & found_set) / max(len(expected_set), 1)
                if expected_set
                else (1.0 if not found_set else 0.0)
            )

            # Illumination penalty for the header shelf
            if shelf_level == "header":
                illum_feats = [
                    f
                    for p in shelf_identified
                    for f in (p.visual_features or [])
                ]
                illum_state = self._extract_illumination_state(illum_feats)
                required_on = any(
                    "illumination_status: on"
                    in " ".join(getattr(sp, "visual_features", None) or []).lower()
                    for sp in shelf_products_cfg
                )
                if required_on and illum_state == "off":
                    score = 0.0
                    self.logger.info(
                        "Header illumination OFF when ON required — compliance zeroed."
                    )

            status = (
                ComplianceStatus.COMPLIANT
                if score >= threshold
                else ComplianceStatus.NON_COMPLIANT
            )

            results.append(
                ComplianceResult(
                    shelf_level=shelf_level,
                    expected_products=expected,
                    found_products=found,
                    missing_products=missing,
                    unexpected_products=unexpected,
                    compliance_status=status,
                    compliance_score=round(score, 4),
                    text_compliance_results=[],
                    text_compliance_score=1.0,
                )
            )

        self.logger.info(
            "EndcapBacklitMultitier compliance: %d shelves evaluated", len(results)
        )
        return results

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _compute_section_bbox(
        self,
        shelf_bbox: Tuple[int, int, int, int],
        region: SectionRegion,
        padding: float,
        image_size: Tuple[int, int],
    ) -> Tuple[int, int, int, int]:
        """Convert section region ratios to absolute pixel coordinates.

        Applies optional padding on all sides and clamps results to image bounds.

        Args:
            shelf_bbox: ``(sx1, sy1, sx2, sy2)`` pixel coordinates.
            region: Section region ratios relative to the shelf size.
            padding: Fractional overlap to add on each boundary.
            image_size: ``(width, height)`` of the full image.

        Returns:
            ``(x1, y1, x2, y2)`` pixel coordinates clamped to image bounds.
        """
        sx1, sy1, sx2, sy2 = shelf_bbox
        sw, sh = sx2 - sx1, sy2 - sy1
        iw, ih = image_size
        x1 = max(0, int(sx1 + (region.x_start - padding) * sw))
        x2 = min(iw, int(sx1 + (region.x_end + padding) * sw))
        y1 = max(0, int(sy1 + (region.y_start - padding) * sh))
        y2 = min(ih, int(sy1 + (region.y_end + padding) * sh))
        return (x1, y1, x2, y2)

    def _remap_bbox_to_full_image(
        self,
        local_bbox: BoundingBox,
        crop_bbox: Tuple[int, int, int, int],
        image_size: Tuple[int, int],
    ) -> BoundingBox:
        """Remap a crop-relative normalized bbox to full-image normalized coordinates.

        LLM responses return bboxes as ratios relative to the section CROP.
        This method converts them to ratios of the FULL image.

        Args:
            local_bbox: Bbox with ratios relative to the section crop.
            crop_bbox: ``(cx1, cy1, cx2, cy2)`` pixel coordinates of the crop.
            image_size: ``(width, height)`` of the full image.

        Returns:
            BoundingBox with coordinates normalized to full-image dimensions.
        """
        cx1, cy1, cx2, cy2 = crop_bbox
        cw = cx2 - cx1
        ch = cy2 - cy1
        iw, ih = image_size

        full_x1 = cx1 + local_bbox.x1 * cw
        full_y1 = cy1 + local_bbox.y1 * ch
        full_x2 = cx1 + local_bbox.x2 * cw
        full_y2 = cy1 + local_bbox.y2 * ch

        return BoundingBox(
            x1=min(1.0, max(0.0, full_x1 / iw)),
            y1=min(1.0, max(0.0, full_y1 / ih)),
            x2=min(1.0, max(0.0, full_x2 / iw)),
            y2=min(1.0, max(0.0, full_y2 / ih)),
        )

    def _build_section_prompt(
        self,
        product_names: List[str],
        category: str,
        brand: str,
    ) -> str:
        """Build an LLM detection prompt for a shelf section.

        No category strings are hardcoded — both ``category`` and ``brand``
        are derived from the live planogram description at runtime.

        Args:
            product_names: Expected product names in this section.
            category: Product category (e.g. ``"Printers"``).
            brand: Brand name (e.g. ``"Epson"``).

        Returns:
            Formatted prompt string for the vision LLM.
        """
        category_hint = f" {category}" if category else ""
        brand_hint = f" {brand}" if brand else ""
        names_str = (
            ", ".join(f'"{n}"' for n in product_names)
            if product_names
            else "any products"
        )
        return (
            f"You are inspecting a retail shelf section containing{brand_hint}"
            f"{category_hint} products. "
            f"Identify any of the following products visible in this image: {names_str}. "
            "For each product found, return a detection with its label (use the exact "
            "product name from the list), confidence score, and bounding box. "
            "Return an empty detections list if none are visible."
        )

    async def _detect_section(
        self,
        img: Image.Image,
        section: ShelfSection,
        shelf_bbox: Tuple[int, int, int, int],
        padding: float,
        category: str,
        brand: str,
        patterns: Optional[List[str]],
    ) -> List[Detection]:
        """Run LLM detection on a single shelf section.

        Crops the section from the full image, sends it to the vision LLM,
        and remaps returned bbox coordinates back to full-image space.
        On any LLM failure the section is treated as empty (graceful degradation).

        Args:
            img: The full input PIL image.
            section: The shelf section configuration.
            shelf_bbox: Shelf pixel bbox ``(sx1, sy1, sx2, sy2)``.
            padding: Fractional overlap added on each boundary of the crop.
            category: Product category string for the detection prompt.
            brand: Brand name for the detection prompt.
            patterns: Optional model normalization patterns (unused in prompting).

        Returns:
            List of Detection objects with full-image normalized bbox coordinates.
            Returns ``[]`` on LLM failure or zero-area crop.
        """
        crop_bbox = self._compute_section_bbox(
            shelf_bbox, section.region, padding, img.size
        )
        cx1, cy1, cx2, cy2 = crop_bbox
        if cx2 <= cx1 or cy2 <= cy1:
            self.logger.warning(
                "Section '%s' has zero-area bbox — skipping.", section.id
            )
            return []

        crop = img.crop(crop_bbox)
        crop_small = self.pipeline._downscale_image(crop, max_side=1024, quality=82)
        prompt = self._build_section_prompt(section.products, category, brand)

        try:
            async with self.pipeline.roi_client as client:
                msg = await client.ask_to_image(
                    image=crop_small,
                    prompt=prompt,
                    model=GoogleModel.GEMINI_3_FLASH_PREVIEW,
                    no_memory=True,
                    structured_output=Detections,
                    max_tokens=4096,
                )
        except Exception as exc:
            self.logger.warning(
                "Section '%s' LLM call failed: %s — treating as empty.",
                section.id,
                exc,
            )
            return []

        data = msg.structured_output or msg.output or {}
        if isinstance(data, str):
            try:
                raw = json.loads(data)
                iw_s, ih_s = crop_small.size
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
            except Exception as parse_err:
                self.logger.warning(
                    "Section '%s' coordinate recovery failed: %s",
                    section.id,
                    parse_err,
                )
                return []

        raw_dets: List[Detection] = getattr(data, "detections", None) or []

        # Remap bbox from section-crop-local to full-image coordinates
        remapped: List[Detection] = []
        for det in raw_dets:
            full_bbox = self._remap_bbox_to_full_image(det.bbox, crop_bbox, img.size)
            remapped.append(
                Detection(
                    label=det.label,
                    confidence=det.confidence,
                    bbox=full_bbox,
                    content=det.content,
                )
            )

        self.logger.debug(
            "Section '%s': %d detections.", section.id, len(remapped)
        )
        return remapped

    async def _detect_flat_shelf(
        self,
        img: Image.Image,
        shelf_bbox: Tuple[int, int, int, int],
        product_names: List[str],
        category: str,
        brand: str,
    ) -> List[Detection]:
        """Run LLM detection on a flat shelf (no section subdivision).

        Args:
            img: The full input PIL image.
            shelf_bbox: Shelf pixel bbox ``(sx1, sy1, sx2, sy2)``.
            product_names: Expected product names for the prompt.
            category: Product category string for the detection prompt.
            brand: Brand name for the detection prompt.

        Returns:
            List of Detection objects with full-image normalized bbox coordinates.
            Returns ``[]`` on LLM failure or zero-area bbox.
        """
        sx1, sy1, sx2, sy2 = shelf_bbox
        if sx2 <= sx1 or sy2 <= sy1:
            return []

        crop = img.crop(shelf_bbox)
        crop_small = self.pipeline._downscale_image(crop, max_side=1024, quality=82)
        prompt = self._build_section_prompt(product_names, category, brand)

        try:
            async with self.pipeline.roi_client as client:
                msg = await client.ask_to_image(
                    image=crop_small,
                    prompt=prompt,
                    model=GoogleModel.GEMINI_3_FLASH_PREVIEW,
                    no_memory=True,
                    structured_output=Detections,
                    max_tokens=4096,
                )
        except Exception as exc:
            self.logger.warning(
                "Flat shelf LLM call failed: %s — treating as empty.", exc
            )
            return []

        data = msg.structured_output or msg.output or {}
        if isinstance(data, str):
            try:
                raw = json.loads(data)
                iw_s, ih_s = crop_small.size
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
            except Exception:
                return []

        raw_dets: List[Detection] = getattr(data, "detections", None) or []
        remapped: List[Detection] = []
        for det in raw_dets:
            full_bbox = self._remap_bbox_to_full_image(det.bbox, shelf_bbox, img.size)
            remapped.append(
                Detection(
                    label=det.label,
                    confidence=det.confidence,
                    bbox=full_bbox,
                    content=det.content,
                )
            )
        return remapped

    def _deduplicate_cross_section(
        self,
        detections: List[Detection],
        iou_threshold: float = 0.5,
    ) -> List[Detection]:
        """Remove duplicate detections that overlap across section boundaries.

        Uses a greedy NMS-style approach: detections are sorted by confidence
        (descending) and any subsequent detection whose IoU with an already
        accepted detection exceeds ``iou_threshold`` is discarded.

        Args:
            detections: List of Detection objects in full-image coordinates.
            iou_threshold: Minimum IoU to treat two detections as duplicates.

        Returns:
            Deduplicated list of Detection objects, sorted by confidence desc.
        """
        if not detections:
            return []

        sorted_dets = sorted(detections, key=lambda d: d.confidence, reverse=True)
        accepted: List[Detection] = []
        for det in sorted_dets:
            keep = True
            for existing in accepted:
                if self._iou(det.bbox, existing.bbox) > iou_threshold:
                    keep = False
                    break
            if keep:
                accepted.append(det)
        return accepted

    @staticmethod
    def _iou(bbox_a: BoundingBox, bbox_b: BoundingBox) -> float:
        """Compute Intersection-over-Union for two normalized BoundingBoxes.

        Args:
            bbox_a: First bounding box (normalized 0-1 coordinates).
            bbox_b: Second bounding box (normalized 0-1 coordinates).

        Returns:
            IoU value in the range ``[0.0, 1.0]``.
        """
        ix1 = max(bbox_a.x1, bbox_b.x1)
        iy1 = max(bbox_a.y1, bbox_b.y1)
        ix2 = min(bbox_a.x2, bbox_b.x2)
        iy2 = min(bbox_a.y2, bbox_b.y2)
        inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
        if inter == 0.0:
            return 0.0
        area_a = (bbox_a.x2 - bbox_a.x1) * (bbox_a.y2 - bbox_a.y1)
        area_b = (bbox_b.x2 - bbox_b.x1) * (bbox_b.y2 - bbox_b.y1)
        union = area_a + area_b - inter
        return inter / union if union > 0.0 else 0.0
