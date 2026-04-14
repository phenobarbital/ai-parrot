"""EndcapBacklitMultitier planogram type composable.

Handles planogram compliance for backlit multi-tier endcap displays: a
retro-illuminated header panel (lightbox) combined with one or more product
shelves.  Shelves may be sub-divided into named sections detected in parallel.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw
from pydantic import BaseModel, Field

from .abstract import AbstractPlanogramType
from parrot.models.google import GoogleModel
from parrot.models.detections import (
    BoundingBox,
    Detection,
    DetectionBox,
    IdentifiedProduct,
    SectionRegion,
    ShelfRegion,
    ShelfSection,
)
from parrot.models.compliance import (
    ComplianceResult,
    ComplianceStatus,
    TextComplianceResult,
)

# Default fractional padding added to each section boundary when
# ``shelf.section_padding`` is not explicitly set.
_DEFAULT_SECTION_PADDING: float = 0.05


# ---------------------------------------------------------------------------
# Permissive Pydantic models for LLM structured output.
#
# Gemini Flash often returns bounding-box coordinates in pixel space or
# 1000-space (values >> 1.0).  The canonical ``Detections`` model enforces
# ``le=1`` on bbox fields, which triggers noisy Pydantic validation warnings
# inside the client's ``structured_output`` parser before the fallback raw-
# string path even gets a chance to normalise them.
#
# These models accept ANY float, letting the manual normalisation code that
# already exists in every call site handle the conversion to 0-1 range.
# ---------------------------------------------------------------------------

class _RawBBox(BaseModel):
    """Bounding box without ``le=1`` constraints."""

    x1: float = Field(default=0)
    y1: float = Field(default=0)
    x2: float = Field(default=0)
    y2: float = Field(default=0)


class _RawDetection(BaseModel):
    """Single detection without strict bbox validation."""

    label: Optional[str] = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    content: Optional[str] = None
    bbox: _RawBBox = Field(default_factory=_RawBBox)


class _RawDetections(BaseModel):
    """Container for detections without strict bbox validation."""

    detections: List[_RawDetection] = Field(default_factory=list)


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
                        structured_output=_RawDetections,
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

        if isinstance(data, _RawDetections):
            self._normalize_raw_dets_coords(data, image_small.size)
        # Pixel-coordinate recovery (same pattern as EndcapNoShelvesPromotional)
        elif isinstance(data, str):
            try:
                raw = json.loads(data)
                iw_s, ih_s = image_small.size
                dets_raw = raw.get("detections", [])
                all_x = [v for d in dets_raw for v in (d.get("bbox", {}).get("x1", 0), d.get("bbox", {}).get("x2", 0))]
                all_y = [v for d in dets_raw for v in (d.get("bbox", {}).get("y1", 0), d.get("bbox", {}).get("y2", 0))]
                needs_norm = any(v > 1.0 for v in all_x + all_y)
                if needs_norm:
                    nw = 1000.0 if max(all_x, default=0) > iw_s else float(iw_s)
                    nh = 1000.0 if max(all_y, default=0) > ih_s else float(ih_s)
                    for d in dets_raw:
                        b = d.get("bbox", {})
                        b["x1"] = min(1.0, max(0.0, b.get("x1", 0) / nw))
                        b["y1"] = min(1.0, max(0.0, b.get("y1", 0) / nh))
                        b["x2"] = min(1.0, max(0.0, b.get("x2", 0) / nw))
                        b["y2"] = min(1.0, max(0.0, b.get("y2", 0) / nh))
                        if b["x1"] > b["x2"]:
                            b["x1"], b["x2"] = b["x2"], b["x1"]
                        if b["y1"] > b["y2"]:
                            b["y1"], b["y2"] = b["y2"], b["y1"]
                data = _RawDetections(**raw)
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
                        structured_output=_RawDetections,
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
        if isinstance(data, _RawDetections):
            self._normalize_raw_dets_coords(data, image_small.size)
        elif isinstance(data, str):
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
                data = _RawDetections(**raw)
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

        # ----------------------------------------------------------
        # Derive x-range from the endcap ROI so shelf crops exclude
        # background clutter on the sides of the display.
        # ----------------------------------------------------------
        roi_x1 = 0
        roi_x2 = iw
        if roi is not None:
            roi_bbox = getattr(roi, "bbox", None)
            if roi_bbox is not None:
                roi_x1 = max(0, int(roi_bbox.x1 * iw))
                roi_x2 = min(iw, int(roi_bbox.x2 * iw))
                self.logger.debug(
                    "Shelf x-range constrained by ROI: x1=%d x2=%d (image width=%d)",
                    roi_x1, roi_x2, iw,
                )

        # ----------------------------------------------------------
        # Pre-compute shelf pixel bboxes from static config ratios
        # ----------------------------------------------------------
        shelf_pixel_bboxes: List[Tuple[int, int, int, int]] = []
        for shelf in shelves:
            y_s = float(getattr(shelf, "y_start_ratio", None) or 0.0)
            h_s = float(getattr(shelf, "height_ratio", 0.30) or 0.30)
            s_y1 = int(ih * y_s)
            s_y2 = min(ih, int(ih * (y_s + h_s)))
            shelf_pixel_bboxes.append((roi_x1, s_y1, roi_x2, s_y2))

        # ----------------------------------------------------------
        # Fact-tag pre-scan: dynamically refine shelf boundaries
        # ----------------------------------------------------------
        _pg_cfg = getattr(self.config, "planogram_config", {}) or {}
        if _pg_cfg.get("use_fact_tag_boundaries") and len(shelves) > 1:
            # Identify the product area (all non-header shelves combined)
            non_header_idxs = [
                i for i, s in enumerate(shelves)
                if getattr(s, "level", "") != "header"
            ]
            if non_header_idxs:
                area_y1 = shelf_pixel_bboxes[non_header_idxs[0]][1]
                area_y2 = shelf_pixel_bboxes[non_header_idxs[-1]][3]
                product_area = (roi_x1, area_y1, roi_x2, area_y2)

                fact_tag_products = await self._detect_fact_tags_prescan(
                    img, product_area
                )

                if fact_tag_products:
                    # Build temporary ShelfRegions from static bboxes
                    static_regions: List[ShelfRegion] = []
                    for si, sh in enumerate(shelves):
                        bx1, by1, bx2, by2 = shelf_pixel_bboxes[si]
                        sh_level = getattr(sh, "level", f"shelf_{si}")
                        static_regions.append(ShelfRegion(
                            shelf_id=f"{sh_level}_{si}",
                            level=sh_level,
                            bbox=DetectionBox(
                                x1=bx1, y1=by1, x2=bx2, y2=by2,
                                confidence=0.0,
                            ),
                            is_background=getattr(sh, "is_background", False),
                            objects=[],
                        ))

                    refined = self._refine_shelves_from_fact_tags(
                        static_regions, fact_tag_products
                    )

                    # Update shelf_pixel_bboxes from refined regions
                    region_by_id = {r.shelf_id: r for r in refined}
                    for si, sh in enumerate(shelves):
                        sh_level = getattr(sh, "level", f"shelf_{si}")
                        sid = f"{sh_level}_{si}"
                        if sid in region_by_id:
                            rb = region_by_id[sid].bbox
                            shelf_pixel_bboxes[si] = (
                                rb.x1, rb.y1, rb.x2, rb.y2,
                            )

                    # Include prescan fact tags in results
                    identified_products.extend(fact_tag_products)

                    self.logger.info(
                        "Shelf boundaries refined from %d fact-tag detections.",
                        len(fact_tag_products),
                    )

        # ----------------------------------------------------------
        # Pre-compute combined flat-shelf detection
        # ----------------------------------------------------------
        # Collect adjacent non-header flat shelves for combined detection.
        flat_shelf_group: List[
            Tuple[int, str, Tuple[int, int, int, int], List[str]]
        ] = []
        for si, sh in enumerate(shelves):
            sh_level = getattr(sh, "level", f"shelf_{si}")
            sh_sections = getattr(sh, "sections", None)
            if sh_level == "header" or sh_sections:
                continue
            sh_products = getattr(sh, "products", []) or []
            pnames = [
                getattr(p, "name", "")
                for p in sh_products
                if getattr(p, "product_type", "") != "fact_tag"
            ]
            flat_shelf_group.append(
                (si, sh_level, shelf_pixel_bboxes[si], pnames)
            )

        # Extract pixel bboxes from prescan fact-tag products so
        # product detection can filter out overlapping false positives.
        ft_bboxes: Optional[List[Tuple[int, int, int, int]]] = None
        ft_products = [
            p
            for p in identified_products
            if getattr(p, "product_type", "") == "fact_tag"
            and getattr(p, "detection_box", None) is not None
        ]
        if ft_products:
            ft_bboxes = [
                (p.detection_box.x1, p.detection_box.y1,
                 p.detection_box.x2, p.detection_box.y2)
                for p in ft_products
            ]

        # Run combined detection if 2+ adjacent flat shelves; otherwise
        # individual detection is used in the per-shelf loop.
        combined_dets: Dict[int, List[Detection]] = {}
        if len(flat_shelf_group) >= 2:
            combined_dets = await self._detect_combined_flat_shelves(
                img=img,
                flat_shelves=flat_shelf_group,
                category=category,
                brand=brand,
                fact_tag_bboxes=ft_bboxes,
            )

        # ----------------------------------------------------------
        # Per-shelf detection loop (uses refined bboxes when available)
        # ----------------------------------------------------------
        for shelf_idx, shelf in enumerate(shelves):
            shelf_level = getattr(shelf, "level", f"shelf_{shelf_idx}")
            padding = float(
                getattr(shelf, "section_padding", None) or _DEFAULT_SECTION_PADDING
            )

            # Use pre-computed (possibly refined) shelf bbox
            shelf_bbox: Tuple[int, int, int, int] = shelf_pixel_bboxes[shelf_idx]
            shelf_y1 = shelf_bbox[1]
            shelf_y2 = shelf_bbox[3]

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
                        fact_tag_bboxes=ft_bboxes if ft_bboxes else None,
                    )
                    for sec in sections
                ]
                section_results: List[List[Detection]] = await asyncio.gather(
                    *section_tasks
                )
                merged = [d for sublist in section_results for d in sublist]
                shelf_detections = self._deduplicate_cross_section(merged)
            elif shelf_idx in combined_dets:
                # Results already computed by combined flat-shelf detection
                shelf_detections = combined_dets[shelf_idx]
            else:
                product_names = [
                    getattr(p, "name", "")
                    for p in shelf_products_cfg
                    if getattr(p, "product_type", "") != "fact_tag"
                ]
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
                    if getattr(sp, "product_type", "") == "fact_tag":
                        continue
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
                    objects=[],
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
                if getattr(sp, "product_type", "") != "fact_tag"
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
                and p.product_type != "fact_tag"
                and "fact tag" not in (p.product_model or "").lower()
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

            # Header scoring: 50% correct campaign text + 50% light ON
            text_compliance_score = 1.0
            text_compliance_results: List[TextComplianceResult] = []
            if shelf_level == "header":
                header_score = 0.0

                # ── 50%: correct campaign (text requirements) ──
                ad_endcap = getattr(planogram_description, "advertisement_endcap", None)
                text_reqs = (
                    getattr(ad_endcap, "text_requirements", []) if ad_endcap else []
                ) or []

                campaign_ok = False
                if text_reqs:
                    ocr_texts = " ".join(
                        getattr(p, "ocr_text", "") or ""
                        for p in shelf_identified
                    ).lower()

                    mandatory_total = 0
                    mandatory_found = 0
                    for req in text_reqs:
                        req_text = getattr(req, "required_text", "") or ""
                        is_mandatory = getattr(req, "mandatory", True)
                        match_type = getattr(req, "match_type", "contains") or "contains"
                        if not req_text or not is_mandatory:
                            continue
                        mandatory_total += 1
                        text_present = req_text.lower() in ocr_texts
                        if text_present:
                            mandatory_found += 1
                        text_compliance_results.append(
                            TextComplianceResult(
                                required_text=req_text,
                                found=text_present,
                                confidence=1.0 if text_present else 0.0,
                                match_type=match_type,
                            )
                        )

                    if mandatory_total > 0:
                        text_compliance_score = mandatory_found / mandatory_total
                    campaign_ok = mandatory_total > 0 and mandatory_found == mandatory_total
                else:
                    # No text requirements configured — campaign passes
                    campaign_ok = True

                if campaign_ok:
                    header_score += 0.5

                # ── 50%: illumination ON ──
                # Use roi_illumination directly — it was computed via
                # _check_illumination() earlier.  Extracting from
                # shelf_identified visual_features fails when the header
                # has no detected products (Found Products: None).
                illum_state = self._extract_illumination_state(
                    [roi_illumination] if roi_illumination else []
                )
                light_on = illum_state == "on"
                if light_on:
                    header_score += 0.5

                score = header_score
                self.logger.info(
                    "Header compliance: campaign=%s (text %d/%d), "
                    "light=%s → score=%.1f%%",
                    "OK" if campaign_ok else "WRONG",
                    mandatory_found if text_reqs else 0,
                    mandatory_total if text_reqs else 0,
                    "ON" if light_on else "OFF",
                    score * 100,
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
                    text_compliance_results=text_compliance_results,
                    text_compliance_score=round(text_compliance_score, 4),
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

    @staticmethod
    def _normalize_raw_dets_coords(
        data: _RawDetections,
        image_size: Tuple[int, int],
    ) -> None:
        """Normalize ``_RawDetections`` bbox coords in place when they exceed 1.0.

        Gemini Flash sometimes returns coords in pixel space or 1000-space.
        This method detects the coordinate space per axis and clamps all values
        to the 0-1 range, matching the manual normalization that was previously
        done only on the ``isinstance(data, str)`` fallback path.
        """
        if not data.detections:
            return
        iw_s, ih_s = image_size
        all_x = [v for d in data.detections for v in (d.bbox.x1, d.bbox.x2)]
        all_y = [v for d in data.detections for v in (d.bbox.y1, d.bbox.y2)]
        if not any(v > 1.0 for v in all_x + all_y):
            return
        nw = 1000.0 if max(all_x, default=0) > iw_s else float(iw_s)
        nh = 1000.0 if max(all_y, default=0) > ih_s else float(ih_s)
        for det in data.detections:
            b = det.bbox
            b.x1 = min(1.0, max(0.0, b.x1 / nw))
            b.y1 = min(1.0, max(0.0, b.y1 / nh))
            b.x2 = min(1.0, max(0.0, b.x2 / nw))
            b.y2 = min(1.0, max(0.0, b.y2 / nh))
            if b.x1 > b.x2:
                b.x1, b.x2 = b.x2, b.x1
            if b.y1 > b.y2:
                b.y1, b.y2 = b.y2, b.y1

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
        n = len(product_names) if product_names else 0
        count_hint = (
            f"\n\nThis section should contain up to {n} distinct products. "
            f"Look carefully — some models may look very "
            f"similar (e.g., two portable scanners side by side that differ "
            f"only in color, WiFi capability, or branding). Count each "
            f"physical device separately."
            if n >= 2
            else ""
        )
        return (
            f"You are inspecting a retail shelf section containing{brand_hint}"
            f"{category_hint} products. "
            f"Identify any of the following products visible in this image: {names_str}. "
            "Detect only the actual physical products (devices/scanners), "
            "NOT price tags, shelf labels, or fact tags. "
            "A price tag or fact tag hanging on the shelf edge does NOT mean "
            "the product is present — only report a product if you can see the "
            "actual physical device/hardware on the shelf. "
            "If a slot is empty (only a price tag but no device), do NOT report "
            "that product. "
            "For each product found, return a detection with its label (use the exact "
            "product name from the list), confidence score, and a bounding box "
            "around the DEVICE. "
            "Return an empty detections list if none are visible."
            + count_hint
        )

    async def _detect_fact_tags_prescan(
        self,
        img: Image.Image,
        product_area_bbox: Tuple[int, int, int, int],
    ) -> List[IdentifiedProduct]:
        """Pre-scan the full product area to detect fact tag positions.

        Sends a focused "detect price tags only" prompt to the vision LLM on
        the combined product-shelf crop.  Returned positions are converted to
        full-image pixel coordinates and wrapped as ``IdentifiedProduct``
        objects so that ``_refine_shelves_from_fact_tags()`` can use them to
        dynamically compute shelf boundaries BEFORE per-shelf detection.

        Args:
            img: The full input PIL image.
            product_area_bbox: Pixel bbox ``(x1, y1, x2, y2)`` covering all
                product shelves (excluding the header).

        Returns:
            List of IdentifiedProduct with ``product_type="fact_tag"`` and
            pixel-space ``detection_box``.  Returns ``[]`` on failure.
        """
        px1, py1, px2, py2 = product_area_bbox
        if px2 <= px1 or py2 <= py1:
            return []

        crop = img.crop(product_area_bbox)
        crop_small = self.pipeline._downscale_image(crop, max_side=1024, quality=82)

        prompt = (
            "You are inspecting a retail display shelf area. "
            "Identify ALL price tags (fact tags) visible along the shelf edges. "
            "These are small rectangular labels or cards hanging from or placed "
            "on shelf edges, typically showing product names and prices. "
            "For each price tag found, return a detection with label \"fact_tag\", "
            "a confidence score, and a tight bounding box. "
            "Return an empty detections list if no price tags are visible."
        )

        try:
            async with self.pipeline.roi_client as client:
                msg = await client.ask_to_image(
                    image=crop_small,
                    prompt=prompt,
                    model=GoogleModel.GEMINI_3_FLASH_PREVIEW,
                    no_memory=True,
                    structured_output=_RawDetections,
                    max_tokens=4096,
                )
        except Exception as exc:
            self.logger.warning(
                "Fact-tag prescan LLM call failed: %s — falling back to "
                "static boundaries.",
                exc,
            )
            return []

        data = msg.structured_output or msg.output or {}
        if isinstance(data, _RawDetections):
            self._normalize_raw_dets_coords(data, crop_small.size)
        elif isinstance(data, str):
            try:
                raw = json.loads(data)
                iw_s, ih_s = crop_small.size
                dets = raw.get("detections", [])
                all_x = [
                    v
                    for d in dets
                    for v in (
                        d.get("bbox", {}).get("x1", 0),
                        d.get("bbox", {}).get("x2", 0),
                    )
                ]
                all_y = [
                    v
                    for d in dets
                    for v in (
                        d.get("bbox", {}).get("y1", 0),
                        d.get("bbox", {}).get("y2", 0),
                    )
                ]
                needs_norm = any(v > 1.0 for v in all_x + all_y)
                if needs_norm:
                    nw = 1000.0 if max(all_x, default=0) > iw_s else float(iw_s)
                    nh = 1000.0 if max(all_y, default=0) > ih_s else float(ih_s)
                    for d in dets:
                        b = d.get("bbox", {})
                        b["x1"] = min(1.0, max(0.0, b.get("x1", 0) / nw))
                        b["y1"] = min(1.0, max(0.0, b.get("y1", 0) / nh))
                        b["x2"] = min(1.0, max(0.0, b.get("x2", 0) / nw))
                        b["y2"] = min(1.0, max(0.0, b.get("y2", 0) / nh))
                        if b["x1"] > b["x2"]:
                            b["x1"], b["x2"] = b["x2"], b["x1"]
                        if b["y1"] > b["y2"]:
                            b["y1"], b["y2"] = b["y2"], b["y1"]
                data = _RawDetections(**raw)
            except Exception:
                self.logger.warning(
                    "Fact-tag prescan: failed to parse LLM response — "
                    "falling back to static boundaries."
                )
                return []

        raw_dets: List[Detection] = getattr(data, "detections", None) or []
        if not raw_dets:
            self.logger.info("Fact-tag prescan: no tags detected.")
            return []

        # Convert crop-relative normalized bboxes to full-image pixel coords
        cw = px2 - px1
        ch = py2 - py1
        iw, ih = img.size
        results: List[IdentifiedProduct] = []
        for det in raw_dets:
            abs_x1 = int(px1 + det.bbox.x1 * cw)
            abs_y1 = int(py1 + det.bbox.y1 * ch)
            abs_x2 = int(px1 + det.bbox.x2 * cw)
            abs_y2 = int(py1 + det.bbox.y2 * ch)
            # Discard degenerate bboxes
            if abs_x2 - abs_x1 < 5 or abs_y2 - abs_y1 < 3:
                continue
            results.append(
                IdentifiedProduct(
                    product_type="fact_tag",
                    product_model="fact_tag",
                    brand=None,
                    confidence=det.confidence,
                    shelf_location="unknown",
                    visual_features=[],
                    detection_box=DetectionBox(
                        x1=abs_x1,
                        y1=abs_y1,
                        x2=abs_x2,
                        y2=abs_y2,
                        confidence=det.confidence,
                    ),
                )
            )

        self.logger.info(
            "Fact-tag prescan: detected %d tags in product area.", len(results)
        )
        return results

    async def _detect_section(
        self,
        img: Image.Image,
        section: ShelfSection,
        shelf_bbox: Tuple[int, int, int, int],
        padding: float,
        category: str,
        brand: str,
        patterns: Optional[List[str]],
        fact_tag_bboxes: Optional[List[Tuple[int, int, int, int]]] = None,
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
        self.logger.debug(
            "Section '%s': crop_bbox=%s  crop=%dx%d  downscaled=%dx%d  "
            "expected=%s",
            section.id,
            crop_bbox,
            crop.size[0],
            crop.size[1],
            crop_small.size[0],
            crop_small.size[1],
            section.products,
        )
        prompt = self._build_section_prompt(section.products, category, brand)

        try:
            async with self.pipeline.roi_client as client:
                msg = await client.ask_to_image(
                    image=crop_small,
                    prompt=prompt,
                    model=GoogleModel.GEMINI_3_FLASH_PREVIEW,
                    no_memory=True,
                    structured_output=_RawDetections,
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
        if isinstance(data, _RawDetections):
            self._normalize_raw_dets_coords(data, crop_small.size)
        elif isinstance(data, str):
            try:
                raw = json.loads(data)
                iw_s, ih_s = crop_small.size
                dets = raw.get("detections", [])
                # Collect all coord values to detect Gemini's coordinate space
                all_x = [v for d in dets for v in (d.get("bbox", {}).get("x1", 0), d.get("bbox", {}).get("x2", 0))]
                all_y = [v for d in dets for v in (d.get("bbox", {}).get("y1", 0), d.get("bbox", {}).get("y2", 0))]
                needs_norm = any(v > 1.0 for v in all_x + all_y)
                if needs_norm:
                    # Per-axis: if max coord exceeds crop dim, Gemini used 1000-space
                    nw = 1000.0 if max(all_x, default=0) > iw_s else float(iw_s)
                    nh = 1000.0 if max(all_y, default=0) > ih_s else float(ih_s)
                    for d in dets:
                        b = d.get("bbox", {})
                        b["x1"] = min(1.0, max(0.0, b.get("x1", 0) / nw))
                        b["y1"] = min(1.0, max(0.0, b.get("y1", 0) / nh))
                        b["x2"] = min(1.0, max(0.0, b.get("x2", 0) / nw))
                        b["y2"] = min(1.0, max(0.0, b.get("y2", 0) / nh))
                        # Fix inverted coordinates (Gemini sometimes swaps y1/y2)
                        if b["x1"] > b["x2"]:
                            b["x1"], b["x2"] = b["x2"], b["x1"]
                        if b["y1"] > b["y2"]:
                            b["y1"], b["y2"] = b["y2"], b["y1"]
                data = _RawDetections(**raw)
            except Exception as parse_err:
                self.logger.warning(
                    "Section '%s' coordinate recovery failed: %s",
                    section.id,
                    parse_err,
                )
                return []

        raw_dets: List[Detection] = getattr(data, "detections", None) or []

        # Remap bbox from section-crop-local to full-image coordinates
        # Discard degenerate bboxes where both edges clamped to the same value
        # (happens when Gemini returns pixel coords far outside the crop bounds)
        remapped: List[Detection] = []
        for det in raw_dets:
            full_bbox = self._remap_bbox_to_full_image(det.bbox, crop_bbox, img.size)
            bbox_w = full_bbox.x2 - full_bbox.x1
            bbox_h = full_bbox.y2 - full_bbox.y1
            if bbox_w < 0.005 or bbox_h < 0.005:
                self.logger.debug(
                    "Section '%s': discarding degenerate bbox for '%s' "
                    "(w=%.4f, h=%.4f).",
                    section.id,
                    det.label,
                    bbox_w,
                    bbox_h,
                )
                continue

            # Discard detections that overlap with known fact tag positions
            if fact_tag_bboxes:
                iw, ih = img.size
                det_px = (
                    int(full_bbox.x1 * iw),
                    int(full_bbox.y1 * ih),
                    int(full_bbox.x2 * iw),
                    int(full_bbox.y2 * ih),
                )
                is_fact_tag = False
                for ft in fact_tag_bboxes:
                    ix1 = max(det_px[0], ft[0])
                    iy1 = max(det_px[1], ft[1])
                    ix2 = min(det_px[2], ft[2])
                    iy2 = min(det_px[3], ft[3])
                    inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
                    det_area = max(
                        1, (det_px[2] - det_px[0]) * (det_px[3] - det_px[1])
                    )
                    if inter / det_area > 0.3:
                        self.logger.debug(
                            "Section '%s': discarding '%s' — overlaps "
                            "fact tag (%.0f%% of detection area).",
                            section.id,
                            det.label,
                            inter / det_area * 100,
                        )
                        is_fact_tag = True
                        break
                if is_fact_tag:
                    continue

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

    # ------------------------------------------------------------------
    # Combined flat-shelf detection
    # ------------------------------------------------------------------

    async def _detect_combined_flat_shelves(
        self,
        img: Image.Image,
        flat_shelves: List[
            Tuple[int, str, Tuple[int, int, int, int], List[str]]
        ],
        category: str,
        brand: str,
        fact_tag_bboxes: Optional[List[Tuple[int, int, int, int]]] = None,
    ) -> Dict[int, List[Detection]]:
        """Detect products across multiple flat shelves in a single LLM call.

        Combines adjacent flat-shelf bboxes into one larger crop, draws red
        horizontal lines at each shelf boundary so the vision model can
        distinguish which shelf a product belongs to, and assigns each
        detection back to the correct shelf based on its y-position.

        Args:
            img: The full input PIL image.
            flat_shelves: List of ``(shelf_idx, shelf_level, shelf_bbox,
                product_names)`` tuples sorted top-to-bottom.
            category: Product category for the prompt.
            brand: Brand name for the prompt.

        Returns:
            Dict mapping ``shelf_idx`` → ``List[Detection]`` with bbox
            coordinates in full-image normalized space.
        """
        result: Dict[int, List[Detection]] = {
            fs[0]: [] for fs in flat_shelves
        }
        if not flat_shelves:
            return result

        # Combined crop bbox (union of all shelf bboxes)
        combined_x1 = min(b[2][0] for b in flat_shelves)
        combined_y1 = min(b[2][1] for b in flat_shelves)
        combined_x2 = max(b[2][2] for b in flat_shelves)
        combined_y2 = max(b[2][3] for b in flat_shelves)
        combined_bbox = (combined_x1, combined_y1, combined_x2, combined_y2)

        cw = combined_x2 - combined_x1
        ch = combined_y2 - combined_y1
        if cw <= 0 or ch <= 0:
            return result

        crop = img.crop(combined_bbox).copy()

        # Draw shelf boundary lines and build prompt per shelf
        draw = ImageDraw.Draw(crop)
        prompt_lines: List[str] = []
        # Shelf boundary y-values in local crop coordinates for assignment
        shelf_y_ranges: List[Tuple[int, int, int]] = []  # (shelf_idx, local_y1, local_y2)

        for i, (shelf_idx, shelf_level, shelf_bbox, product_names) in enumerate(
            flat_shelves
        ):
            local_y1 = shelf_bbox[1] - combined_y1
            local_y2 = shelf_bbox[3] - combined_y1
            shelf_y_ranges.append((shelf_idx, local_y1, local_y2))

            # Draw red line at the TOP of each shelf (skip first — it's the
            # top edge of the crop)
            if i > 0:
                draw.line(
                    [(0, local_y1), (crop.width, local_y1)],
                    fill="red",
                    width=3,
                )

            names_str = ", ".join(f'"{n}"' for n in product_names)
            count_note = (
                f" (up to {len(product_names)} products)"
                if len(product_names) >= 2
                else ""
            )
            if len(flat_shelves) == 2:
                position = "UPPER" if i == 0 else "LOWER"
                prompt_lines.append(
                    f"{position} SHELF '{shelf_level}' "
                    f"({'above' if i == 0 else 'below'} the red line): "
                    f"{names_str}{count_note}"
                )
            else:
                prompt_lines.append(
                    f"SHELF '{shelf_level}': {names_str}{count_note}"
                )

        total_products = sum(len(fs[3]) for fs in flat_shelves)
        category_hint = f" {category}" if category else ""
        brand_hint = f" {brand}" if brand else ""
        prompt = (
            f"You are inspecting a retail display with "
            f"{len(flat_shelves)} product shelves of{brand_hint}"
            f"{category_hint}. There are up to {total_products} distinct "
            f"physical products total across all shelves. "
            f"Red horizontal lines mark the boundaries between shelves.\n\n"
            + "\n".join(prompt_lines)
            + "\n\nIMPORTANT: Detect only the actual physical products (devices/"
            "scanners sitting on the shelf), NOT price tags, shelf labels, or "
            "fact tags hanging from the shelf edge.\n"
            "A price tag or fact tag does NOT mean the product is present — "
            "only report a product if you can see the actual physical "
            "device/hardware on the shelf. Some slots may be EMPTY.\n"
            "Some models may look very similar — count each physical device "
            "separately even if two adjacent devices look alike.\n"
            "For each product found, return a detection with its exact "
            "label from the lists above, a confidence score, and a tight "
            "bounding box around the DEVICE. "
            "Return an empty detections list for a shelf if none are visible."
        )

        crop_small = self.pipeline._downscale_image(
            crop, max_side=1024, quality=82
        )
        self.logger.debug(
            "Combined flat shelves: crop_bbox=%s  crop=%dx%d  "
            "downscaled=%dx%d  shelves=%s",
            combined_bbox,
            crop.width,
            crop.height,
            crop_small.size[0],
            crop_small.size[1],
            [fs[1] for fs in flat_shelves],
        )

        try:
            async with self.pipeline.roi_client as client:
                msg = await client.ask_to_image(
                    image=crop_small,
                    prompt=prompt,
                    model=GoogleModel.GEMINI_3_FLASH_PREVIEW,
                    no_memory=True,
                    structured_output=_RawDetections,
                    max_tokens=4096,
                )
        except Exception as exc:
            self.logger.warning(
                "Combined flat-shelf LLM call failed: %s — treating as empty.",
                exc,
            )
            return result

        data = msg.structured_output or msg.output or {}
        if isinstance(data, _RawDetections):
            self._normalize_raw_dets_coords(data, crop_small.size)
        elif isinstance(data, str):
            try:
                raw = json.loads(data)
                iw_s, ih_s = crop_small.size
                dets = raw.get("detections", [])
                all_x = [
                    v
                    for d in dets
                    for v in (
                        d.get("bbox", {}).get("x1", 0),
                        d.get("bbox", {}).get("x2", 0),
                    )
                ]
                all_y = [
                    v
                    for d in dets
                    for v in (
                        d.get("bbox", {}).get("y1", 0),
                        d.get("bbox", {}).get("y2", 0),
                    )
                ]
                needs_norm = any(v > 1.0 for v in all_x + all_y)
                if needs_norm:
                    nw = (
                        1000.0
                        if max(all_x, default=0) > iw_s
                        else float(iw_s)
                    )
                    nh = (
                        1000.0
                        if max(all_y, default=0) > ih_s
                        else float(ih_s)
                    )
                    for d in dets:
                        b = d.get("bbox", {})
                        b["x1"] = min(1.0, max(0.0, b.get("x1", 0) / nw))
                        b["y1"] = min(1.0, max(0.0, b.get("y1", 0) / nh))
                        b["x2"] = min(1.0, max(0.0, b.get("x2", 0) / nw))
                        b["y2"] = min(1.0, max(0.0, b.get("y2", 0) / nh))
                        if b["x1"] > b["x2"]:
                            b["x1"], b["x2"] = b["x2"], b["x1"]
                        if b["y1"] > b["y2"]:
                            b["y1"], b["y2"] = b["y2"], b["y1"]
                data = _RawDetections(**raw)
            except Exception:
                self.logger.warning(
                    "Combined flat-shelf coordinate recovery failed."
                )
                return result

        raw_dets = getattr(data, "detections", None) or []

        # Assign each detection to a shelf and remap to full-image coords
        for det in raw_dets:
            full_bbox = self._remap_bbox_to_full_image(
                det.bbox, combined_bbox, img.size
            )
            bbox_w = full_bbox.x2 - full_bbox.x1
            bbox_h = full_bbox.y2 - full_bbox.y1
            if bbox_w < 0.005 or bbox_h < 0.005:
                self.logger.debug(
                    "Combined: discarding degenerate bbox for '%s' "
                    "(w=%.4f, h=%.4f).",
                    det.label,
                    bbox_w,
                    bbox_h,
                )
                continue

            # Discard detections that overlap with known fact tag positions
            if fact_tag_bboxes:
                iw, ih = img.size
                det_px = (
                    int(full_bbox.x1 * iw),
                    int(full_bbox.y1 * ih),
                    int(full_bbox.x2 * iw),
                    int(full_bbox.y2 * ih),
                )
                is_fact_tag = False
                for ft in fact_tag_bboxes:
                    # Intersection area
                    ix1 = max(det_px[0], ft[0])
                    iy1 = max(det_px[1], ft[1])
                    ix2 = min(det_px[2], ft[2])
                    iy2 = min(det_px[3], ft[3])
                    inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
                    det_area = max(1, (det_px[2] - det_px[0]) * (det_px[3] - det_px[1]))
                    if inter / det_area > 0.3:
                        self.logger.debug(
                            "Combined: discarding '%s' — overlaps fact tag "
                            "(%.0f%% of detection area).",
                            det.label,
                            inter / det_area * 100,
                        )
                        is_fact_tag = True
                        break
                if is_fact_tag:
                    continue

            # Determine shelf by bbox center y in crop-local pixels
            det_cy_local = (det.bbox.y1 + det.bbox.y2) / 2.0 * ch
            assigned_idx = flat_shelves[-1][0]  # default: last shelf
            for shelf_idx, local_y1, local_y2 in shelf_y_ranges:
                if local_y1 <= det_cy_local <= local_y2:
                    assigned_idx = shelf_idx
                    break

            result[assigned_idx].append(
                Detection(
                    label=det.label,
                    confidence=det.confidence,
                    bbox=full_bbox,
                    content=det.content,
                )
            )

        for shelf_idx, shelf_level, _, _ in flat_shelves:
            self.logger.debug(
                "Combined shelf '%s': %d detections.",
                shelf_level,
                len(result[shelf_idx]),
            )

        return result

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
                    structured_output=_RawDetections,
                    max_tokens=4096,
                )
        except Exception as exc:
            self.logger.warning(
                "Flat shelf LLM call failed: %s — treating as empty.", exc
            )
            return []

        data = msg.structured_output or msg.output or {}
        if isinstance(data, _RawDetections):
            self._normalize_raw_dets_coords(data, crop_small.size)
        elif isinstance(data, str):
            try:
                raw = json.loads(data)
                iw_s, ih_s = crop_small.size
                dets = raw.get("detections", [])
                all_x = [v for d in dets for v in (d.get("bbox", {}).get("x1", 0), d.get("bbox", {}).get("x2", 0))]
                all_y = [v for d in dets for v in (d.get("bbox", {}).get("y1", 0), d.get("bbox", {}).get("y2", 0))]
                needs_norm = any(v > 1.0 for v in all_x + all_y)
                if needs_norm:
                    nw = 1000.0 if max(all_x, default=0) > iw_s else float(iw_s)
                    nh = 1000.0 if max(all_y, default=0) > ih_s else float(ih_s)
                    for d in dets:
                        b = d.get("bbox", {})
                        b["x1"] = min(1.0, max(0.0, b.get("x1", 0) / nw))
                        b["y1"] = min(1.0, max(0.0, b.get("y1", 0) / nh))
                        b["x2"] = min(1.0, max(0.0, b.get("x2", 0) / nw))
                        b["y2"] = min(1.0, max(0.0, b.get("y2", 0) / nh))
                        if b["x1"] > b["x2"]:
                            b["x1"], b["x2"] = b["x2"], b["x1"]
                        if b["y1"] > b["y2"]:
                            b["y1"], b["y2"] = b["y2"], b["y1"]
                data = _RawDetections(**raw)
            except Exception:
                return []

        raw_dets: List[Detection] = getattr(data, "detections", None) or []
        remapped: List[Detection] = []
        for det in raw_dets:
            full_bbox = self._remap_bbox_to_full_image(det.bbox, shelf_bbox, img.size)
            bbox_w = full_bbox.x2 - full_bbox.x1
            bbox_h = full_bbox.y2 - full_bbox.y1
            if bbox_w < 0.005 or bbox_h < 0.005:
                self.logger.debug(
                    "Flat shelf: discarding degenerate bbox for '%s' "
                    "(w=%.4f, h=%.4f).",
                    det.label,
                    bbox_w,
                    bbox_h,
                )
                continue
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
