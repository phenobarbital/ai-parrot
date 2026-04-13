"""ProductOnShelves planogram type composable.

Handles planogram compliance for product-on-shelves displays (endcaps with
poster/header panels and shelved products below).
"""
import asyncio
import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple
from collections import defaultdict

from parrot_pipelines.planogram.grid.models import DetectionGridConfig, GridType
from parrot_pipelines.planogram.grid.horizontal_bands import HorizontalBands
from parrot_pipelines.planogram.grid.detector import GridDetector
from parrot_pipelines.planogram.grid.strategy import AbstractGridStrategy, NoGrid

from PIL import Image

from .abstract import AbstractPlanogramType
from parrot.models.google import GoogleModel
from parrot.models.detections import (
    Detection,
    DetectionBox,
    ShelfRegion,
    IdentifiedProduct,
    BoundingBox,
    Detections,
)
from parrot.models.compliance import (
    ComplianceResult,
    BrandComplianceResult,
    TextComplianceResult,
    ComplianceStatus,
    TextMatcher,
)


class ProductOnShelves(AbstractPlanogramType):
    """Planogram type for product-on-shelves displays.

    Implements ROI detection via poster/endcap finding, product detection,
    and compliance checking for displays with a header panel and shelved
    products below.

    Args:
        pipeline: Parent PlanogramCompliance instance.
        config: The PlanogramConfig for this compliance run.
    """

    def __init__(self, pipeline: Any, config: Any) -> None:
        super().__init__(pipeline, config)
        # Endcap geometry margins
        geometry = self.config.endcap_geometry
        self.left_margin_ratio = geometry.left_margin_ratio
        self.right_margin_ratio = geometry.right_margin_ratio

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
        """Compute the region of interest by finding the poster/endcap.

        Args:
            img: The input PIL image.

        Returns:
            Tuple of (endcap_detection, panel_detection, brand_detection,
            text_detection, raw_detections_list).
        """
        planogram_description = self.config.get_planogram_description()
        return await self._find_poster(
            img,
            planogram_description,
            partial_prompt=self.config.roi_detection_prompt,
        )

    async def detect_objects_roi(
        self,
        img: Image.Image,
        roi: Any,
    ) -> List[Detection]:
        """Detect macro objects within the ROI.

        For ProductOnShelves, macro object detection is folded into the
        main detect_objects() step (single LLM call covers both macro and
        product-level items). Returns an empty list; the orchestrator should
        pass it through to detect_objects().

        Args:
            img: The input PIL image.
            roi: ROI data from compute_roi().

        Returns:
            Empty list — macro detection is integrated into detect_objects().
        """
        return []

    def get_grid_strategy(self) -> AbstractGridStrategy:
        """Return the appropriate grid strategy for this planogram type.

        Returns HorizontalBands when detection_grid is configured with
        HORIZONTAL_BANDS, otherwise returns NoGrid (current behavior).

        Returns:
            AbstractGridStrategy instance.
        """
        grid_config = getattr(self.config, "detection_grid", None)
        if grid_config and grid_config.grid_type == GridType.HORIZONTAL_BANDS:
            return HorizontalBands()
        return NoGrid()

    async def detect_objects(
        self,
        img: Image.Image,
        roi: Any,
        macro_objects: Any,
    ) -> Tuple[List[IdentifiedProduct], List[ShelfRegion]]:
        """Detect and identify all products within the ROI.

        When detection_grid is configured, uses grid-based parallel detection
        (splitting the ROI into cells per shelf). Otherwise falls back to the
        current single-image detection path (unchanged).

        Args:
            img: The input PIL image.
            roi: ROI data from compute_roi() — used for coordinate offsets.
                 Expected to be a Detection with a bbox, or None.
            macro_objects: Macro detections from detect_objects_roi() (unused
                 for ProductOnShelves).

        Returns:
            Tuple of (identified_products, shelf_regions).
        """
        planogram_description = self.config.get_planogram_description()

        # Determine crop offset (if ROI was used, products need absolute coords)
        offset_x, offset_y = 0, 0
        target_image = img
        if roi and hasattr(roi, "bbox"):
            w, h = img.size
            x1, y1, x2, y2 = roi.bbox.get_pixel_coordinates(width=w, height=h)
            target_image = img.crop((x1, y1, x2, y2))
            offset_x, offset_y = x1, y1

        # Determine detection path: grid or legacy
        grid_config = getattr(self.config, "detection_grid", None)
        if grid_config and grid_config.grid_type != GridType.NO_GRID:
            self.logger.info(
                "Using grid detection path (grid_type=%s).", grid_config.grid_type
            )
            identified_products = await self._detect_with_grid(
                target_image, planogram_description, grid_config
            )
            # Apply ROI offset to grid results
            # (grid coords are relative to the ROI crop, not full image)
            for p in identified_products:
                if p.detection_box and (offset_x or offset_y):
                    p.detection_box.x1 += offset_x
                    p.detection_box.y1 += offset_y
                    p.detection_box.x2 += offset_x
                    p.detection_box.y2 += offset_y
            # Grid detection returns products only — shelf regions generated later
            shelf_regions: List[ShelfRegion] = []
        else:
            self.logger.info("Using legacy single-image detection path.")
            identified_products, shelf_regions = await self._detect_legacy(
                target_image, planogram_description, offset_x, offset_y
            )

        # ── Illumination enrichment (opt-in) ─────────────────────────────────
        # Reads illumination_required from the raw planogram_config dict —
        # PlanogramDescription is a sanitised Pydantic view that does NOT
        # carry illumination_required. The raw dict lives on the
        # PlanogramConfig (self.config.planogram_config).
        _pcfg = getattr(self.config, "planogram_config", None) or {}
        _raw_shelves = _pcfg.get("shelves", [])
        self.logger.debug(
            "Illumination enrichment: scanning %d raw shelves from "
            "self.config.planogram_config",
            len(_raw_shelves),
        )
        # Match by (shelf_level, product_type) rather than config `name`:
        # the LLM returns labels like 'promotional_graphic' in
        # IdentifiedProduct.product_model, which never equal the config
        # name (e.g. "Epson Scanners Header Graphic (backlit)").
        illum_keys: set = {
            (rs.get("level"), rp.get("product_type"))
            for rs in _raw_shelves
            for rp in rs.get("products", [])
            if rp.get("illumination_required")
            and rs.get("level")
            and rp.get("product_type")
        }

        if illum_keys:
            illum_result: Optional[str] = None  # cached — one LLM call per image
            for ip in identified_products:
                if (ip.shelf_location, ip.product_type) in illum_keys:
                    if illum_result is None:
                        zone_bbox = ip.detection_box if ip.detection_box else None
                        illum_result = await self._check_illumination(
                            img,
                            zone_bbox=zone_bbox,
                            roi=roi,
                            planogram_description=planogram_description,
                        )
                        self.logger.info(
                            "Illumination check result for shelf=%s type=%s "
                            "(model=%r): %s",
                            ip.shelf_location,
                            ip.product_type,
                            ip.product_model,
                            illum_result,
                        )
                    if illum_result is not None:
                        ip.visual_features = [illum_result] + list(
                            ip.visual_features or []
                        )
        # ── end illumination enrichment ───────────────────────────────────────

        return identified_products, shelf_regions

    async def _detect_with_grid(
        self,
        target_image: Image.Image,
        planogram_description: Any,
        grid_config: DetectionGridConfig,
    ) -> List[IdentifiedProduct]:
        """Run grid-based parallel per-cell LLM detection.

        Args:
            target_image: The (ROI-cropped) image to detect in.
            planogram_description: PlanogramDescription for this run.
            grid_config: Grid configuration.

        Returns:
            Merged, deduplicated list of IdentifiedProduct.
        """
        strategy = self.get_grid_strategy()
        roi_bbox = (0, 0, target_image.size[0], target_image.size[1])
        cells = strategy.compute_cells(
            roi_bbox=roi_bbox,
            image_size=target_image.size,
            planogram_description=planogram_description,
            grid_config=grid_config,
        )

        self.logger.info(
            "Grid detection: %d cells computed for %d shelves.",
            len(cells),
            len(getattr(planogram_description, "shelves", [])),
        )

        detector = GridDetector(
            llm=self.pipeline.llm,
            reference_images=self.pipeline.reference_images or {},
            logger=self.logger,
        )
        return await detector.detect_cells(cells, target_image, grid_config)

    async def _detect_legacy(
        self,
        target_image: Image.Image,
        planogram_description: Any,
        offset_x: int,
        offset_y: int,
    ) -> Tuple[List[IdentifiedProduct], List[ShelfRegion]]:
        """Legacy single-image detection path (original implementation).

        This method contains the UNCHANGED original detect_objects logic.
        Do NOT modify this method — it must remain byte-for-byte equivalent
        to the pre-refactor implementation.

        Args:
            target_image: The (ROI-cropped) image to detect in.
            planogram_description: PlanogramDescription for this run.
            offset_x: Horizontal offset from ROI crop (pixels).
            offset_y: Vertical offset from ROI crop (pixels).

        Returns:
            Tuple of (identified_products, shelf_regions).
        """
        # Build product-name hints from planogram config
        hints = []
        if planogram_description:
            for shelf in getattr(planogram_description, "shelves", []):
                for p in getattr(shelf, "products", []):
                    if name := getattr(p, "name", ""):
                        hints.append(name)

        hints_str = ", ".join(set(hints))
        prompt = (
            "Detect all retail products, empty slots, and shelf regions in this image.\n"
            "Use the provided reference images to identify specific products.\n\n"
            "IMPORTANT:\n"
            "- If you see a cardboard box containing a product image/name, label it as \"[Product Name] box\".\n"
            "- If you see the bare product itself (e.g. a loose printer), label it as \"[Product Name]\".\n"
            f"- Prefer the following product names if they match: {hints_str}\n"
            "- If an item is NOT in the list, provide a descriptive name (e.g. \"Ink Bottle\", \"Printer\") "
            "rather than just \"unknown\".\n"
            "- Do not output \"unknown\" unless strictly necessary.\n\n"
            "Output a JSON list where each entry contains:\n"
            "- \"label\": The identified product name/model or 'shelf' or 'unknown'.\n"
            "- \"box_2d\": [ymin, xmin, ymax, xmax] normalized 0-1000.\n"
            "- \"confidence\": 0-1.\n"
            "- \"type\": \"product\" (for loose items), \"product_box\" (for boxes), \"shelf\", \"gap\".\n"
        )

        # Flatten reference images — values may be a single image or a list of images
        # (PlanogramConfig.reference_images was widened in TASK-588 to support multi-ref
        # per product; the legacy path must flatten to avoid passing nested lists to the LLM).
        refs: List[Any] = []
        for v in (self.pipeline.reference_images or {}).values():
            if isinstance(v, list):
                refs.extend(v)
            else:
                refs.append(v)

        _output_format = (
            "\n\nOutput a JSON array where each entry contains:\n"
            '- "label": The item label.\n'
            '- "box_2d": [ymin, xmin, ymax, xmax] normalized 0-1000.\n'
            '- "confidence": 0.0-1.0.\n'
            '- "type": "product", "promotional_graphic", "fact_tag", "shelf", or "gap".\n'
        )
        _base_prompt = getattr(self.config, "object_identification_prompt", None) or prompt
        obj_prompt = _base_prompt + _output_format

        detected_items = await self.pipeline.llm.detect_objects(
            image=target_image,
            prompt=obj_prompt,
            reference_images=refs,
            output_dir=None,
        )

        shelf_regions: List[ShelfRegion] = []
        identified_products: List[IdentifiedProduct] = []

        self.logger.debug("Detected %d items from LLM.", len(detected_items))

        for item in detected_items:
            box = item.get("box_2d")
            if not box:
                continue

            # FIXME: box_2d from the LLM is [ymin, xmin, ymax, xmax] (see spec §6),
            # but this legacy path unpacks as (x1=ymin, y1=xmin, x2=ymax, y2=xmax),
            # swapping the x/y axes. The GridDetector path (detector.py) parses this
            # correctly. Fixing here would break existing callers that rely on the
            # current (swapped) coordinate layout — tracked as tech-debt to resolve
            # once all consumers of detection_box are audited.
            x1, y1, x2, y2 = box
            abs_x1 = x1 + offset_x
            abs_y1 = y1 + offset_y
            abs_x2 = x2 + offset_x
            abs_y2 = y2 + offset_y

            label = item.get("label", "unknown")
            conf = item.get("confidence", 0.0)
            if "shelf" in label.lower():
                shelf_regions.append(
                    ShelfRegion(
                        shelf_id=f"shelf_{len(shelf_regions)}",
                        level=label,
                        bbox=DetectionBox(
                            x1=abs_x1, y1=abs_y1, x2=abs_x2, y2=abs_y2, confidence=conf
                        ),
                    )
                )
            else:
                ptype = item.get("type", "product")
                if "box" in label.lower() or "carton" in label.lower():
                    ptype = "product_box"
                identified_products.append(
                    IdentifiedProduct(
                        detection_box=DetectionBox(
                            x1=abs_x1, y1=abs_y1, x2=abs_x2, y2=abs_y2, confidence=conf
                        ),
                        product_model=label,
                        confidence=conf,
                        product_type=ptype,
                    )
                )

        return identified_products, shelf_regions

    def check_planogram_compliance(
        self,
        identified_products: List[IdentifiedProduct],
        planogram_description: Any,
    ) -> List[ComplianceResult]:
        """Check compliance of identified products against the planogram."""
        # All LLM aliases that map to a promotional_graphic concept
        _PROMO_TYPES = {
            "promotional_graphic", "graphic", "banner", "backlit_graphic", "backlit",
            "advertisement", "advertisement_graphic", "display_graphic",
            "promotional_display", "promotional_material", "promotional_materials",
            "text_overlay",  # injected utility carrier for poster OCR text
        }

        # Configurable product subtypes — custom types declared in
        # planogram_config.product_subtypes that should match 'product'.
        # NOTE: PlanogramDescription is a Pydantic view that does NOT expose
        # the raw planogram_config. Read it from self.config (PlanogramConfig)
        # which holds the raw dict.
        _pcfg = getattr(self.config, 'planogram_config', None) or {}
        if isinstance(_pcfg, dict):
            _product_subtypes = set(_pcfg.get('product_subtypes', []))
        else:
            _product_subtypes = set(getattr(_pcfg, 'product_subtypes', []) or [])

        # Raw shelves for illumination penalty lookups (non-Pydantic fields).
        _raw_shelves = _pcfg.get("shelves", []) if isinstance(_pcfg, dict) else []

        def _find_raw_illum_required(shelf_level: str, product_name: str) -> Optional[str]:
            """Return illumination_required value for a product, or None."""
            for rs in _raw_shelves:
                if rs.get("level") == shelf_level:
                    for rp in rs.get("products", []):
                        if rp.get("name") == product_name:
                            return rp.get("illumination_required")
            return None

        def _find_raw_illum_penalty(shelf_level: str, product_name: str) -> float:
            """Return illumination_penalty for a product (default 0.5)."""
            for rs in _raw_shelves:
                if rs.get("level") == shelf_level:
                    for rp in rs.get("products", []):
                        if rp.get("name") == product_name:
                            return float(rp.get("illumination_penalty", 0.5))
            return 0.5  # ProductOnShelves default (endcap uses 1.0)

        def _matches(ek, fk) -> bool:
            (e_ptype, e_base), (f_ptype, f_base) = ek, fk

            # Relaxed type matching
            type_match = (e_ptype == f_ptype)
            if not type_match:
                # specific overrides
                if {e_ptype, f_ptype} <= {"printer", "product"}:
                    type_match = True
                # product_box is a subtype of product
                elif {e_ptype, f_ptype} <= {"product", "product_box"}:
                    type_match = True
                # promotional_graphic in config may be detected as 'product' by LLM
                elif "promotional_graphic" in {e_ptype, f_ptype} and "product" in {e_ptype, f_ptype}:
                    type_match = True
                # Any promo-like type aliases are treated as equivalent
                elif e_ptype in _PROMO_TYPES and f_ptype in _PROMO_TYPES:
                    type_match = True
                # Custom semantic product types (e.g. soundbar, headphones, camera)
                # are never returned by the LLM; allow them to match 'product'.
                elif "product" in {e_ptype, f_ptype}:
                    other_type = f_ptype if e_ptype == "product" else e_ptype
                    # 1) Configurable: planogram_config.product_subtypes
                    if _product_subtypes and other_type in _product_subtypes:
                        type_match = True
                    else:
                        # 2) Hardcoded fallback for unlisted types
                        _non_product_types = {
                            "promotional_graphic", "graphic", "banner", "backlit_graphic",
                            "backlit", "advertisement", "advertisement_graphic",
                            "display_graphic", "promotional_display", "promotional_material",
                            "promotional_materials", "product_box", "printer",
                            "fact_tag", "price_tag", "slot", "brand_logo", "gap", "shelf",
                        }
                        if other_type not in _non_product_types:
                            type_match = True

            if not type_match:
                return False
            if not e_base or not f_base:
                return True
            if not e_base:
                return True
            if f_base == e_base or e_base in f_base or f_base in e_base:
                return True
            if e_ptype == "promotional_graphic":
                def fam(s):
                    return "canvas-tv" if "canvas-tv" in s else s
                return fam(e_base) == fam(f_base)
            return e_base in f_base or f_base in e_base

        results: List[ComplianceResult] = []
        planogram_brand = planogram_description.brand.lower()
        norm_patterns = planogram_description.model_normalization_patterns or None
        found_brand_product = next((
            p for p in identified_products if p.brand and p.brand.lower() == planogram_brand
        ), None)

        brand_compliance_result = BrandComplianceResult(
            expected_brand=planogram_description.brand,
            found_brand=found_brand_product.brand if found_brand_product else None,
            found=bool(found_brand_product),
            confidence=found_brand_product.confidence if found_brand_product else 0.0
        )
        brand_check_ok = brand_compliance_result.found
        by_shelf = defaultdict(list)

        for p in identified_products:
            by_shelf[p.shelf_location].append(p)

        globally_matched_keys: set = set()

        # Pre-build the set of ALL expected canonical keys across every shelf.
        # Used to protect misassigned products: if a product is expected on shelf
        # A but spatially landed on shelf B, it should not count as "unexpected"
        # on shelf B (it will already appear as "missing" on shelf A instead).
        all_expected_keys: set = set()
        for _shelf_cfg in planogram_description.shelves:
            for _sp in _shelf_cfg.products:
                if _sp.product_type in ("fact_tag", "price_tag", "slot"):
                    continue
                _ek = self._canonical_expected_key(
                    _sp, brand=planogram_brand, patterns=norm_patterns
                )
                all_expected_keys.add(_ek)

        for shelf_cfg in planogram_description.shelves:
            shelf_level = shelf_cfg.level
            products_on_shelf = by_shelf.get(shelf_level, [])
            expected = []
            expected_names = []
            expected_products = []  # parallel list of original shelf product configs

            for sp in shelf_cfg.products:
                if sp.product_type in ("fact_tag", "price_tag", "slot"):
                    continue
                e_ptype, e_base = self._canonical_expected_key(sp, brand=planogram_brand, patterns=norm_patterns)
                expected.append((e_ptype, e_base))
                expected_names.append(sp.name)
                expected_products.append(sp)

            found_keys = []
            found_lookup = []
            found_products = []  # parallel list of original IdentifiedProduct objects
            promos = []
            for p in products_on_shelf:
                # text_overlay carries OCR for the text check but is not a matchable product
                if p.product_type == "text_overlay":
                    promos.append(p)
                    continue
                if p.product_type in ("fact_tag", "price_tag", "slot", "brand_logo", "gap", "shelf"):
                    continue
                f_ptype, f_base, f_conf = self._canonical_found_key(p, brand=planogram_brand, patterns=norm_patterns)
                found_keys.append((f_ptype, f_base))
                found_products.append(p)
                if p.product_type in _PROMO_TYPES:
                    promos.append(p)
                label = p.product_model or p.product_type or "unknown"
                found_lookup.append((f_ptype, f_base, label))

            matched = [False] * len(expected)
            consumed = [False] * len(found_keys)
            visual_feature_scores = []
            # (i_expected_idx, j_found_idx, detected_state, expected_state, penalty)
            illum_mismatches: list = []

            for i, ek in enumerate(expected):
                for j, fk in enumerate(found_keys):
                    if matched[i] or consumed[j]:
                        continue
                    match_result = _matches(ek, fk)
                    if match_result:
                        matched[i] = True
                        consumed[j] = True
                        globally_matched_keys.add(fk)
                        shelf_product = expected_products[i]
                        identified_product = found_products[j]
                        if hasattr(shelf_product, 'visual_features') and shelf_product.visual_features:
                            detected_features = getattr(identified_product, 'visual_features', []) or []
                            # Only score visual features when enrichment was actually
                            # performed (detected_features non-empty).  If the product
                            # was found geometrically but no OCR/visual enrichment ran
                            # (e.g. 'product' type items), skip the penalty so the
                            # score reflects detection success, not enrichment absence.
                            if detected_features:
                                vf_score = self._calculate_visual_feature_match(
                                    shelf_product.visual_features, detected_features
                                )
                                visual_feature_scores.append(vf_score)
                        # Illumination penalty check (opt-in, only if config declares it)
                        _illum_req = _find_raw_illum_required(shelf_level, shelf_product.name)
                        if _illum_req is not None:
                            _detected_illum = self._extract_illumination_state(
                                getattr(identified_product, 'visual_features', []) or []
                            )
                            self.logger.info(
                                "Illumination check for %s: expected=%s detected=%s",
                                shelf_product.name, _illum_req, _detected_illum,
                            )
                            if (
                                _detected_illum is not None
                                and _detected_illum != _illum_req.strip().lower()
                            ):
                                _penalty = _find_raw_illum_penalty(shelf_level, shelf_product.name)
                                illum_mismatches.append(
                                    (i, j, _detected_illum, _illum_req.strip().lower(), _penalty)
                                )
                        break

            expected_readable = expected_names
            # Build found_readable — update labels for illumination-mismatch products.
            _mismatch_j = {j_idx: det for (_, j_idx, det, _, _) in illum_mismatches}
            found_readable = []
            for k, (used, (f_ptype, f_base), (_, _, original_label)) in enumerate(
                zip(consumed, found_keys, found_lookup)
            ):
                label = original_label
                if k in _mismatch_j:
                    label = f"{original_label} (LIGHT_{_mismatch_j[k].upper()})"
                found_readable.append(label)

            missing = [expected_readable[i] for i, ok in enumerate(matched) if not ok]
            # Append illumination mismatch entries to missing list.
            for (i_idx, _j, det, exp_s, _pen) in illum_mismatches:
                missing.append(
                    f"{expected_readable[i_idx]} — backlight {det.upper()} (required: {exp_s.upper()})"
                )
            unexpected = []
            if not shelf_cfg.allow_extra_products:
                for used, (f_ptype, f_base), (_, _, original_label) in zip(consumed, found_keys, found_lookup):
                    if not used and (f_ptype, f_base) not in globally_matched_keys:
                        # Also protect products that ARE expected somewhere else in
                        # the planogram but landed on the wrong shelf due to spatial
                        # misassignment. They will already appear as "missing" on
                        # their correct shelf — no need to double-penalise.
                        expected_elsewhere = any(
                            _matches((ek_ptype, ek_base), (f_ptype, f_base))
                            for (ek_ptype, ek_base) in all_expected_keys
                        )
                        if expected_elsewhere:
                            self.logger.debug(
                                f"all_expected_keys protected shelf='{shelf_level}' "
                                f"model='{original_label}' key=({f_ptype},{f_base}) "
                                f"— expected on another shelf"
                            )
                        else:
                            unexpected.append(original_label)
                    elif not used:
                        self.logger.debug(
                            f"globally_matched_keys protected shelf='{shelf_level}' "
                            f"model='{original_label}' key=({f_ptype},{f_base}) from unexpected"
                        )

            basic_score = (
                sum(1 for ok in matched if ok) / (len(expected) or 1.0)
            )

            visual_feature_score = 1.0
            if visual_feature_scores:
                visual_feature_score = sum(visual_feature_scores) / len(visual_feature_scores)

            text_results, text_score, overall_text_ok = [], 1.0, True
            endcap = planogram_description.advertisement_endcap
            if endcap and endcap.enabled and endcap.position == shelf_level:
                if endcap.text_requirements:
                    all_features = []
                    ocr_blocks = []
                    for promo in promos:
                        if getattr(promo, "visual_features", None):
                            all_features.extend(promo.visual_features)
                            for feat in promo.visual_features:
                                if isinstance(feat, str) and feat.startswith("ocr:"):
                                    ocr_blocks.append(feat[4:].strip())
                            ocr_text = getattr(promo, 'ocr_text', None) or getattr(promo.detection_box, 'ocr_text', '')
                            if ocr_text:
                                ocr_blocks.append(ocr_text.strip())
                    if ocr_blocks:
                        ocr_norm = self._normalize_ocr_text(" ".join(ocr_blocks))
                        if ocr_norm:
                            all_features.append(ocr_norm)

                    if not promos and shelf_level == "header":
                        overall_text_ok = False
                        for text_req in endcap.text_requirements:
                            text_results.append(TextComplianceResult(
                                required_text=text_req.required_text,
                                found=False,
                                matched_features=[],
                                confidence=0.0,
                                match_type=text_req.match_type
                            ))
                    else:
                        for text_req in endcap.text_requirements:
                            result = TextMatcher.check_text_match(
                                required_text=text_req.required_text,
                                visual_features=all_features,
                                match_type=text_req.match_type,
                                case_sensitive=text_req.case_sensitive,
                                confidence_threshold=text_req.confidence_threshold
                            )
                            text_results.append(result)
                            if not result.found and text_req.mandatory:
                                overall_text_ok = False
                        if text_results:
                            text_score = sum(
                                r.confidence for r in text_results if r.found
                            ) / len(text_results)

            elif shelf_level != "header":
                overall_text_ok = True
                text_score = 1.0

            threshold = getattr(
                shelf_cfg,
                "compliance_threshold",
                planogram_description.global_compliance_threshold or 0.8
            )
            major_unexpected = [
                p for p in unexpected
                if "ink" not in p.lower()
                and "price tag" not in p.lower()
                and "fact_tag" not in p.lower()
                and "fact tag" not in p.lower()
            ]

            status = ComplianceStatus.NON_COMPLIANT
            if shelf_level != "header":
                if basic_score >= threshold and not major_unexpected and not illum_mismatches:
                    status = ComplianceStatus.COMPLIANT
                elif basic_score == 0.0 and len(expected) > 0:
                    status = ComplianceStatus.MISSING
            else:
                if not brand_check_ok:
                    status = ComplianceStatus.NON_COMPLIANT
                elif (
                    basic_score >= threshold
                    and not major_unexpected
                    and overall_text_ok
                    and not illum_mismatches
                ):
                    status = ComplianceStatus.COMPLIANT
                elif basic_score == 0.0 and len(expected) > 0:
                    status = ComplianceStatus.MISSING
                else:
                    status = ComplianceStatus.NON_COMPLIANT

            visual_weight = getattr(
                planogram_description,
                'visual_features_weight',
                0.2
            )
            if shelf_level == "header" and endcap:
                adjusted_product_weight = endcap.product_weight * (1 - visual_weight)
                visual_feature_weight = endcap.product_weight * visual_weight
                combined_score = (
                    (basic_score * adjusted_product_weight) +
                    (text_score * endcap.text_weight) +
                    (brand_compliance_result.confidence * getattr(endcap, "brand_weight", 0.0)) +
                    (visual_feature_score * visual_feature_weight)
                )
            else:
                # Per-shelf weights override globals when defined in planogram_config
                s_visual_weight = shelf_cfg.visual_weight if shelf_cfg.visual_weight is not None else visual_weight
                s_text_weight = shelf_cfg.text_weight if shelf_cfg.text_weight is not None else 0.1
                s_product_weight = shelf_cfg.product_weight if shelf_cfg.product_weight is not None else (1 - s_visual_weight)
                combined_score = (
                    basic_score * s_product_weight +
                    text_score * s_text_weight +
                    visual_feature_score * s_visual_weight
                )

            # Apply illumination penalty at combined_score level so the user-facing
            # compliance % is clearly interpretable (100% light ON, 50% light OFF,
            # 0% product missing — assuming penalty=0.5).  The penalty scales the
            # full combined_score rather than only the product component, so a
            # single mismatch produces an unambiguous drop regardless of how
            # product/text/visual weights are distributed.
            if illum_mismatches:
                _n = len(expected) or 1
                _total_penalty = sum(_pen for (_, _, _, _, _pen) in illum_mismatches) / _n
                combined_score *= max(0.0, 1.0 - _total_penalty)

            combined_score = min(1.0, max(0.0, combined_score))
            text_score = min(1.0, max(0.0, text_score))

            results.append(
                ComplianceResult(
                    shelf_level=shelf_level,
                    expected_products=expected_readable,
                    found_products=found_readable,
                    missing_products=missing,
                    unexpected_products=unexpected,
                    compliance_status=status,
                    compliance_score=combined_score,
                    text_compliance_results=text_results,
                    text_compliance_score=text_score,
                    overall_text_compliant=overall_text_ok,
                    brand_compliance_result=brand_compliance_result
                )
            )
        return results

    # ------------------------------------------------------------------
    # Helper methods (migrated from PlanogramCompliance)
    # ------------------------------------------------------------------

    async def _find_poster(
        self,
        image: Image.Image,
        planogram: Any,  # PlanogramDescription
        partial_prompt: str,
    ) -> Any:
        """Ask VISION Model to find the main promotional graphic."""
        brand = (getattr(planogram, "brand", "") or "").strip()
        tags = [t.strip() for t in getattr(planogram, "tags", []) or []]
        endcap = getattr(planogram, "advertisement_endcap", None)
        geometry = self.config.endcap_geometry
        if endcap and getattr(endcap, "text_requirements", None):
            for tr in endcap.text_requirements:
                if getattr(tr, "required_text", None):
                    tags.append(tr.required_text)
        tag_hint = ", ".join(sorted({f"'{t}'" for t in tags if t}))

        # downscale for LLM
        image_small = self.pipeline._downscale_image(image, max_side=1024, quality=78)
        prompt = partial_prompt.format(
            brand=brand,
            tag_hint=tag_hint,
            image_size=image_small.size
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
                        max_tokens=8192
                    )
                break
            except Exception as e:
                if attempt < max_attempts - 1:
                    await asyncio.sleep(10)
                else:
                    raise e

        data = msg.structured_output or msg.output or {}
        # If Pydantic validation failed (e.g. LLM returned pixel coords instead
        # of normalized), 'data' will be a raw JSON string.  Try to recover by
        # normalizing the bbox values against the downscaled image dimensions.
        if isinstance(data, str):
            import json as _json
            try:
                raw = _json.loads(data)
                iw, ih = image_small.size
                for d in raw.get("detections", []):
                    b = d.get("bbox", {})
                    # If any coordinate exceeds 1.0 it's in pixel space -> normalize.
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

        def _first_by_labels(labels: List[str]) -> Optional[Detection]:
            wanted = {lbl.strip().lower() for lbl in labels}
            return next((d for d in dets if _norm_label(d) in wanted), None)

        panel_det = (
            _first_by_labels(["poster_panel", "poster"])
            or (max(dets, key=lambda x: float(x.confidence)) if dets else None)
        )

        text_det = _first_by_labels(["poster_text"])
        brand_det = _first_by_labels(["brand_logo", "brand logo"])

        if not panel_det:
            self.logger.error(
                "Critical failure: Could not detect the poster_panel."
            )
            return None, None, None, None, []

        promo_graphic_det = _first_by_labels(["promotional_graphic"])

        if promo_graphic_det and panel_det:
            if not (promo_graphic_det.bbox.x1 >= panel_det.bbox.x1 and promo_graphic_det.bbox.x2 <= panel_det.bbox.x2):
                panel_det.bbox.x1 = min(panel_det.bbox.x1, promo_graphic_det.bbox.x1)
                panel_det.bbox.x2 = max(panel_det.bbox.x2, promo_graphic_det.bbox.x2)

        config_width_percent = geometry.width_margin_percent
        config_height_percent = geometry.height_margin_percent
        config_top_margin_percent = geometry.top_margin_percent
        side_margin_percent = geometry.side_margin_percent

        # If planogram has is_background shelves (e.g. a wide promotional panel
        # that may sit *beside* the product display), force full image width so
        # the ROI crop always includes the background graphic.
        has_background_shelf = any(
            getattr(s, "is_background", False)
            for s in (getattr(planogram, "shelves", None) or [])
        )
        if has_background_shelf:
            side_margin_percent = max(side_margin_percent, 0.5)

        panel_det.bbox.x1 = max(0.0, panel_det.bbox.x1 - side_margin_percent)
        panel_det.bbox.x2 = min(1.0, panel_det.bbox.x2 + side_margin_percent)

        if panel_det and text_det:
            text_bottom_y2 = text_det.bbox.y2
            padding = 0.08
            new_panel_y2 = min(text_bottom_y2 + padding, 1.0)
            panel_det.bbox.y2 = new_panel_y2

        # Consolidate endcap logic
        endcap_det = _first_by_labels(["endcap", "endcap_roi", "endcap-roi", "endcap roi"])
        px1, py1, px2, py2 = panel_det.bbox.x1, panel_det.bbox.y1, panel_det.bbox.x2, panel_det.bbox.y2

        if endcap_det:
            # If endcap found, ensure it includes the poster (UNION)
            ex1 = min(endcap_det.bbox.x1, px1)
            ey1 = min(endcap_det.bbox.y1, py1)
            ex2 = max(endcap_det.bbox.x2, px2)
            ey2 = max(endcap_det.bbox.y2, py2)
        else:
            # If no endcap, start with poster
            ex1, ey1, ex2, ey2 = px1, py1, px2, py2
            # Heuristic: The Endcap usually includes a riser/shelf below the poster.
            # Extend downwards by ~35% of poster height to capture it.
            panel_h = py2 - py1
            ey2 = min(1.0, ey2 + (panel_h * 0.35))

        # Add horizontal buffer
        x_buffer = max(
            self.left_margin_ratio * (px2 - px1), self.right_margin_ratio * (px2 - px1)
        )
        ex1 = min(ex1, px1 - x_buffer)
        ex2 = max(ex2, px2 + x_buffer)

        # If the endcap is a header with shelves below, use the panel to set width
        # but extend ROI height to cover the full display.
        full_height_hint = False
        if endcap and getattr(endcap, "position", None) == "header" and getattr(endcap, "full_height_roi", True):
            shelves = getattr(planogram, "shelves", []) or []
            has_non_header = any(
                getattr(s, "level", None) and getattr(s, "level") != "header"
                for s in shelves
            )
            full_height_hint = has_non_header
        if full_height_hint:
            ey2 = 1.0
            ey1 = min(ey1, py1)

        # Clip to image bounds
        ex1 = max(0.0, ex1)
        ex2 = min(1.0, ex2)
        if ex2 <= ex1:
            ex2 = ex1 + 1e-6
        ey1 = max(0.0, ey1)
        ey2 = min(1.0, ey2)
        if ey2 <= ey1:
            ey2 = ey1 + 1e-6

        if endcap_det is None:
            endcap_det = Detection(
                label="endcap",
                confidence=0.9,
                content=None,
                bbox=BoundingBox(x1=ex1, y1=ey1, x2=ex2, y2=ey2)
            )
        else:
            endcap_det.bbox.x1 = ex1
            endcap_det.bbox.x2 = ex2
            endcap_det.bbox.y1 = ey1
            endcap_det.bbox.y2 = ey2

        return endcap_det, panel_det, brand_det, text_det, dets

    def _base_model_from_str(
        self, s: str, brand: str = None, patterns: Optional[List[str]] = None
    ) -> str:
        """Extract normalized base model from any text, supporting multiple brands.

        If ``patterns`` is provided (from planogram_config.model_normalization_patterns),
        those regex patterns are tried first and replace the generic defaults.
        Each pattern's captured groups are joined with '-' to form the key.
        Brand-specific and generic fallbacks only run when no configured patterns exist.
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

    def _canonical_expected_key(
        self, sp: Any, brand: str, patterns: Optional[List[str]] = None
    ) -> Tuple[str, str]:
        """Compute canonical key for an expected product from planogram config."""
        ptype = (getattr(sp, "product_type", "") or "").strip().lower()
        type_mappings = {
            "tv_demonstration": "tv",
            "promotional_graphic": "promotional_graphic",
            "product_box": "product_box",
            "printer": "printer",
            "promotional_materials": "promotional_materials"
        }
        ptype = type_mappings.get(ptype, ptype)
        model_str = getattr(sp, "name", "") or getattr(sp, "product_model", "") or ""
        base = self._base_model_from_str(model_str, brand=brand, patterns=patterns)
        return ptype or "unknown", base or ""

    def _canonical_found_key(
        self, p: Any, brand: str, patterns: Optional[List[str]] = None
    ) -> Tuple[str, str, float]:
        """Compute canonical key for a detected/found product."""
        ptype = (getattr(p, "product_type", "") or "").strip().lower()
        type_mappings = {
            "tv_demonstration": "tv",
            "promotional_graphic": "promotional_graphic",
            "product_box": "product_box",
            "printer": "printer",
            "promotional_material": "promotional_material",
            "promotional_display": "promotional_display"
        }
        ptype = type_mappings.get(ptype, ptype)
        model_str = getattr(p, "product_model", "") or getattr(p, "product_type", "") or ""
        base = self._base_model_from_str(model_str, brand=brand, patterns=patterns)
        conf = float(getattr(p, "confidence", 0.0) or 0.0)

        # Only reclassify as product_box for generic types; never override promotional types
        _no_reclassify = {"promotional_graphic", "graphic", "banner", "backlit_graphic", "backlit",
                          "advertisement", "advertisement_graphic", "promotional_display",
                          "promotional_material", "promotional_materials"}
        if ptype not in _no_reclassify and self._looks_like_box(getattr(p, "visual_features", None)):
            if ptype != "product_box":
                ptype = "product_box"
            conf = min(1.0, conf + 0.05)
        return ptype or "unknown", base or "", conf

    def _looks_like_box(self, visual_features: Optional[List[str]]) -> bool:
        """Check if visual features suggest a product box."""
        if not visual_features:
            return False
        # Use whole-word match for "box" to avoid false positives like "lightbox"
        whole_word_keywords = {"packaging", "package", "cardboard", "blue packaging", "printer image on box"}
        norm = " ".join(visual_features).lower()
        if any(k in norm for k in whole_word_keywords):
            return True
        # "box" only as whole word (not part of "lightbox", "mailbox", etc.)
        if re.search(r'\bbox\b', norm):
            return True
        return False

    def _normalize_ocr_text(self, s: str) -> str:
        """Normalize OCR text for comparison."""
        if not s:
            return ""
        s = unicodedata.normalize("NFKC", s)
        s = "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch))
        s = re.sub(r"[\u2014\u2013\u2010-\u2012\u2e3a\u2026\u201c\u201d\"'\u00b7\u2022\u2219\u00b7\u2022\u2014\u2013/\\|_=+^°™®©§]", " ", s)
        s = re.sub(r"[^A-Za-z0-9 ]+", " ", s)
        s = re.sub(r"\s+", " ", s).strip().lower()
        return s

    def _calculate_visual_feature_match(
        self,
        expected_features: List[str],
        detected_features: List[str],
    ) -> float:
        """Calculate match score between expected and detected visual features."""
        if not expected_features:
            return 1.0
        if not detected_features:
            return 0.0

        def extract_keywords(text):
            text = text.lower().strip()
            stop_words = {
                'a', 'an', 'the', 'is', 'are', 'on', 'of', 'in', 'at',
                'to', 'for', 'with', 'visible', 'displayed', 'showing'
            }
            words = [w for w in text.split() if w not in stop_words and len(w) > 1]
            return set(words)

        semantic_mappings = {
            'active': ['active', 'on', 'powered', 'illuminated', 'lit'],
            'display': ['display', 'screen', 'tv', 'television', 'monitor'],
            'illuminated': ['illuminated', 'backlit', 'lit', 'bright', 'glowing'],
            'logo': ['logo', 'text', 'branding', 'brand'],
            'dynamic': ['dynamic', 'colorful', 'graphics', 'content'],
            'official': ['official', 'partner'],
            'white': ['white', 'large']
        }

        def semantic_match(expected_word, detected_keywords):
            if expected_word in detected_keywords:
                return True
            if expected_word in semantic_mappings:
                synonyms = semantic_mappings[expected_word]
                return any(syn in detected_keywords for syn in synonyms)
            return any(expected_word in keyword for keyword in detected_keywords)

        matches = 0
        for expected in expected_features:
            expected_keywords = extract_keywords(expected)
            all_detected_keywords = set()
            for detected in detected_features:
                all_detected_keywords.update(extract_keywords(detected))

            feature_matched = False
            for exp_keyword in expected_keywords:
                if semantic_match(exp_keyword, all_detected_keywords):
                    feature_matched = True
                    break

            if feature_matched:
                matches += 1

        return matches / len(expected_features)

    def _get_default_shelf_configs(self) -> List[Dict[str, Any]]:
        """Return default shelf configuration when no planogram config is provided.

        Default: Header (0.34), Middle (0.25), Bottom (rest ~0.41).
        """
        return [
            {"level": "header", "height_ratio": 0.34},
            {"level": "middle", "height_ratio": 0.25},
            {"level": "bottom", "height_ratio": 0.41},
        ]

    def _generate_virtual_shelves(
        self,
        roi_bbox: DetectionBox,
        image_size: Tuple[int, int],
        planogram: Any,
    ) -> List[ShelfRegion]:
        """Generate virtual shelf regions based on ROI and planogram configuration ratios."""
        w, h = image_size
        r_x1, r_y1, r_x2, r_y2 = roi_bbox.x1, roi_bbox.y1, roi_bbox.x2, roi_bbox.y2

        # Ensure absolute coords
        if r_x1 <= 1.0 and r_x2 <= 1.0:
            r_x1 *= w
            r_y1 *= h
            r_x2 *= w
            r_y2 *= h

        roi_h = r_y2 - r_y1
        shelves = []
        current_y = r_y1

        # Get shelf config from planogram
        # If no config, fallback to default thirds: Header (0.34), Middle (0.25), Bottom (rest)
        shelf_configs = getattr(planogram, "shelves", []) or self._get_default_shelf_configs()
        shelf_padding_ratio = 0.0
        if hasattr(self.config, "endcap_geometry"):
            shelf_padding_ratio = float(getattr(self.config.endcap_geometry, "inter_shelf_padding", 0.0) or 0.0)
        allow_overlap = getattr(planogram, "allow_overlap", False)
        if not allow_overlap and hasattr(planogram, "planogram_config") and isinstance(planogram.planogram_config, dict):
            allow_overlap = planogram.planogram_config.get("allow_overlap", False)
            if not allow_overlap:
                # Also check nested under 'aisle' key (common config pattern)
                aisle_cfg = planogram.planogram_config.get("aisle", {})
                if isinstance(aisle_cfg, dict):
                    allow_overlap = aisle_cfg.get("allow_overlap", False)

        used_ratio = 0.0
        for i, cfg in enumerate(shelf_configs):
            level = getattr(cfg, "level", f"shelf_{i}")

            # Determine start Y -- always honour explicit y_start_ratio
            start_ratio = getattr(cfg, "y_start_ratio", None)
            if start_ratio is not None:
                s_y1 = r_y1 + (roi_h * float(start_ratio))
            else:
                s_y1 = current_y

            if ratio := getattr(cfg, "height_ratio", None):
                s_h = roi_h * float(ratio)
                used_ratio += float(ratio)
            elif i == len(shelf_configs) - 1 and start_ratio is None:
                # Last shelf takes the rest (only if implicit stacking)
                s_h = max(0, (r_y2 - s_y1))
            else:
                s_h = roi_h * 0.25  # Default?

            base_y2 = min(r_y2, s_y1 + s_h)
            pad = roi_h * shelf_padding_ratio
            s_y2 = min(r_y2, base_y2 + pad) if pad > 0 else base_y2

            # Read is_background flag from config (handles both dict and object)
            if isinstance(cfg, dict):
                is_background = cfg.get("is_background", False)
            else:
                is_background = getattr(cfg, "is_background", False)

            shelves.append(ShelfRegion(
                shelf_id=f"virtual_{level}",
                level=level,
                bbox=DetectionBox(
                    x1=int(r_x1),
                    y1=int(s_y1),
                    x2=int(r_x2),
                    y2=int(s_y2),
                    confidence=1.0
                ),
                is_background=is_background
            ))

            # Always advance current_y so stacking fallback works for
            # shelves that lack an explicit y_start_ratio.
            current_y = base_y2
            if current_y >= r_y2:
                break

        return shelves

    def _cluster_fact_tag_rows(
        self,
        fact_tags: List[Any],
        cluster_threshold: int = 50,
    ) -> List[int]:
        """Group fact tags into horizontal rows by Y2 proximity.

        Returns a sorted list of Y values (one per row), representing the
        bottom edge of each price-tag row (i.e., the physical shelf board level).
        """
        if not fact_tags:
            return []
        y2_vals = sorted(
            p.detection_box.y2 for p in fact_tags if p.detection_box is not None
        )
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
        Products sit ABOVE their corresponding fact-tag row. The refined zones are:
            shelf[0]: header_end -> row[0]
            shelf[1]: row[0]     -> row[1]
            shelf[2]: row[1]     -> row[2]
            ...
        When fewer rows are detected than needed, computes a shift correction
        from the first detected row vs. its static boundary and extrapolates
        the missing boundaries.  Falls back to static only when zero rows found.
        """
        fact_tags = [
            p for p in identified_products
            if p.product_type == "fact_tag" and p.detection_box is not None
        ]
        row_ys = self._cluster_fact_tag_rows(fact_tags)

        bg_shelves = [s for s in shelf_regions if getattr(s, "is_background", False)]
        fg_shelves = [s for s in shelf_regions if not getattr(s, "is_background", False)]

        if not row_ys or not fg_shelves:
            self.logger.info(
                "use_fact_tag_boundaries: no fact-tag rows detected "
                "— keeping static boundaries"
            )
            return shelf_regions

        # N-1 rows are sufficient to divide N zones; the last zone extends
        # to the ROI bottom.  When we have fewer, extrapolate using a shift.
        if len(row_ys) < len(fg_shelves) - 1:
            # Compute shift: difference between detected first row and
            # the static boundary of the first foreground shelf.
            static_first_y2 = fg_shelves[0].bbox.y2
            shift = row_ys[0] - static_first_y2
            self.logger.info(
                f"use_fact_tag_boundaries: found {len(row_ys)} fact-tag rows "
                f"for {len(fg_shelves)} shelves — extrapolating with "
                f"shift={shift:+d}px (detected row={row_ys[0]}, "
                f"static boundary={static_first_y2})"
            )
            # Extrapolate missing boundaries from static + shift
            extrapolated = list(row_ys)
            for i in range(len(row_ys), len(fg_shelves) - 1):
                static_boundary = fg_shelves[i].bbox.y2
                extrapolated.append(int(static_boundary + shift))
            row_ys = extrapolated
        else:
            self.logger.info(
                f"use_fact_tag_boundaries: refining {len(fg_shelves)} shelves "
                f"from fact-tag rows at y={row_ys}"
            )

        # x-span comes from the existing shelf regions
        r_x1 = shelf_regions[0].bbox.x1
        r_x2 = shelf_regions[0].bbox.x2
        r_y2 = shelf_regions[-1].bbox.y2

        # Top of first foreground shelf = bottom of header (or first fg shelf y1)
        prev_y = fg_shelves[0].bbox.y1

        new_fg: List[ShelfRegion] = []
        for i, shelf in enumerate(fg_shelves):
            base_y = row_ys[i] if i < len(row_ys) else r_y2
            new_fg.append(ShelfRegion(
                shelf_id=shelf.shelf_id,
                level=shelf.level,
                bbox=DetectionBox(
                    x1=int(r_x1), y1=int(prev_y),
                    x2=int(r_x2), y2=int(base_y),
                    confidence=1.0
                ),
                is_background=shelf.is_background,
            ))
            prev_y = base_y

        return bg_shelves + new_fg

    async def _ocr_fact_tags(
        self,
        identified_products: List[Any],
        img: Any,
        planogram_description: Any,
        shelf_regions: Optional[List[Any]] = None,
    ) -> Dict[str, List[str]]:
        """Run OCR on the fact-tag row for every non-background shelf.

        Uses the full shelf width from shelf_regions to build each crop,
        guaranteeing coverage even when the LLM under-detects individual tags.
        If detected fact-tag bboxes exist for a shelf, their y-positions refine
        the crop vertically; otherwise a fixed strip at the shelf's bottom edge
        is used (fact tags always hang from the bottom of each shelf board).

        Args:
            identified_products: Full list of detected products/fact-tags.
            img: Full PIL image (bboxes are in absolute image coords).
            planogram_description: Used to build the known-models hint list.
            shelf_regions: ShelfRegion list after boundary refinement.

        Returns:
            A dict mapping shelf_level -> list of model-name strings found via OCR.
        """
        # Build a hint list of known models from the planogram config
        known_models: List[str] = []
        try:
            for shelf in (planogram_description.shelves or []):
                for sp in shelf.products:
                    m = getattr(sp, "name", "") or getattr(sp, "product_model", "") or ""
                    if m and m not in known_models:
                        known_models.append(m)
        except Exception:
            pass

        model_hint = ""
        if known_models:
            model_hint = (
                "\nKnown product models for this display: "
                + ", ".join(known_models)
                + ".\nMatch what you read to the closest known model when possible."
            )

        # Group any detected fact tags by shelf level (used for y-refinement)
        detected_by_shelf: Dict[str, List[Any]] = defaultdict(list)
        for p in identified_products:
            if (
                p.product_type == "fact_tag"
                and p.detection_box is not None
                and p.shelf_location
            ):
                detected_by_shelf[p.shelf_location].append(p)

        # Build a lookup of non-background shelf_regions by level
        shelf_reg_by_level: Dict[str, Any] = {}
        for sr in (shelf_regions or []):
            if not getattr(sr, "is_background", False):
                shelf_reg_by_level[sr.level] = sr

        # If no shelf_regions were supplied, fall back to only detected-tag levels
        if not shelf_reg_by_level:
            shelf_reg_by_level = {lvl: None for lvl in detected_by_shelf}

        shelf_map: Dict[str, List[str]] = defaultdict(list)
        img_w, img_h = img.size

        # Vertical strip height (px) around each shelf's bottom edge where tags hang
        STRIP_HEIGHT = 55

        # Compute endcap x-span from detected products/tags so we don't include
        # the store background shelves (which have their own price tags).
        # Only count items with a real bbox (area > 4px^2).
        _real_boxes = [
            p.detection_box for p in identified_products
            if p.detection_box is not None
            and (p.detection_box.x2 - p.detection_box.x1) > 2
            and (p.detection_box.y2 - p.detection_box.y1) > 2
        ]
        if _real_boxes:
            _enc_x1 = max(0, min(int(b.x1) for b in _real_boxes) - 30)
            _enc_x2 = min(img_w, max(int(b.x2) for b in _real_boxes) + 30)
        else:
            _enc_x1, _enc_x2 = 0, img_w
        self.logger.info(
            f"Fact-tag OCR endcap x-span: [{_enc_x1}, {_enc_x2}]"
        )

        for shelf_level, sr in shelf_reg_by_level.items():
            try:
                # -- X span: endcap width (avoids background store shelves) --
                shelf_y2 = img_h
                if sr is not None:
                    shelf_y2 = int(sr.bbox.y2)
                sx1, sx2 = _enc_x1, _enc_x2

                # -- Y span --
                tags = detected_by_shelf.get(shelf_level, [])
                if tags:
                    # Refine y using detected tag positions, extend x to full width
                    fy1 = min(int(t.detection_box.y1) for t in tags)
                    fy2 = max(int(t.detection_box.y2) for t in tags)
                    pad_y = max(5, int((fy2 - fy1) * 0.10))
                    ry1 = max(0, fy1 - pad_y)
                    ry2 = min(img_h, fy2 + pad_y)
                else:
                    # No detected tags -- use a fixed strip at the shelf's bottom edge
                    ry1 = max(0, shelf_y2 - STRIP_HEIGHT)
                    ry2 = min(img_h, shelf_y2 + 20)

                rx1 = max(0, sx1)
                rx2 = min(img_w, sx2)

                if rx1 >= rx2 or ry1 >= ry2:
                    continue

                self.logger.info(
                    f"Fact-tag row crop shelf='{shelf_level}': "
                    f"x=[{rx1},{rx2}] y=[{ry1},{ry2}] "
                    f"({len(tags)} tags detected by LLM)"
                )
                row_img = img.crop((rx1, ry1, rx2, ry2))
                prompt = (
                    f"This image shows the '{shelf_level}' shelf area of a retail "
                    "store display. It may contain BOTH physical product devices "
                    "(scanners, printers) AND small rectangular price/fact tags.\n\n"
                    "YOUR TASK: Read ONLY the model numbers from the small "
                    "price tags (fact tags). These are small rectangular label "
                    "cards (usually yellow or white, ~5cm wide) attached to the "
                    "shelf edge — typically at the VERY BOTTOM of the image.\n\n"
                    "CRITICAL: Do NOT read any text or model numbers printed "
                    "directly on the product device bodies (scanner housings, "
                    "printer casings). Those are device labels, NOT fact tags. "
                    "Fact tags are separate hanging cards, not part of the device.\n\n"
                    "IMPORTANT: If multiple rows of fact tags are visible at "
                    "different heights, read ONLY the row closest to the BOTTOM "
                    "of the image — those are this shelf's own fact tags. Any "
                    "fact tags in the upper portion of the image belong to the "
                    "shelf above and must be ignored.\n"
                    f"{model_hint}\n"
                    "Return ONLY model numbers found on fact tags, separated by "
                    "commas (e.g. 'ES-C220, RR-60, ES-400'). "
                    "If no fact tags are readable, return 'UNKNOWN'."
                )
                async with self.pipeline.roi_client as client:
                    msg = await client.ask_to_image(
                        image=row_img,
                        prompt=prompt,
                        model=GoogleModel.GEMINI_3_FLASH_PREVIEW,
                        no_memory=True,
                        max_tokens=128,
                    )
                raw = (msg.output or "").strip() if msg else ""
                self.logger.info(
                    f"Fact-tag row OCR shelf='{shelf_level}' -> '{raw}'"
                )
                # Store raw text on detected tags for traceability
                for t in tags:
                    t.ocr_text = raw

                if raw.upper() == "UNKNOWN" or not raw:
                    continue

                # Parse comma-separated model names
                for token in raw.split(","):
                    model_text = token.strip().strip("'\"").upper()
                    if model_text and model_text != "UNKNOWN":
                        shelf_map[shelf_level].append(model_text)

            except Exception as e:
                self.logger.warning(
                    f"Fact-tag row OCR failed for shelf='{shelf_level}': {e}"
                )

        return dict(shelf_map)

    def _corroborate_products_with_fact_tags(
        self,
        identified_products: List[Any],
        fact_tag_shelf_map: Dict[str, List[str]],
        planogram_description: Any,
    ) -> None:
        """Use fact-tag OCR results to supplement product detections.

        For each model name found by OCR on a given shelf, if no visually-detected
        product with a matching model already exists on that shelf, a synthetic
        IdentifiedProduct is injected so compliance scoring can credit the product.
        Products already correctly detected are simply logged as corroborated.

        Modifies ``identified_products`` in-place.
        """
        norm_patterns = getattr(planogram_description, "model_normalization_patterns", None)
        brand = (getattr(planogram_description, "brand", "") or "").lower()

        for shelf_level, ocr_models in fact_tag_shelf_map.items():
            # Collect normalized keys for products already on this shelf
            existing_norms: set = set()
            for p in identified_products:
                if (
                    p.shelf_location == shelf_level
                    and p.product_type not in (
                        "fact_tag", "price_tag", "slot",
                        "brand_logo", "gap", "shelf",
                    )
                ):
                    norm = self._base_model_from_str(
                        p.product_model or "", brand=brand, patterns=norm_patterns
                    )
                    if norm:
                        existing_norms.add(norm)

            # Build set of normalized model names expected on this shelf
            # AND on all other shelves, to prevent cross-shelf injection.
            expected_norms: set = set()
            all_other_shelf_norms: set = set()
            shelves_cfg = getattr(planogram_description, "shelves", []) or []
            for sh_cfg in shelves_cfg:
                sh_level = sh_cfg.get("level") if isinstance(sh_cfg, dict) else getattr(sh_cfg, "level", None)
                sh_products = sh_cfg.get("products", []) if isinstance(sh_cfg, dict) else getattr(sh_cfg, "products", [])
                for prod_cfg in (sh_products or []):
                    pname = prod_cfg.get("name", "") if isinstance(prod_cfg, dict) else getattr(prod_cfg, "name", "")
                    pnorm = self._base_model_from_str(
                        pname, brand=brand, patterns=norm_patterns
                    )
                    if pnorm:
                        if sh_level == shelf_level:
                            expected_norms.add(pnorm)
                        else:
                            all_other_shelf_norms.add(pnorm)

            for ocr_model in ocr_models:
                ocr_norm = self._base_model_from_str(
                    ocr_model, brand=brand, patterns=norm_patterns
                )
                if ocr_norm and ocr_norm in existing_norms:
                    self.logger.info(
                        f"Fact-tag corroboration \u2713 shelf='{shelf_level}' "
                        f"model='{ocr_model}' already detected"
                    )
                    continue

                # Skip models that are NOT expected on this shelf per config.
                # OCR sometimes misreads fact tags (e.g. reads scanner body
                # text instead of the actual fact-tag label).
                # Also skip if normalization failed entirely (ocr_norm is None),
                # meaning the OCR text doesn't match any known product pattern
                # (e.g. background store signs like 'REWARDS').
                if not ocr_norm:
                    self.logger.info(
                        f"Fact-tag corroboration \u2717 shelf='{shelf_level}' "
                        f"model='{ocr_model}' could not be normalized — skipping injection"
                    )
                    continue
                if expected_norms and ocr_norm not in expected_norms:
                    self.logger.info(
                        f"Fact-tag corroboration \u2717 shelf='{shelf_level}' "
                        f"model='{ocr_model}' (norm='{ocr_norm}') NOT expected "
                        f"on this shelf — skipping injection"
                    )
                    continue

                # Cross-shelf guard: if the model belongs to a DIFFERENT
                # shelf in the config, it was misread from a neighboring
                # fact-tag row -- skip it.
                if ocr_norm and ocr_norm in all_other_shelf_norms:
                    self.logger.info(
                        f"Fact-tag corroboration \u2717 shelf='{shelf_level}' "
                        f"model='{ocr_model}' (norm='{ocr_norm}') belongs to "
                        f"another shelf — skipping injection"
                    )
                    continue

                self.logger.info(
                    f"Fact-tag corroboration \u2192 injecting '{ocr_model}' "
                    f"on shelf='{shelf_level}' (not found in LLM detections)"
                )
                synthetic = IdentifiedProduct(
                    detection_box=DetectionBox(
                        x1=0, y1=0, x2=1, y2=1, confidence=0.85
                    ),
                    product_type="product",
                    product_model=ocr_model,
                    confidence=0.85,
                    shelf_location=shelf_level,
                    ocr_text=f"fact_tag_ocr:{ocr_model}",
                    visual_features=[f"fact_tag_confirmed:{ocr_model}"],
                )
                identified_products.append(synthetic)
                if ocr_norm:
                    existing_norms.add(ocr_norm)  # prevent duplicates within same run

    def _assign_products_to_shelves(
        self,
        products: List[IdentifiedProduct],
        shelves: List[ShelfRegion],
        use_y1_assignment: bool = False,
    ):
        """Assign each product to the spatially best-fitting shelf.

        Modifies 'shelf_location' in-place.
        Supports 'is_background' flag for layered shelf assignment.

        When use_y1_assignment=True (fact-tag boundary mode), the TOP of the
        product bbox (y1) is used to determine the shelf instead of the center
        overlap. Products rest ON the shelf board; their top edge sits inside
        the shelf zone above the fact-tag row, even when their body extends
        downward past it.
        """
        if not shelves:
            return

        # Sort just in case, though virtual generator creates them ordered
        shelves.sort(key=lambda s: s.bbox.y1)

        # Identify background shelves for promotional graphics
        background_shelves = [s for s in shelves if getattr(s, 'is_background', False)]

        _promo_types_assign = {
            "promotional_graphic", "graphic", "banner", "backlit_graphic", "backlit",
            "advertisement", "advertisement_graphic", "display_graphic",
            "promotional_display", "promotional_material", "promotional_materials"
        }
        _structural_types = {"gap", "shelf"}
        for p in products:
            if p.product_type in _structural_types:
                continue  # Skip structural LLM detections (gaps, shelf lines)
            if p.product_type in _promo_types_assign and p.shelf_location == "header":
                continue  # Already assigned to header, keep it

            # Check if this is a promotional/advertisement item that should go to background
            # Check various fields for promotional indicators
            model_lower = (p.product_model or "").lower()
            type_lower = (p.product_type or "").lower()
            brand_lower = (getattr(p, 'brand', '') or "").lower()

            # Items with explicit promotional names like "Logo Ad" should always go to background
            is_explicit_ad = ("logo" in model_lower and "ad" in model_lower) or "backlit" in model_lower

            # Regular products should NOT go to background (unless explicitly an ad)
            is_regular_product = p.product_type in ("product", "printer", "speaker", "pa_system") and not is_explicit_ad

            is_promotional = (
                is_explicit_ad or
                (not is_regular_product and (
                    p.product_type in ("promotional_graphic", "advertisement", "graphic", "logo", "banner", "backlit_graphic") or
                    "logo" in model_lower or
                    " ad" in model_lower or
                    "advertisement" in model_lower or
                    "graphic" in type_lower or
                    "banner" in type_lower or
                    "logo" in brand_lower
                ))
            )

            # For promotional items, prefer background shelves over foreground —
            # but only when the item's center actually falls inside that shelf's
            # Y range.  If the center lies below the background shelf (e.g. a
            # comparison table or base graphic detected as promotional_graphic),
            # fall through to the regular spatial assignment so it lands on the
            # correct foreground shelf.
            if is_promotional and background_shelves:
                bg = background_shelves[0]
                p_box_check = p.detection_box
                if p_box_check is not None:
                    p_cy_check = (p_box_check.y1 + p_box_check.y2) / 2
                    if bg.bbox.y1 <= p_cy_check <= bg.bbox.y2:
                        p.shelf_location = bg.level
                        continue
                    # else: fall through to spatial assignment below
                else:
                    p.shelf_location = bg.level
                    continue

            p_box = p.detection_box

            # For regular products, prefer foreground shelves (non-background)
            # Only fall back to background shelves if no foreground shelf matches
            foreground_shelves = [s for s in shelves if not getattr(s, 'is_background', False)]
            search_shelves = foreground_shelves if foreground_shelves else shelves

            # If no detection_box (LLM-identified products without bbox), fall back
            # to assigning by order: use shelf_location already set by LLM if valid,
            # otherwise assign to middle foreground shelf
            if p_box is None:
                valid_levels = {s.level for s in search_shelves}
                if p.shelf_location and p.shelf_location in valid_levels:
                    continue  # keep LLM-assigned shelf if it's a valid foreground shelf
                # Assign to the middle foreground shelf as best guess
                mid_idx = len(search_shelves) // 2
                p.shelf_location = search_shelves[mid_idx].level
                continue

            # Fact-tag boundary mode: use the TOP of the bbox (y1) to determine
            # shelf. Products sit ON the shelf board; their y1 starts inside the
            # zone above the fact-tag row even when the body hangs below it.
            # Falls back to overlap logic if y1 doesn't land in any zone.
            if use_y1_assignment:
                # Use vertical CENTER of the bounding box for shelf
                # assignment.  Tall products (e.g. ES-400 with paper
                # tray) have y1 that extends above their actual shelf
                # boundary, but the center always lands firmly inside
                # the correct zone.
                p_cy_assign = (p_box.y1 + p_box.y2) / 2
                cy_shelf = None
                # Iterate bottom->top so products near overlapping shelf
                # boundaries (caused by inter_shelf_padding) prefer the
                # lower shelf.
                for s in reversed(search_shelves):
                    if s.bbox.y1 <= p_cy_assign < s.bbox.y2:
                        cy_shelf = s
                        break
                if not cy_shelf:
                    # Center fell between zones (e.g. narrow middle shelf with
                    # extrapolated boundaries). Try the TOP of the bbox (y1) as
                    # a secondary hint -- products physically sit above their
                    # fact-tag row so y1 may land in the correct zone even when
                    # the center falls just below it.
                    for s in reversed(search_shelves):
                        if s.bbox.y1 <= p_box.y1 < s.bbox.y2:
                            cy_shelf = s
                            break
                if cy_shelf:
                    p.shelf_location = cy_shelf.level
                    continue
                # Both center and y1 fell outside all zones -- fall through
                # to the standard overlap logic below

            p_cy = (p_box.y1 + p_box.y2) / 2

            best_shelf = None
            max_iou = 0.0
            min_dist = float('inf')

            # Use Vertical Intersection -- pick the shelf with MAXIMUM overlap
            for s in search_shelves:
                s_box = s.bbox
                sy1, sy2 = s_box.y1, s_box.y2
                py1, py2 = p_box.y1, p_box.y2

                inter_y1 = max(sy1, py1)
                inter_y2 = min(sy2, py2)

                if inter_y2 > inter_y1:
                    iy = inter_y2 - inter_y1
                    ph = py2 - py1
                    overlap = iy / ph if ph > 0 else 0
                    if overlap > max_iou:
                        max_iou = overlap
                        best_shelf = s

            if not best_shelf:
                # Vertical center distance fallback - still prefer foreground
                for s in search_shelves:
                    s_box = s.bbox
                    s_cy = (s_box.y1 + s_box.y2) / 2
                    dist = abs(p_cy - s_cy)
                    if dist < min_dist:
                        min_dist = dist
                        best_shelf = s

            # If still no match in foreground, fall back to any shelf
            if not best_shelf and foreground_shelves:
                for s in shelves:
                    s_box = s.bbox
                    s_cy = (s_box.y1 + s_box.y2) / 2
                    dist = abs(p_cy - s_cy)
                    if dist < min_dist:
                        min_dist = dist
                        best_shelf = s

            if best_shelf:
                p.shelf_location = best_shelf.level
