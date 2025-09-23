"""
3-Step Planogram Compliance Pipeline
Step 1: Object Detection (YOLO/ResNet)
Step 2: LLM Object Identification with Reference Images
Step 3: Planogram Comparison and Compliance Verification
"""
import asyncio
import os
from typing import List, Dict, Any, Optional, Union, Tuple
from collections import defaultdict, Counter
from datetime import datetime
import unicodedata
import re
import traceback
from pathlib import Path
import math
import pytesseract
from PIL import (
    Image,
    ImageDraw,
    ImageFont,
    ImageEnhance,
    ImageOps
)
import numpy as np
from pydantic import BaseModel, Field
import cv2
import torch
from google.genai.errors import ServerError
from .abstract import AbstractPipeline
from ..models.detections import (
    DetectionBox,
    Detection,
    Detections,
    ShelfRegion,
    IdentifiedProduct,
    PlanogramDescription
)
from ..models.compliance import (
    ComplianceResult,
    ComplianceStatus,
    TextComplianceResult,
    TextMatcher,
    BrandComplianceResult
)
from .detector import AbstractDetector
from .models import PlanogramConfig


CID = {
    "promotional_candidate": 103,
    "product_candidate": 100,
    "box_candidate": 101,
    "price_tag": 102,
    "shelf_region": 190,
    "brand_logo": 105,
    "poster_text": 106,
}

class RetailDetector(AbstractDetector):
    """
    Reference-guided Phase-1 detector.

    1) Enhance image (contrast/brightness) to help OCR/YOLO/CLIP.
    2) Localize the promotional poster using:
       - OCR ('EPSON', 'Hello', 'Savings', etc.)
       - CLIP similarity with your FIRST reference image.
    3) Crop to poster width (+ margin) to form an endcap ROI (remember offsets).
    4) Detect shelf lines within ROI (Hough) => top/middle/bottom bands.
    5) YOLO proposals inside ROI (low conf, class-agnostic).
    6) For each proposal: OCR + CLIP vs remaining reference images
       => label as promotional/product/box candidate.
    7) Shrink, merge, suppress items that are inside the poster.
    """

    def __init__(
        self,
        yolo_model: str = "yolo12l.pt",
        conf: float = 0.15,
        iou: float = 0.5,
        device: str = "cuda" if torch.cuda.is_available() else "cpu",
        reference_images: Optional[List[str]] = None,  # first is the poster
        **kwargs
    ):
        super().__init__(
            yolo_model=yolo_model,
            conf=conf,
            iou=iou,
            device=device,
            **kwargs
        )
        # Shelf split defaults: header/middle/bottom
        self.shelf_split = (0.40, 0.25, 0.35)  # sums to ~1.0
        # Useful elsewhere (price tag guardrails, etc.)
        self.label_strip_ratio = 0.06
        self.ref_paths = reference_images or []
        self.ref_ad = self.ref_paths[0] if self.ref_paths else None
        self.ref_products = self.ref_paths[1:] if len(self.ref_paths) > 1 else []
        self.ref_ad_feat = self._embed_image(self.ref_ad) if self.ref_ad else None
        self.ref_prod_feats = [
            self._embed_image(p) for p in self.ref_products
        ] if self.ref_products else []

    # -------------------------- Main Detection Entry ---------------------------------
    async def detect(
        self,
        image: Image.Image,
        image_array: np.array,
        endcap: Detection,
        ad: Detection,
        planogram: Optional[PlanogramDescription] = None,
        debug_yolo: Optional[str] = None,
        debug_phase1: Optional[str] = None,
        debug_phases: Optional[str] = None,
    ):
        h, w = image_array.shape[:2]
        # text prompts (backup if no product refs)
        text = [f"a photo of a {t}" for t in planogram.text_tokens if t]
        if not text:
            text = [
                "a photo of a retail promotional poster lightbox",
                "a photo of a product box",
                "a photo of a product cartridge bottle",
                "a photo of a price tag"
            ]
        self.text_tokens = self.proc(
            text=text,
            return_tensors="pt",
            padding=True
        ).to(self.device)
        with torch.no_grad():
            self.text_feats = self.clip.get_text_features(**self.text_tokens)
            self.text_feats = self.text_feats / self.text_feats.norm(dim=-1, keepdim=True)

        # Check if detections are valid before proceeding
        if not endcap or not ad:
            print("ERROR: Failed to get required detections.")
            return # or raise an exception

        # 2) endcap ROI
        roi_box = endcap.bbox.get_pixel_coordinates(width=w, height=h)
        ad_box = ad.bbox.get_pixel_coordinates(width=w, height=h)

        # Unpack the Pixel coordinates
        rx1, ry1, rx2, ry2 = roi_box

        roi = image_array[ry1:ry2, rx1:rx2]

        # 4) YOLO inside ROI
        yolo_props = self._yolo_props(roi, rx1, ry1)

        # Extract planogram config for shelf layout
        planogram_config = None
        if planogram:
            planogram_config = {
                'shelves': [
                    {
                        'level': shelf.level,
                        'height_ratio': getattr(shelf, 'height_ratio', None),
                        'products': [
                            {
                                'name': product.name,
                                'product_type': product.product_type
                            } for product in shelf.products
                        ]
                    } for shelf in planogram.shelves
                ]
            }

        # 3) shelves
        shelf_lines, bands = self._find_shelves(
            roi_box=roi_box,
            ad_box=ad_box,
            w=w,
            h=h,
            planogram_config=planogram_config
        )
        # header_limit_y = min(v[0] for v in bands.values()) if bands else int(0.4 * h)
        # classification fallback limit = header bottom (or 40% of ROI height)
        if bands and "header" in bands:
            header_limit_y = bands["header"][1]
        else:
            roi_h = max(1, ry2 - ry1)
            header_limit_y = ry1 + int(0.4 * roi_h)

        if debug_yolo:
            dbg = self._draw_phase_areas(image_array.copy(), yolo_props, roi_box)
            if debug_phases:
                cv2.imwrite(
                    debug_phases,
                    cv2.cvtColor(dbg, cv2.COLOR_RGB2BGR)
                )
            dbg = self._draw_yolo(image_array.copy(), yolo_props, roi_box, shelf_lines)
            cv2.imwrite(
                debug_yolo,
                cv2.cvtColor(dbg, cv2.COLOR_RGB2BGR)
            )

        # 5) classify YOLO → proposals (works w/ bands={}, header_limit_y above)
        proposals = await self._classify_proposals(
            image_array,
            yolo_props,
            bands,
            header_limit_y,
            ad_box
        )
        # 6) shrink -> merge -> remove those fully inside the poster
        proposals = self._merge(proposals, iou_same=0.45)

        # shelves dict to satisfy callers; in flat mode keep it empty
        shelves = {
            name: DetectionBox(
                x1=rx1, y1=y1, x2=rx2, y2=y2,
                confidence=1.0,
                class_id=190, class_name="shelf_region",
                area=(rx2-rx1)*(y2-y1),
            )
            for name, (y1, y2) in bands.items()
        }

        # (OPTIONAL) draw Phase-1 debug
        if debug_phase1:
            dbg = self._draw_phase1(
                image_array.copy(),
                roi_box,
                shelf_lines,
                proposals,
                ad_box
            )
            cv2.imwrite(
                debug_phase1,
                cv2.cvtColor(dbg, cv2.COLOR_RGB2BGR)
            )

        # 8) ensure the promo exists exactly once
        if ad_box is not None and not any(d.class_name == "promotional_candidate" and self._iou_box_tuple(d, ad_box) > 0.7 for d in proposals):
            x1, y1, x2, y2 = ad_box
            proposals.append(
                DetectionBox(
                    x1=x1, y1=y1, x2=x2, y2=y2,
                    confidence=0.95,
                    class_id=103,
                    class_name="promotional_candidate",
                    area=(x2-x1)*(y2-y1)
                )
            )

        return {"shelves": shelves, "proposals": proposals}

    # --------------------------- shelves -------------------------------------
    def _find_shelves(
        self,
        roi_box: tuple[int, int, int, int],
        ad_box: tuple[int, int, int, int],
        h: int,
        w: int,
        planogram_config: dict = None
    ) -> tuple[List[int], dict]:
        """
        Detects shelf bands based on planogram configuration, prioritizing the
        dynamically detected ad_box for the header.
        """
        rx1, ry1, rx2, ry2 = map(int, roi_box)
        _, ad_y1, _, ad_y2 = map(int, ad_box)
        roi_h = max(1, ry2 - ry1)

        # Fallback to the old proportional method if no planogram is provided
        if not planogram_config or 'shelves' not in planogram_config:
            return self._find_shelves_proportional(roi_box, rx1, ry1, rx2, ry2, h)

        shelf_configs = planogram_config['shelves']
        if not shelf_configs:
            return [], {}

        bands = {}
        levels = []

        # --- 1. Prioritize the Header based on ad_box ---
        # The header starts at the top of the ROI and ends at the bottom of the ad_box
        header_config = next((s for s in shelf_configs if s.get('level') == 'header'), None)
        if header_config:
            # Use the detected ad_box y-coordinates for the header band
            header_top = ad_y1
            header_bottom = ad_y2
            bands[header_config['level']] = (header_top, header_bottom)
            current_y = header_bottom
            remaining_configs = [s for s in shelf_configs if s.get('level') != 'header']
        else:
            # If no header is defined, start from the top of the ROI
            current_y = ry1
            remaining_configs = shelf_configs

        # --- 2. Calculate space for remaining shelves ---
        remaining_roi_h = max(1, ry2 - current_y)

        # Calculate space consumed by shelves with a fixed height_ratio
        height_from_ratios = 0
        shelves_without_ratio = []
        for shelf_config in remaining_configs:
            if 'height_ratio' in shelf_config and shelf_config['height_ratio'] is not None:
                # height_ratio is a percentage of the TOTAL ROI height
                height_from_ratios += int(shelf_config['height_ratio'] * roi_h)
            else:
                shelves_without_ratio.append(shelf_config)

        # Calculate height for each shelf without a specified ratio
        auto_size_h = max(0, remaining_roi_h - height_from_ratios)
        auto_shelf_height = int(auto_size_h / len(shelves_without_ratio)) if shelves_without_ratio else 0

        # --- 3. Build the bands for the remaining shelves ---
        for i, shelf_config in enumerate(remaining_configs):
            shelf_level = shelf_config['level']

            if 'height_ratio' in shelf_config and shelf_config['height_ratio'] is not None:
                shelf_pixel_height = int(shelf_config['height_ratio'] * roi_h)
            else:
                shelf_pixel_height = auto_shelf_height

            shelf_bottom = current_y + shelf_pixel_height

            # For the very last shelf, ensure it extends to the bottom of the ROI
            if i == len(remaining_configs) - 1:
                shelf_bottom = ry2

            # VALIDATION: Ensure valid bounding box
            if shelf_bottom <= current_y:
                print(
                    f"WARNING: Invalid shelf {shelf_level}: y1={current_y}, y2={shelf_bottom}"
                )
                shelf_bottom = current_y + 50  # Minimum height

            bands[shelf_level] = (current_y, shelf_bottom)
            current_y = shelf_bottom

        # --- 4. Create the levels list (separator lines) ---
        # The levels are the bottom coordinate of each shelf band, except for the last one
        if bands:
            # Ensure order from top to bottom based on the planogram config
            ordered_levels = [bands[s['level']][1] for s in shelf_configs if s['level'] in bands]
            levels = ordered_levels[:-1]

        self.logger.debug(
            f"📊 Planogram Shelves: {len(shelf_configs)} shelves configured, "
            f"ROI height={roi_h}, bands={bands}"
        )

        return levels, bands

    def _find_shelves_proportional(self, roi: tuple, rx1, ry1, rx2, ry2, H, planogram_config: dict = None):
        """
        Fallback proportional layout using planogram config or default 3-shelf layout.
        """
        roi_h = max(1, ry2 - ry1)

        # Use planogram config if available
        if planogram_config and 'shelves' in planogram_config:
            shelf_configs = planogram_config['shelves']
            num_shelves = len(shelf_configs)

            if num_shelves > 0:
                # Equal division among configured shelves
                shelf_height = roi_h // num_shelves

                levels = []
                bands = {}
                current_y = ry1

                for i, shelf_config in enumerate(shelf_configs):
                    shelf_level = shelf_config['level']
                    shelf_bottom = current_y + shelf_height

                    # For the last shelf, extend to ROI bottom
                    if i == len(shelf_configs) - 1:
                        shelf_bottom = ry2

                    bands[shelf_level] = (current_y, shelf_bottom)
                    if i < len(shelf_configs) - 1:  # Don't add last boundary to levels
                        levels.append(shelf_bottom)

                    current_y = shelf_bottom

                return levels, bands

        # Default fallback: 3-shelf layout if no config
        hdr_r, mid_r, bot_r = 0.40, 0.30, 0.30

        header_bottom = ry1 + int(hdr_r * roi_h)
        middle_bottom = header_bottom + int(mid_r * roi_h)

        # Ensure boundaries don't exceed ROI
        header_bottom = max(ry1 + 20, min(header_bottom, ry2 - 40))
        middle_bottom = max(header_bottom + 20, min(middle_bottom, ry2 - 20))

        levels = [header_bottom, middle_bottom]
        bands = {
            "header": (ry1, header_bottom),
            "middle": (header_bottom, middle_bottom),
            "bottom": (middle_bottom, ry2),
        }

        return levels, bands

    # ---------------------------- YOLO ---------------------------------------
    def _preprocess_roi_for_detection(self, roi: np.ndarray) -> np.ndarray:
        """
        Ultra-minimal preprocessing - only applies when absolutely necessary.
        Use this version if you want maximum preservation of original image quality.
        """
        try:
            # Convert BGR to RGB if needed
            if len(roi.shape) == 3 and roi.shape[2] == 3:
                rgb_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2RGB)
            else:
                rgb_roi = roi.copy()

            # Quick contrast check
            gray = cv2.cvtColor(rgb_roi, cv2.COLOR_RGB2GRAY)
            contrast = gray.std()

            # Only process if contrast is very low
            if contrast > 35:
                # Good contrast - return original with minimal sharpening
                result = rgb_roi.astype(np.float32)

                # Ultra-subtle sharpening
                kernel = np.array([[0, -0.05, 0],
                                [-0.05, 1.2, -0.05],
                                [0, -0.05, 0]])

                for i in range(3):
                    result[:,:,i] = cv2.filter2D(result[:,:,i], -1, kernel)

                result = np.clip(result, 0, 255).astype(np.uint8)
            else:
                # Low contrast - apply gentle CLAHE only
                lab = cv2.cvtColor(rgb_roi, cv2.COLOR_RGB2LAB)
                clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(10,10))
                lab[:,:,0] = clahe.apply(lab[:,:,0])
                result = cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)

            # Convert back to BGR if needed
            if len(roi.shape) == 3 and roi.shape[2] == 3:
                result = cv2.cvtColor(result, cv2.COLOR_RGB2BGR)

            return result

        except Exception as e:
            self.logger.warning(f"Minimal ROI preprocessing failed: {e}")
            return roi

    def _yolo_props(self, roi: np.ndarray, rx1, ry1, detection_phases: Optional[List[Dict[str, Any]]] = None):
        """
        Multi-phase YOLO detection with configurable confidence levels and weighted scoring.
        Returns proposals in the same format expected by existing _classify_proposals method.

        Args:
            roi: ROI image array
            rx1, ry1: ROI offset coordinates
            detection_phases: List of phase configurations. If None, uses default 2-phase approach.
        """
        #   printer ≈ 5–9%, product_box ≈ 7–12%, promotional_graphic ≥ 20%
        CLASS_LIMITS = {
            # Base retail categories
            "poster":       {"min_area": 0.06, "max_area": 0.95, "min_ar": 0.5, "max_ar": 3.5},
            "person":       {"min_area": 0.02, "max_area": 0.60, "min_ar": 0.3, "max_ar": 3.5},
            "printer":      {"min_area": 0.010, "max_area": 0.28, "min_ar": 0.6, "max_ar": 2.8},
            "product_box":  {"min_area": 0.003, "max_area": 0.20, "min_ar": 0.4, "max_ar": 3.2},
            "price_tag":    {"min_area": 0.0006,"max_area": 0.010,"min_ar": 1.6, "max_ar": 8.0},

            # YOLO classes mapped to retail categories with their own limits
            "tv":           {"min_area": 0.06, "max_area": 0.95, "min_ar": 0.5, "max_ar": 3.5},  # → poster
            "monitor":      {"min_area": 0.06, "max_area": 0.95, "min_ar": 0.5, "max_ar": 3.5},  # → poster
            "laptop":       {"min_area": 0.06, "max_area": 0.95, "min_ar": 0.5, "max_ar": 3.5},  # → poster
            "microwave":    {"min_area": 0.010, "max_area": 0.28, "min_ar": 0.6, "max_ar": 2.8}, # → printer
            "book":         {"min_area": 0.003, "max_area": 0.20, "min_ar": 0.4, "max_ar": 3.2}, # → product_box
            "box":          {"min_area": 0.003, "max_area": 0.20, "min_ar": 0.4, "max_ar": 3.2}, # → product_box
            "suitcase":     {"min_area": 0.003, "max_area": 0.20, "min_ar": 0.4, "max_ar": 3.2}, # → product_box
            "bottle":       {"min_area": 0.0006,"max_area": 0.010,"min_ar": 1.6, "max_ar": 8.0}, # → price_tag
            "clock":        {"min_area": 0.0006,"max_area": 0.010,"min_ar": 1.6, "max_ar": 8.0}, # → price_tag
            "mouse":        {"min_area": 0.0006,"max_area": 0.010,"min_ar": 1.6, "max_ar": 8.0}, # → price_tag
            "remote":       {"min_area": 0.0006,"max_area": 0.010,"min_ar": 1.6, "max_ar": 8.0}, # → price_tag
            "cell phone":   {"min_area": 0.0006,"max_area": 0.010,"min_ar": 1.6, "max_ar": 8.0}, # → price_tag
        }

        # Mapping from YOLO classes to retail categories
        YOLO_TO_RETAIL = {
            "tv": "poster",
            "monitor": "poster",
            "laptop": "poster",
            "microwave": "printer",
            "keyboard": "product_box",
            "book": "product_box",
            "box": "product_box",
            "suitcase": "product_box",
            "bottle": "price_tag",
            "clock": "price_tag",
            "mouse": "price_tag",
            "remote": "price_tag",
            "cell phone": "price_tag",
        }

        def _get_class_limits(yolo_class: str) -> Optional[Dict[str, float]]:
            """Get class limits for a YOLO class"""
            return CLASS_LIMITS.get(yolo_class, None)

        def _get_retail_category(yolo_class: str) -> str:
            """Map YOLO class to retail category"""
            return YOLO_TO_RETAIL.get(yolo_class, yolo_class)

        def _passes_class_limits(yolo_class: str, area_ratio: float, aspect_ratio: float) -> tuple[bool, str]:
            """Check if detection passes class-specific limits"""
            limits = _get_class_limits(yolo_class)
            if not limits:
                # Use generic fallback limits if no class-specific ones
                generic_ok = (0.0008 <= area_ratio <= 0.9 and 0.1 <= aspect_ratio <= 10.0)
                return generic_ok, "generic_limits"

            area_ok = limits["min_area"] <= area_ratio <= limits["max_area"]
            ar_ok = limits["min_ar"] <= aspect_ratio <= limits["max_ar"]

            if area_ok and ar_ok:
                retail_category = _get_retail_category(yolo_class)
                return True, f"class_limits_{yolo_class}→{retail_category}"
            else:
                # Provide specific failure reason for debugging
                reasons = []
                if not area_ok:
                    reasons.append(
                        f"area={area_ratio:.4f} not in [{limits['min_area']:.4f}, {limits['max_area']:.4f}]"
                    )
                if not ar_ok:
                    reasons.append(
                        f"ar={aspect_ratio:.2f} not in [{limits['min_ar']:.2f}, {limits['max_ar']:.2f}]"
                    )
                return False, f"failed_{yolo_class}: {'; '.join(reasons)}"

        # Preprocess ROI to enhance detection of similar-colored objects
        enhanced_roi = self._preprocess_roi_for_detection(roi)

        if detection_phases is None:
            detection_phases = [
                {  # Coarse: quickly find large boxes (e.g., header, promo)
                    "name": "coarse",
                    "conf": 0.35,
                    "iou": 0.35,
                    "weight": 0.20,
                    "min_area": 0.05,  # >= 5% of ROI
                    "description": "High confidence pass for large objects",
                },
                # Standard: main workhorse for printers & boxes
                {
                    "name": "standard",
                    "conf": 0.05,
                    "iou": 0.20,
                    "weight": 0.70,
                    "min_area": 0.001,
                    "description": "High confidence pass for clear objects"
                },
                # Aggressive: recover misses but still bounded by class limits
                {
                    "name": "aggressive",
                    "conf": 0.008,
                    "iou": 0.15,
                    "weight": 0.10,
                    "min_area": 0.0006,
                    "description": "Selective aggressive pass for missed objects only"
                },
            ]

        try:
            H, W = roi.shape[:2]
            roi_area = H * W
            all_proposals = []

            print(f"\n🔄 Detection with Your Preferred Settings on ROI {W}x{H}")
            print("   " + "="*70)

            # Statistics tracking
            stats = {
                "total_detections": 0,
                "passed_confidence": 0,
                "passed_size": 0,
                "passed_class_limits": 0,
                "rejected_class_limits": 0
            }

            # Run both phases with your settings
            for phase_idx, phase in enumerate(detection_phases):
                phase_name = phase["name"]
                conf_thresh = phase["conf"]
                iou_thresh = phase["iou"]
                weight = phase["weight"]

                print(
                    f"\n📡 Phase {phase_idx + 1}: {phase_name}"
                )
                print(
                    f"   Config: conf={conf_thresh}, iou={iou_thresh}, weight={weight}"
                )

                r = self.yolo(enhanced_roi, conf=conf_thresh, iou=iou_thresh, verbose=False)[0]

                if not hasattr(r, 'boxes') or r.boxes is None:
                    print(f"   📊 No boxes detected in {phase_name}")
                    continue

                xyxy = r.boxes.xyxy.cpu().numpy()
                confs = r.boxes.conf.cpu().numpy()
                classes = r.boxes.cls.cpu().numpy().astype(int)
                names = r.names

                print(
                    f"   📊 Raw YOLO output: {len(xyxy)} detections"
                )

                phase_count = 0
                phase_rejected = 0

                for _, ((x1, y1, x2, y2), conf, cls_id) in enumerate(zip(xyxy, confs, classes)):
                    gx1, gy1, gx2, gy2 = int(x1) + rx1, int(y1) + ry1, int(x2) + rx1, int(y2) + ry1

                    width, height = x2 - x1, y2 - y1
                    if width <= 0 or height <= 0 or width < 8 or height < 8:
                        continue

                    if conf < conf_thresh:
                        continue

                    stats["passed_confidence"] += 1

                    area = width * height
                    area_ratio = area / roi_area
                    aspect_ratio = width / max(height, 1)
                    yolo_class = names[cls_id]

                    min_area = phase.get("min_area")
                    if min_area and area_ratio < float(min_area):
                        continue

                    stats["passed_size"] += 1

                    # Apply class-specific limits
                    limits_passed, limit_reason = _passes_class_limits(yolo_class, area_ratio, aspect_ratio)

                    if not limits_passed:
                        phase_rejected += 1
                        stats["rejected_class_limits"] += 1
                        if phase_rejected <= 3:  # Log first few rejections for debugging
                            print(f"   ❌ Rejected {yolo_class}: {limit_reason}")
                        continue

                    ocr_text = None
                    orientation = self._detect_orientation(gx1, gy1, gx2, gy2)
                    if (area_ratio >= 0.0008 and area_ratio <= 0.9):
                        # Only run OCR on boxes with an area > 5% of the ROI
                        if area_ratio > 0.05:
                            try:
                                # Crop the specific proposal from the ROI image
                                # Use local coordinates (x1, y1, x2, y2) for this
                                proposal_img_crop = roi[int(y1):int(y2), int(x1):int(x2)]

                                # --- ROTATION LOGIC for VERTICAL BOXES ---
                                if orientation == 'vertical':
                                    # Rotate the crop 90 degrees counter-clockwise to make text horizontal
                                    proposal_img_crop = cv2.rotate(
                                        proposal_img_crop,
                                        cv2.ROTATE_90_CLOCKWISE
                                    )
                                    text = pytesseract.image_to_string(
                                        proposal_img_crop,
                                        # config='--psm 6'
                                        config="--psm 6 -l eng"
                                    )
                                    proposal_img_crop = cv2.rotate(
                                        proposal_img_crop,
                                        cv2.ROTATE_90_COUNTERCLOCKWISE
                                    )
                                    vtext = pytesseract.image_to_string(
                                        proposal_img_crop,
                                        # config='--psm 6'
                                        config="--psm 6 -l eng"
                                    )
                                    raw_text = text + ' | ' + vtext
                                else:
                                    # Run Tesseract on the crop
                                    raw_text = pytesseract.image_to_string(
                                        proposal_img_crop,
                                        # config='--psm 6'
                                        config="--psm 6 -l eng"
                                    )

                                # Clean up the text
                                ocr_text = " ".join(raw_text.strip().split())
                            except Exception as ocr_error:
                                self.logger.warning(
                                    f"OCR failed for a proposal: {ocr_error}"
                                )

                    orientation = self._detect_orientation(gx1, gy1, gx2, gy2)
                    weighted_conf = float(conf) * weight
                    proposal = {
                        "yolo_label": yolo_class,
                        "yolo_conf": float(conf),
                        "weighted_conf": weighted_conf,
                        "box": (gx1, gy1, gx2, gy2),
                        "area_ratio": area_ratio,
                        "aspect_ratio": aspect_ratio,
                        "orientation": orientation,
                        "retail_candidates": self._get_retail_candidates(yolo_class),
                        "raw_index": len(all_proposals) + 1,
                        "ocr_text": ocr_text,
                        "phase": phase_name
                    }
                    # print('PROPOSAL > ', proposal)
                    all_proposals.append(proposal)
                    stats["total_detections"] += 1
                    phase_count += 1

                print(f"   ✅ Kept {phase_count} detections from {phase_name}")

            # Light deduplication (let classification handle quality control)
            deduplicated = self._object_deduplication(all_proposals)

            print(f"\n📊 Detection Summary: {len(deduplicated)} total proposals")
            print("   Focus: Let classification phase handle object type distinction")

            # Print final statistics
            print(f"\n📊 Detection Summary:")
            print(f"   Total YOLO detections: {stats['total_detections']}")
            print(f"   Passed confidence: {stats['passed_confidence']}")
            print(f"   Passed basic size: {stats['passed_size']}")
            print(f"   Passed class limits: {stats['passed_class_limits']}")
            print(f"   Rejected by class limits: {stats['rejected_class_limits']}")
            print(f"   Final after deduplication: {len(deduplicated)}")
            return deduplicated

        except Exception as e:
            print(f"Detection failed: {e}")
            traceback.print_exc()
            return []

    def _determine_shelf_level(self, center_y: float, bands: Dict[str, tuple]) -> str:
        """Enhanced shelf level determination"""
        if not bands:
            return "unknown"

        for level, (y1, y2) in bands.items():
            if y1 <= center_y <= y2:
                return level

        # If not in any band, find closest
        min_distance = float('inf')
        closest_level = "unknown"
        for level, (y1, y2) in bands.items():
            band_center = (y1 + y2) / 2
            distance = abs(center_y - band_center)
            if distance < min_distance:
                min_distance = distance
                closest_level = level

        return closest_level

    def _detect_orientation(self, x1: int, y1: int, x2: int, y2: int) -> str:
        """Detect orientation from bounding box dimensions"""
        width = x2 - x1
        height = y2 - y1
        aspect_ratio = width / max(height, 1)

        if aspect_ratio < 0.8:
            return "vertical"
        elif aspect_ratio > 1.5:
            return "horizontal"
        else:
            return "square"

    def _get_retail_candidates(self, yolo_class: str) -> List[str]:
        """Light retail candidate mapping - let classification do the heavy work"""
        mapping = {
            "microwave": ["printer", "product_box"],
            "tv": ["promotional_graphic", "tv"],
            "television": ["tv"],
            "monitor": ["promotional_graphic"],
            "laptop": ["promotional_graphic"],
            "book": ["product_box"],
            "box": ["product_box"],
            "suitcase": ["product_box", "printer"],
            "bottle": ["ink_bottle", "price_tag"],
            "person": ["promotional_graphic"],
            "clock": ["small_object", "price_tag"],
            "cell phone": ["small_object", "price_tag"],
        }
        return mapping.get(yolo_class, ["product_candidate"])

    def _object_deduplication(self, all_detections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Enhanced deduplication with container/contained logic and better IoU thresholds
        """
        if not all_detections:
            return []

        # Sort by weighted confidence (highest first)
        sorted_detections = sorted(all_detections, key=lambda x: x["weighted_conf"], reverse=True)

        deduplicated = []
        for detection in sorted_detections:
            detection_box = detection["box"]
            x1, y1, x2, y2 = detection_box
            detection_area = (x2 - x1) * (y2 - y1)

            is_duplicate = False
            is_contained = False

            for kept in deduplicated[:]:
                kept_box = kept["box"]
                kx1, ky1, kx2, ky2 = kept_box
                kept_area = (kx2 - kx1) * (ky2 - ky1)

                iou = self._calculate_iou_tuples(detection_box, kept_box)

                # Standard IoU-based deduplication (lowered threshold)
                if iou > 0.5:  # Reduced from 0.7 to 0.5
                    is_duplicate = True
                    break

                # (e.g., individual box vs. entire shelf detection)
                if kept_area > detection_area * 3:  # Kept is 3x larger
                    # Check if detection is substantially contained within kept
                    overlap_area = max(0, min(x2, kx2) - max(x1, kx1)) * max(0, min(y2, ky2) - max(y1, ky1))
                    contained_ratio = overlap_area / detection_area
                    if contained_ratio > 0.8:  # 80% of detection is inside kept
                        is_contained = True
                        break

                # Check if kept detection is contained within current (much larger) detection
                elif detection_area > kept_area * 3:  # Current is 3x larger
                    overlap_area = max(0, min(x2, kx2) - max(x1, kx1)) * max(0, min(y2, ky2) - max(y1, ky1))
                    contained_ratio = overlap_area / kept_area
                    if contained_ratio > 0.8:  # 80% of kept is inside current
                        # Remove the contained detection and replace with current
                        deduplicated.remove(kept)

            if not is_duplicate and not is_contained:
                deduplicated.append(detection)

        print(
            f"   🔄 Deduplication: {len(sorted_detections)} → {len(deduplicated)} detections"
        )
        return deduplicated

    # Additional helper method for phase configuration
    def set_detection_phases(self, phases: List[Dict[str, Any]]):
        """
        Set custom detection phases for the RetailDetector

        Args:
            phases: List of phase configurations, each containing:
                - name: Phase identifier
                - conf: Confidence threshold
                - iou: IoU threshold
                - weight: Weight for this phase (should sum to 1.0 across all phases)
                - description: Optional description

        Example:
            detector.set_detection_phases([
                {
                    "name": "ultra_high_conf",
                    "conf": 0.5,
                    "iou": 0.6,
                    "weight": 0.5,
                    "description": "Ultra high confidence for definite objects"
                },
                {
                    "name": "medium_conf",
                    "conf": 0.15,
                    "iou": 0.4,
                    "weight": 0.3,
                    "description": "Medium confidence for likely objects"
                },
                {
                    "name": "aggressive",
                    "conf": 0.005,
                    "iou": 0.15,
                    "weight": 0.2,
                    "description": "Aggressive pass for missed objects"
                }
            ])
        """
        # Validate phase configuration
        total_weight = sum(phase.get("weight", 0) for phase in phases)
        if abs(total_weight - 1.0) > 0.01:
            print(f"⚠️  Warning: Phase weights sum to {total_weight:.3f}, not 1.0")

        # Validate required fields
        for i, phase in enumerate(phases):
            required_fields = ["name", "conf", "iou", "weight"]
            missing = [field for field in required_fields if field not in phase]
            if missing:
                raise ValueError(f"Phase {i} missing required fields: {missing}")

        self.detection_phases = phases
        print(f"✅ Configured {len(phases)} detection phases")
        for i, phase in enumerate(phases):
            print(f"   Phase {i+1}: {phase['name']} (conf={phase['conf']}, weight={phase['weight']})")

    def _calculate_iou_tuples(self, box1: tuple, box2: tuple) -> float:
        """Calculate IoU between two bounding boxes in tuple format"""
        x1_1, y1_1, x2_1, y2_1 = box1
        x1_2, y1_2, x2_2, y2_2 = box2

        # Calculate intersection
        ix1, iy1 = max(x1_1, x1_2), max(y1_1, y1_2)
        ix2, iy2 = min(x2_1, x2_2), min(y2_1, y2_2)

        if ix2 <= ix1 or iy2 <= iy1:
            return 0.0

        intersection = (ix2 - ix1) * (iy2 - iy1)
        area1 = (x2_1 - x1_1) * (y2_1 - y1_1)
        area2 = (x2_2 - x1_2) * (y2_2 - y1_2)
        union = area1 + area2 - intersection

        return intersection / max(union, 1)

    # ------------------- OCR + CLIP preselection -----------------------------
    def _analyze_crop_visuals(self, crop_bgr: np.ndarray) -> dict:
        """Analyzes a crop for dominant color properties to distinguish printers from boxes."""
        if crop_bgr.size == 0:
            return {"is_mostly_white": False, "is_mostly_blue": False}

        # Convert to HSV for better color analysis
        hsv = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2HSV)

        # --- White/Gray Detection ---
        # Define a broad range for white, light gray, and silver colors
        lower_white = np.array([0, 0, 150])
        upper_white = np.array([180, 50, 255])
        white_mask = cv2.inRange(hsv, lower_white, upper_white)

        # --- Blue Detection ---
        # Define a range for the Epson blue
        lower_blue = np.array([95, 80, 40])
        upper_blue = np.array([125, 255, 255])
        blue_mask = cv2.inRange(hsv, lower_blue, upper_blue)

        # Calculate the percentage of the image that is white or blue
        total_pixels = crop_bgr.shape[0] * crop_bgr.shape[1]
        white_percentage = (cv2.countNonZero(white_mask) / total_pixels) * 100
        blue_percentage = (cv2.countNonZero(blue_mask) / total_pixels) * 100

        # Determine if the object is primarily one color
        # Thresholds can be tuned, but these are generally effective.
        is_mostly_white = white_percentage > 40
        is_mostly_blue = blue_percentage > 35

        return {
            "is_mostly_white": is_mostly_white,
            "is_mostly_blue": is_mostly_blue,
            "white_pct": white_percentage,
            "blue_pct": blue_percentage,
        }

    async def _classify_proposals(self, img, props, bands, header_limit_y, ad_box=None):
        """
        ENHANCED proposal classification with a robust, heuristic-first decision process.
        1.  Identify price tags by size.
        2.  Identify promotional graphics by position.
        3.  For remaining objects, use strong visual heuristics (color) to classify.
        4.  Use CLIP similarity only as a fallback for ambiguous cases.
        """
        H, W = img.shape[:2]
        final_proposals = []
        PRICE_TAG_AREA_THRESHOLD = 0.005  # 0.5% of total image area

        print(f"\n🎯 Enhanced Classification: Running {len(props)} proposals...")
        print("   " + "="*60)

        for p in props:
            x1, y1, x2, y2 = p["box"]
            area = (x2 - x1) * (y2 - y1)
            area_ratio = area / (H * W)
            center_y = (y1 + y2) / 2

            # Helper to determine shelf level for context
            shelf_level = self._determine_shelf_level(center_y, bands)

            # --- 1. Price Tag Check (by size) ---
            if area_ratio < PRICE_TAG_AREA_THRESHOLD:
                final_proposals.append(
                    DetectionBox(
                        x1=x1, y1=y1, x2=x2, y2=y2,
                        confidence=p.get('yolo_conf', 0.8),
                        class_id=CID["price_tag"],
                        class_name="price_tag",
                        area=area,
                        ocr_text=p.get('ocr_text')
                    )
                )
                continue

            # --- 2. Promotional Graphic Check (by position) ---
            if center_y < header_limit_y:
                final_proposals.append(
                    DetectionBox(
                        x1=x1, y1=y1, x2=x2, y2=y2,
                        confidence=p.get('yolo_conf', 0.9),
                        class_id=CID["promotional_candidate"],
                        class_name="promotional_candidate",
                        area=area,
                        ocr_text=p.get('ocr_text')
                    )
                )
                continue

            # --- 3. Heuristic & CLIP Classification for Products/Boxes ---
            try:
                crop_bgr = img[y1:y2, x1:x2]
                if crop_bgr.size == 0:
                    continue

                # Get visual heuristics and CLIP scores
                visuals = self._analyze_crop_visuals(crop_bgr)

                crop_pil = Image.fromarray(cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB))
                with torch.no_grad():
                    ip = self.proc(images=crop_pil, return_tensors="pt").to(self.device)
                    img_feat = self.clip.get_image_features(**ip)
                    img_feat /= img_feat.norm(dim=-1, keepdim=True)
                    text_sims = (img_feat @ self.text_feats.T).squeeze().tolist()
                    s_poster, s_printer, s_box = text_sims[0], text_sims[1], text_sims[2]

                # --- New Decision Logic ---
                class_name = None
                confidence = 0.8 # Default confidence for heuristic-based decision

                # Priority 1: Strong color evidence overrides everything.
                if visuals["is_mostly_white"] and not visuals["is_mostly_blue"]:
                    class_name = "product_candidate" # It's a white printer device
                    confidence = 0.95 # High confidence in color heuristic
                elif visuals["is_mostly_blue"]:
                    class_name = "box_candidate" # It's a blue product box
                    confidence = 0.95

                # Priority 2: If color is ambiguous, use shelf location as a strong hint.
                if not class_name:
                    if shelf_level == "middle":
                        class_name = "product_candidate"
                        confidence = 0.85
                    elif shelf_level == "bottom":
                        class_name = "box_candidate"
                        confidence = 0.85

                # Priority 3 (Fallback): If still undecided, use the original CLIP score.
                if not class_name:
                    if s_printer > s_box:
                        class_name = "product_candidate"
                        confidence = s_printer
                    else:
                        class_name = "box_candidate"
                        confidence = s_box

                final_class_id = CID[class_name]
                final_proposals.append(
                    DetectionBox(
                        x1=x1, y1=y1, x2=x2, y2=y2,
                        confidence=confidence,
                        class_id=final_class_id,
                        class_name=class_name,
                        area=area,
                        ocr_text=p.get('ocr_text')
                    )
                )

            except Exception as e:
                self.logger.error(f"Failed to classify proposal with heuristics/CLIP: {e}")

        return final_proposals

    # --------------------- merge/cleanup ------------------------------
    def _merge(self, dets: List[DetectionBox], iou_same=0.3) -> List[DetectionBox]:
        """Enhanced merge with size-aware logic"""
        dets = sorted(dets, key=lambda d: (d.class_name, -d.confidence, -d.area))
        out = []

        for d in dets:
            placed = False
            for m in out:
                if d.class_name == m.class_name:
                    iou = self._iou(d, m)

                    # Different merge strategies based on class
                    if d.class_name == "box_candidate":
                        # More aggressive merging for boxes (they're often tightly packed)
                        merge_threshold = 0.25
                    elif d.class_name == "product_candidate":
                        # Conservative merging for printers (they're usually separate)
                        merge_threshold = 0.4
                    else:
                        merge_threshold = iou_same

                    if iou > merge_threshold:
                        # Merge by taking the union
                        m.x1 = min(m.x1, d.x1)
                        m.y1 = min(m.y1, d.y1)
                        m.x2 = max(m.x2, d.x2)
                        m.y2 = max(m.y2, d.y2)
                        m.area = (m.x2 - m.x1) * (m.y2 - m.y1)
                        m.confidence = max(m.confidence, d.confidence)
                        placed = True
                        print(f"   🔄 Merged {d.class_name} with IoU={iou:.3f}")
                        break

            if not placed:
                out.append(d)

        return out

    # ------------------------------ debug ------------------------------------
    def _rectangle_dashed(self, img, pt1, pt2, color, thickness=2, gap=9):
        x1, y1 = pt1
        x2, y2 = pt2
        # top
        for x in range(x1, x2, gap * 2):
            cv2.line(img, (x, y1), (min(x + gap, x2), y1), color, thickness)
        # bottom
        for x in range(x1, x2, gap * 2):
            cv2.line(img, (x, y2), (min(x + gap, x2), y2), color, thickness)
        # left
        for y in range(y1, y2, gap * 2):
            cv2.line(img, (x1, y), (x1, min(y + gap, y2)), color, thickness)
        # right
        for y in range(y1, y2, gap * 2):
            cv2.line(img, (x2, y), (x2, min(y + gap, y2)), color, thickness)

    def _draw_corners(self, img, pt1, pt2, color, length=12, thickness=2):
        x1, y1 = pt1
        x2, y2 = pt2
        # TL
        cv2.line(img, (x1, y1), (x1 + length, y1), color, thickness)
        cv2.line(img, (x1, y1), (x1, y1 + length), color, thickness)
        # TR
        cv2.line(img, (x2, y1), (x2 - length, y1), color, thickness)
        cv2.line(img, (x2, y1), (x2, y1 + length), color, thickness)
        # BL
        cv2.line(img, (x1, y2), (x1 + length, y2), color, thickness)
        cv2.line(img, (x1, y2), (x1, y2 - length), color, thickness)
        # BR
        cv2.line(img, (x2, y2), (x2 - length, y2), color, thickness)
        cv2.line(img, (x2, y2), (x2, y2 - length), color, thickness)

    def _draw_phase_areas(self, img, props, roi_box, show_labels=True):
        """
        Draw per-phase borders (no fill). Thickness encodes confidence.
        poster_high = magenta (solid), high_confidence = green (solid), aggressive = orange (dashed).
        """
        phase_colors = {
            "poster_high":     (200, 0, 200),  # BGR
            "high_confidence": (0, 220, 0),
            "aggressive":      (0, 165, 255),
        }
        dashed = {"poster_high": False, "high_confidence": False, "aggressive": True}

        # --- legend counts
        counts = Counter(p.get("phase", "aggressive") for p in props)

        # --- draw ROI
        rx1, ry1, rx2, ry2 = roi_box
        cv2.rectangle(img, (rx1, ry1), (rx2, ry2), (0, 255, 0), 2)

        # --- per-proposal borders
        for p in props:
            x1, y1, x2, y2 = p["box"]
            phase = p.get("phase", "aggressive")
            conf  = float(p.get("confidence", 0.0))
            color = phase_colors.get(phase, (180, 180, 180))

            # thickness: 1..5 with a gentle curve so small conf doesn't vanish
            t = max(1, min(5, int(round(1 + 4 * math.sqrt(max(0.0, min(conf, 1.0)))))))

            if dashed.get(phase, False):
                self._rectangle_dashed(img, (x1, y1), (x2, y2), color, thickness=t, gap=9)
            else:
                cv2.rectangle(img, (x1, y1), (x2, y2), color, t)

            # add subtle phase corners to help when borders overlap
            self._draw_corners(img, (x1, y1), (x2, y2), color, length=10, thickness=max(1, t - 1))

            if show_labels:
                lbl = f"{phase.split('_')[0][:1].upper()} {conf:.2f}"
                ty = max(12, y1 - 6)
                cv2.putText(img, lbl, (x1 + 2, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1, cv2.LINE_AA)

        # --- legend (top-left of ROI)
        legend_items = [("poster_high", "Poster"), ("high_confidence", "High"), ("aggressive", "Agg")]
        lx, ly = rx1 + 6, max(18, ry1 + 16)
        for key, name in legend_items:
            col = phase_colors[key]
            cv2.rectangle(img, (lx, ly - 10), (lx + 18, ly - 2), col, -1)
            text = f"{name}: {counts.get(key, 0)}"
            cv2.putText(img, text, (lx + 24, ly - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)
            ly += 16

        return img

    def _draw_yolo(self, img, props, roi_box, shelf_lines):
        """
        Draw raw YOLO detections with detailed labels
        """
        rx1, ry1, rx2, ry2 = roi_box

        # Draw ROI box
        cv2.rectangle(img, (rx1, ry1), (rx2, ry2), (0, 255, 0), 3)
        cv2.putText(img, f"ROI: {rx2-rx1}x{ry2-ry1}", (rx1, ry1-10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

        # Draw shelf lines
        for i, y in enumerate(shelf_lines):
            cv2.line(img, (rx1, y), (rx2, y), (0, 255, 255), 2)
            cv2.putText(img, f"Shelf{i+1}", (rx1+5, y-5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 255), 1)

        # Color mapping for retail candidates
        candidate_colors = {
            "promotional_graphic": (255, 0, 255),   # Magenta
            "printer": (255, 140, 0),               # Orange
            "tv": (0, 200, 0),                     # Green
            "product_candidate": (200, 200, 0),     # Yellow
            "product_box": (0, 140, 255),           # Blue
            "small_object": (128, 128, 128),        # Gray
            "ink_bottle": (160, 0, 200),            # Purple
        }

        for p in props:
            (x1, y1, x2, y2) = p["box"]

            # Choose color based on primary retail candidate
            candidates = p.get("retail_candidates", ["unknown"])
            primary_candidate = candidates[0] if candidates else "unknown"
            color = candidate_colors.get(primary_candidate, (255, 255, 255))

            # Draw detection
            cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)

            # Enhanced label
            idx = p["raw_index"]
            yolo_class = p["yolo_label"]
            conf = p["yolo_conf"]
            area_pct = p["area_ratio"] * 100

            label1 = f"#{idx} {yolo_class}→{primary_candidate}"
            label2 = f"conf:{conf:.3f} area:{area_pct:.1f}%"

            cv2.putText(img, label1, (x1, max(15, y1 - 5)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1, cv2.LINE_AA)
            cv2.putText(img, label2, (x1, max(30, y1 + 15)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.35, color, 1, cv2.LINE_AA)

        return img

    def _draw_phase1(self, img, roi_box, shelf_lines, dets, ad_box=None):
        """
        FIXED: Phase-1 debug drawing with better info
        """
        rx1, ry1, rx2, ry2 = roi_box
        cv2.rectangle(img, (rx1, ry1), (rx2, ry2), (0, 255, 0), 2)

        for y in shelf_lines:
            cv2.line(img, (rx1, y), (rx2, y), (0, 255, 255), 2)

        colors = {
            "promotional_candidate": (0, 200, 0),
            "product_candidate": (255, 140, 0),
            "box_candidate": (0, 140, 255),
            "price_tag": (255, 0, 255),
        }

        for i, d in enumerate(dets, 1):
            c = colors.get(d.class_name, (200, 200, 200))
            cv2.rectangle(img, (d.x1, d.y1), (d.x2, d.y2), c, 2)

            # Enhanced label with detection info
            w, h = d.x2 - d.x1, d.y2 - d.y1
            area_pct = (d.area / (img.shape[0] * img.shape[1])) * 100
            aspect = w / max(h, 1)
            center_y = (d.y1 + d.y2) / 2

            print(f"   #{i:2d}: {d.class_name:20s} conf={d.confidence:.3f} "
                f"area={area_pct:.2f}% AR={aspect:.2f} center_y={center_y:.0f}")

            label = f"#{i} {d.class_name} {d.confidence:.2f}"
            cv2.putText(img, label, (d.x1, max(15, d.y1 - 4)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, c, 1, cv2.LINE_AA)

        if ad_box is not None:
            cv2.rectangle(img, (ad_box[0], ad_box[1]), (ad_box[2], ad_box[3]), (0, 255, 128), 2)
            cv2.putText(
                img, "poster_roi",
                (ad_box[0], max(12, ad_box[1] - 4)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.4, (0, 255, 128), 1, cv2.LINE_AA,
            )

        return img


class PlanogramCompliancePipeline(AbstractPipeline):
    """
    Pipeline for planogram compliance checking.

    3-Step planogram compliance pipeline:
    Step 1: Object Detection (YOLO/ResNet)
    Step 2: LLM Object Identification with Reference Images
    Step 3: Planogram Comparison and Compliance Verification
    """
    def __init__(
        self,
        planogram_config: PlanogramConfig,
        llm: Any = None,
        llm_provider: str = "google",
        llm_model: Optional[str] = None,
        **kwargs: Any
    ):
        """
        Initialize the 3-step pipeline

        Args:
            llm_provider: LLM provider for identification
            llm_model: Specific LLM model
            api_key: API key
            detection_model: Object detection model to use
        """
        # Endcap geometry defaults (can be tuned per program)
        geometry = planogram_config.endcap_geometry
        self.endcap_aspect_ratio = geometry.aspect_ratio
        self.left_margin_ratio = geometry.left_margin_ratio
        self.right_margin_ratio = geometry.right_margin_ratio
        self.top_margin_ratio = geometry.top_margin_ratio
        self.bottom_margin_ratio = geometry.bottom_margin_ratio
        self.inter_shelf_padding = geometry.inter_shelf_padding

        # saving the planogram config for later use
        self.planogram_config = planogram_config
        super().__init__(
            llm=llm,
            llm_provider=llm_provider,
            llm_model=llm_model,
            **kwargs
        )
        reference_images = planogram_config.reference_images
        references = list(reference_images.values()) if reference_images else None
        # Initialize the generic shape detector
        self.shape_detector = RetailDetector(
            yolo_model=planogram_config.detection_model,
            conf=planogram_config.confidence_threshold,
            llm=self.llm,
            device="cuda" if torch.cuda.is_available() else "cpu",
            reference_images=references
        )
        self.logger.debug(
            f"Initialized RetailDetector with {planogram_config.detection_model}"
        )
        self.reference_images = reference_images or {}
        self.confidence_threshold = planogram_config.confidence_threshold

    async def detect_objects_and_shelves(
        self,
        image: Image,
        image_array: np.ndarray,
        endcap: Detection,
        ad: Optional[Detection] = None,
        brand: Optional[Detection] = None,
        panel_text: Optional[Detection] = None,
        planogram_description: Optional[PlanogramDescription] = None
    ):
        self.logger.debug(
            "Step 1: Detecting generic shapes and boundaries..."
        )

        det_out = await self.shape_detector.detect(
            image=image,
            image_array=image_array,
            endcap=endcap,
            ad=ad,
            planogram=planogram_description,
            debug_yolo="/tmp/data/yolo_raw.png",
            debug_phase1="/tmp/data/yolo_phase1_debug.png",
            debug_phases="/tmp/data/yolo_phases_debug.png",
        )

        shelves = det_out["shelves"]          # {'top': DetectionBox(...), 'middle': ...}
        proposals    = det_out["proposals"]        # List[DetectionBox]

        print("PROPOSALS:", proposals)
        print("SHELVES:", shelves)

        h, w = image_array.shape[:2]
        if brand:
            bx1, by1, bx2, by2 = brand.bbox.get_pixel_coordinates(width=w, height=h)
            proposals.append(
                DetectionBox(
                    x1=bx1, y1=by1, x2=bx2, y2=by2,
                    confidence=brand.confidence,
                    class_id=CID["brand_logo"],
                    class_name="brand_logo",
                    area=(bx2 - bx1) * (by2 - by1),
                    ocr_text=brand.content
                )
            )
            print(f"  + Injected brand_logo: '{brand.content}'")

        if panel_text:
            tx1, ty1, tx2, ty2 = panel_text.bbox.get_pixel_coordinates(width=w, height=h)
            proposals.append(
                DetectionBox(
                    x1=tx1, y1=ty1, x2=tx2, y2=ty2,
                    confidence=panel_text.confidence,
                    class_id=CID["poster_text"],
                    class_name="poster_text",
                    area=(tx2 - tx1) * (ty2 - ty1),
                    ocr_text=panel_text.content.replace('.', ' ')
                )
            )
            print(f"  + Injected poster_text: '{panel_text.content}'")

        # --- IMPORTANT: use Phase-1 shelf bands (not %-of-image buckets) ---
        shelf_regions = self._materialize_shelf_regions(shelves, proposals, planogram_description)

        detections = list(proposals)

        self.logger.debug(
            "Found %d objects in %d shelf regions", len(detections), len(shelf_regions)
        )

        self.logger.debug("Found %d objects in %d shelf regions",
                        len(detections), len(shelf_regions))
        return shelf_regions, detections

    def _materialize_shelf_regions(
        self,
        shelves_dict: Dict[str, DetectionBox],
        dets: List[DetectionBox],
        planogram_description: Optional[PlanogramDescription] = None
    ) -> List[ShelfRegion]:
        """Turn Phase-1 shelf bands into ShelfRegion objects and assign detections by y-overlap."""
        def y_overlap(a1, a2, b1, b2) -> int:
            return max(0, min(a2, b2) - max(a1, b1))

        regions: List[ShelfRegion] = []

        # Iterate through the shelves defined in the planogram config, in their specified order.
        for shelf_config in planogram_description.shelves:
            level = shelf_config.level
            band = shelves_dict.get(level)
            if not band:
                self.logger.warning(
                    f"Shelf '{level}' is defined in the planogram but was not detected in the image."
                )
                continue

            # Find all object proposals that vertically overlap with this shelf's detected band.
            # An object belongs to the shelf if any part of it is within the shelf's y-range.
            objs = [d for d in dets if y_overlap(d.y1, d.y2, band.y1, band.y2) > 0]

            # If no objects were found on this shelf, we don't need to create a region for it.
            if objs:
                x1 = min(o.x1 for o in objs)
                x2 = max(o.x2 for o in objs)
            else:
                # Use band boundaries if no objects
                x1, x2 = band.x1, band.x2

            # Create a new bounding box for the ShelfRegion.
            # The Y coordinates are fixed by the detected shelf band.
            # The X coordinates are calculated as the min/max extent of the objects on that shelf.
            y1 = band.y1
            y2 = band.y2

            bbox = DetectionBox(
                x1=x1, y1=y1, x2=x2, y2=y2,
                confidence=1.0,
                class_id=CID["shelf_region"],
                class_name="shelf_region",
                area=(x2 - x1) * (y2 - y1)
            )

            # Create the final ShelfRegion object.
            regions.append(
                ShelfRegion(
                    shelf_id=f"{level}_shelf",
                    bbox=bbox,
                    level=level,
                    objects=objs
                )
            )

        return regions

    async def identify_objects_with_references(
        self,
        image: Union[str, Path, Image.Image],
        detections: List[DetectionBox],
        shelf_regions: List[ShelfRegion],
        reference_images: List[Union[str, Path, Image.Image]],
        prompt: str
    ) -> List[IdentifiedProduct]:
        """
        Step 2: Use LLM to identify detected objects using reference images

        Args:
            image: Original endcap image
            detections: Object detections from Step 1
            shelf_regions: Shelf regions from Step 1
            reference_images: Reference product images
            prompt: Prompt for object identification

        Returns:
            List of identified products
        """

        self.logger.debug(
            f"Starting identification with {len(detections)} detections"
        )
        # If no detections, return empty list
        if not detections:
            self.logger.warning("No detections to identify")
            return []


        pil_image = self._get_image(image)

        # Create annotated image showing detection boxes
        effective_dets = [
            d for d in detections if d.class_name not in {"slot", "shelf_region", "price_tag", "fact_tag"}
        ]
        annotated_image = self._create_annotated_image(pil_image, effective_dets)

        async with self.llm as client:
            try:
                extra_refs = {
                    "annotated_image": annotated_image,
                    **reference_images
                }
                identified_products = await client.image_identification(
                    prompt=self._build_gemini_identification_prompt(
                        effective_dets,
                        shelf_regions,
                        partial_prompt=prompt
                    ),
                    image=image,
                    detections=effective_dets,
                    shelf_regions=shelf_regions,
                    reference_images=extra_refs,
                    temperature=0.0
                )
                identified_products = await self._augment_products_with_box_ocr(
                    image,
                    identified_products
                )
                for product in identified_products:
                    if product.product_type == "promotional_graphic":
                        if lines := await self._extract_text_from_region(image, product.detection_box):
                            snippet = " ".join(lines)[:120]
                            product.visual_features = (product.visual_features or []) + [f"ocr:{snippet}"]
                return identified_products

            except Exception as e:
                self.logger.error(f"Error in structured identification: {e}")
                traceback.print_exc()
                raise

    def _guess_et_model_from_text(self, text: str) -> Optional[str]:
        """
        Find Epson EcoTank model tokens in text.
        Returns normalized like 'et-4950' (device) or 'et-2980', etc.
        """
        if not text:
            return None
        t = text.lower().replace(" ", "")
        # common variants: et-4950, et4950, et – 4950, etc.
        m = re.search(r"et[-]?\s?(\d{4})", t)
        if not m:
            return None
        num = m.group(1)
        # Accept only models we care about (tighten if needed)
        if num in {"2980", "3950", "4950"}:
            return f"et-{num}"
        return None


    def _maybe_brand_from_text(self, text: str) -> Optional[str]:
        if not text:
            return None
        t = text.lower()
        if "epson" in t or "ecotank" in t:
            return "Epson"
        if 'hisense' in t or "canvastv" in t:
            return "Hisense"
        if "firetv" in t or "fire tv" in t:
            return "Amazon"
        if "google tv" in t or "chromecast" in t:
            return "Google"
        return None

    def _normalize_ocr_text(self, s: str) -> str:
        """
        Make OCR text match-friendly:
        - Unicode normalize (NFKC), strip diacritics
        - Replace fancy dashes/quotes with spaces
        - Remove non-alnum except spaces, collapse whitespace
        - Lowercase
        """
        if not s:
            return ""
        s = unicodedata.normalize("NFKC", s)
        # strip accents
        s = "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch))
        # unify punctuation to spaces
        s = re.sub(r"[—–‐-‒–—―…“”\"'·•••·•—–/\\|_=+^°™®©§]", " ", s)
        # keep letters/digits/spaces
        s = re.sub(r"[^A-Za-z0-9 ]+", " ", s)
        # collapse
        s = re.sub(r"\s+", " ", s).strip().lower()
        return s

    async def _augment_products_with_box_ocr(
        self,
        image: Union[str, Path, Image.Image],
        products: List[IdentifiedProduct]
    ) -> List[IdentifiedProduct]:
        """Add OCR-derived evidence to boxes/printers and fix product_model when we see ET-xxxx."""
        for p in products:
            if not p.detection_box:
                continue
            # normalize product brand logo with OCR or content from detection if is null:
            if getattr(p.detection_box, 'class_name', None) == 'brand_logo' and not getattr(p, 'brand', None):
                if p.detection_box.ocr_text:
                    brand = self._maybe_brand_from_text(p.detection_box.ocr_text)
                    if brand:
                        try:
                            p.brand = brand  # only if IdentifiedProduct has 'brand'
                        except Exception:
                            if not p.visual_features:
                                p.visual_features = []
                            p.visual_features.append(f"brand:{brand}")
            if p.product_type in {"product_box", "printer"}:
                lines = await self._extract_text_from_region(image, p.detection_box, mode="model")
                if lines:
                    # Keep some OCR as visual evidence (don’t explode the list)
                    snippet = " ".join(lines)[:120]
                    if not p.visual_features:
                        p.visual_features = []
                    p.visual_features.append(f"ocr:{snippet}")

                    # Brand hint
                    brand = self._maybe_brand_from_text(snippet)
                    if brand and not getattr(p, "brand", None):
                        try:
                            p.brand = brand  # only if IdentifiedProduct has 'brand'
                        except Exception:
                            # If the model doesn’t have brand, keep it as a feature.
                            p.visual_features.append(f"brand:{brand}")

                    # Model from OCR
                    model = self._guess_et_model_from_text(snippet)
                    if model:
                        # Normalize to your scheme:
                        target = model.upper()
                        # If missing or mismatched, replace
                        if not p.product_model:
                            p.product_model = target
                        else:
                            # If current looks generic/incorrect, fix it
                            cur = (p.product_model or "").lower()
                            if "et-" in target.lower() and ("et-" not in cur or "box" in target.lower() and "box" not in cur):
                                p.product_model = target
            elif p.product_type == "promotional_graphic":
                if lines := await self._extract_text_from_region(image, p.detection_box):
                    snippet = " ".join(lines)[:160]
                    p.visual_features = (p.visual_features or []) + [f"ocr:{snippet}"]
                    # keep a normalized text blob
                    joined = " ".join(lines)
                    if norm := self._normalize_ocr_text(joined):
                        p.visual_features.append(norm)
                        for ln in lines:
                            if ln and (nln := self._normalize_ocr_text(ln)) and nln not in p.visual_features:
                                p.visual_features.append(nln)

                    # NEW: infer brand from OCR/features if missing
                    if not getattr(p, "brand", None):
                        brand = self._maybe_brand_from_text(joined)
                        if not brand and p.visual_features:
                            vf_blob = " ".join(p.visual_features)
                            brand = self._maybe_brand_from_text(vf_blob)
                        if brand:
                            p.brand = brand
        return products

    async def _extract_text_from_region(
        self,
        image: Union[str, Path, Image.Image],
        detection_box: DetectionBox,
        mode: str = "generic",          # "generic" | "model"
    ) -> List[str]:
        """Extract text from a region with OCR.
        - generic: multi-pass (psm 6 & 4) + unsharp + binarize
        - model  : tuned to catch ET-xxxx
        Returns lines + normalized variants so TextMatcher has more chances.
        """
        try:
            pil_image = Image.open(image) if isinstance(image, (str, Path)) else image
            pad = 10
            x1 = max(0, detection_box.x1 - pad)
            y1 = max(0, detection_box.y1 - pad)
            x2 = min(pil_image.width - 1, detection_box.x2 + pad)
            y2 = min(pil_image.height - 1, detection_box.y2 + pad)

            # ENSURE VALID CROP COORDINATES
            if x1 >= x2:
                x2 = x1 + 10
            if y1 >= y2:
                y2 = y1 + 10

            crop_rgb = pil_image.crop((x1, y1, x2, y2)).convert("RGB")

            def _prep(arr):
                g = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
                g = cv2.resize(g, None, fx=1.5, fy=1.5, interpolation=cv2.INTER_CUBIC)
                blur = cv2.GaussianBlur(g, (0, 0), sigmaX=1.0)
                sharp = cv2.addWeighted(g, 1.6, blur, -0.6, 0)
                _, th = cv2.threshold(sharp, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
                return th

            if mode == "model":
                th = _prep(np.array(crop_rgb))
                crop = Image.fromarray(th).convert("L")
                cfg = "--oem 3 --psm 6 -l eng -c tessedit_char_whitelist=ETet0123456789-ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                raw = pytesseract.image_to_string(crop, config=cfg)
                lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
            else:
                arr = np.array(crop_rgb)
                th = _prep(arr)
                # two passes help for 'Goodbye Cartridges' on light box
                raw1 = pytesseract.image_to_string(Image.fromarray(th), config="--psm 6 -l eng")
                raw2 = pytesseract.image_to_string(Image.fromarray(th), config="--psm 4 -l eng")
                raw  = raw1 + "\n" + raw2
                lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]

            # Add normalized variants to help TextMatcher:
            #  - lowercase, punctuation stripped
            #  - a single combined line
            def norm(s: str) -> str:
                s = s.lower()
                s = re.sub(r"[^a-z0-9\s]", " ", s)         # drop punctuation like colons
                s = re.sub(r"\s+", " ", s).strip()
                return s

            variants = [norm(ln) for ln in lines if ln]
            if variants:
                variants.append(norm(" ".join(lines)))

            # merge unique while preserving originals first
            out = lines[:]
            for v in variants:
                if v and v not in out:
                    out.append(v)

            return out

        except Exception as e:
            self.logger.error(f"Text extraction failed: {e}")
            return []

    def _get_image(
        self,
        image: Union[str, Path, Image.Image]
    ) -> Image.Image:
        """Load image from path or return copy if already PIL"""

        if isinstance(image, (str, Path)):
            pil_image = Image.open(image).copy()
        else:
            pil_image = image.copy()
        return pil_image

    def _create_annotated_image(
        self,
        image: Image.Image,
        detections: List[DetectionBox]
    ) -> Image.Image:
        """Create an annotated image with detection boxes and IDs"""

        draw = ImageDraw.Draw(image)

        for i, detection in enumerate(detections):
            # Draw bounding box
            draw.rectangle(
                [(detection.x1, detection.y1), (detection.x2, detection.y2)],
                outline="red", width=2
            )

            # Add detection ID and confidence
            label = f"ID:{i+1} ({detection.confidence:.2f})"
            draw.text((detection.x1, detection.y1 - 20), label, fill="red")

        return image

    def _build_gemini_identification_prompt(
        self,
        detections: List[DetectionBox],
        shelf_regions: List[ShelfRegion],
        partial_prompt: str
    ) -> str:
        """Builds a more detailed prompt to help Gemini differentiate similar products."""
        detection_lines = ["\nDETECTED OBJECTS (with pre-assigned IDs):"]
        if detections:
            for i, detection in enumerate(detections, 1):
                detection_lines.append(
                    f"ID {i}: Initial class '{detection.class_name}' at bbox ({detection.x1},{detection.y1},{detection.x2},{detection.y2})"
                )
        else:
            detection_lines.append("None")

        shelf_definitions = ["\n**VALID SHELF NAMES & LOCATIONS (Ground Truth):**"]
        valid_shelf_names = []
        num_detections = len(detections)
        for shelf in shelf_regions:
            # if shelf.level in ['header', 'middle', 'bottom']:
            valid_shelf_names.append(f"'{shelf.level}'")
            shelf_definitions.append(f"- Shelf '{shelf.level}': Covers the vertical pixel range from y={shelf.bbox.y1} to y={shelf.bbox.y2}.")
        shelf_definitions.append(f"\n**RULE:** For the `shelf_location` field, you MUST use one of these exact names: {', '.join(valid_shelf_names)}.")

        # REVISED: Enhanced prompt with new rules
        prompt = f"""
You are an expert at identifying retail products in planogram displays.
I have provided an image of a retail endcap, labeled reference images, and a list of {num_detections} pre-detected objects.

{''.join(detection_lines)}
{''.join(shelf_definitions)}

**YOUR TASK:**
For each distinct product, you must first analyze its visual features according to the guide, state your reasoning, and then provide the final identification.

"""
        partial_prompt = partial_prompt.strip().format(
            num_detections=num_detections,
            shelf_names=", ".join(valid_shelf_names)
        )
        prompt += partial_prompt
        prompt += f"""
---

**JSON OUTPUT FORMAT:**
Respond with a single JSON object. For each **distinct product** you identify, provide an entry in the 'detections' list.

- **detection_id**: The pre-detected ID number, or `null` for newly found items.
- **detection_box**: **REQUIRED** if `detection_id` is `null`. An array of four numbers `[x1, y1, x2, y2]`.
- **product_type**: printer, tv, product_box, fact_tag, promotional_graphic, or ink_bottle.
- **product_model**: Follow naming rules above.
- **confidence**: Your confidence (0.0-1.0).
- **visual_features**: List of key visual features as if device is turned on, color, size, brightness or any other visual features.
-   **reasoning**: A brief sentence explaining your identification based on the visual guide. Example: "Reasoning: The control panel has a physical key pad, which matches the ET-3950 guide."
-   **reference_match**: Which reference image name matches (or "none").
- **shelf_location**: {', '.join(valid_shelf_names)}.
- **position_on_shelf**: 'left', 'center', or 'right'.

**!! FINAL CHECK !!**
- Ensure your response contains **NO DUPLICATE** entries for the same physical object.
- **CRITICAL**: Verify that any item with `detection_id: null` also includes a `detection_box`.

Analyze all provided images and return the complete JSON response.
"""
        return prompt

    def _calculate_visual_feature_match(self, expected_features: List[str], detected_features: List[str]) -> float:
        """
        Enhanced visual feature matching with semantic understanding
        """
        if not expected_features:
            return 1.0  # No requirements = full match

        if not detected_features:
            return 0.0  # No detected features but requirements exist

        # Normalize and create keyword sets for semantic matching
        def extract_keywords(text):
            """Extract meaningful keywords from feature text"""
            text = text.lower().strip()
            # Remove common words that don't add meaning
            stop_words = {'a', 'an', 'the', 'is', 'are', 'on', 'of', 'in', 'at', 'to', 'for', 'with', 'visible', 'displayed', 'showing'}
            words = [w for w in text.split() if w not in stop_words and len(w) > 1]
            return set(words)

        # Special semantic mappings for common concepts
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
            """Check if expected word semantically matches any detected keywords"""
            if expected_word in detected_keywords:
                return True

            # Check semantic mappings
            if expected_word in semantic_mappings:
                synonyms = semantic_mappings[expected_word]
                return any(syn in detected_keywords for syn in synonyms)

            # Check if any detected keyword contains the expected word
            return any(expected_word in keyword for keyword in detected_keywords)

        matches = 0
        for expected in expected_features:
            expected_keywords = extract_keywords(expected)

            # Combine all detected feature keywords
            all_detected_keywords = set()
            for detected in detected_features:
                all_detected_keywords.update(extract_keywords(detected))

            # Check if any expected keyword has a semantic match
            feature_matched = False
            for exp_keyword in expected_keywords:
                if semantic_match(exp_keyword, all_detected_keywords):
                    feature_matched = True
                    break

            if feature_matched:
                matches += 1

        score = matches / len(expected_features)
        return score

    def check_planogram_compliance(
        self,
        identified_products: List[IdentifiedProduct],
        planogram_description: PlanogramDescription,
    ) -> List[ComplianceResult]:
        """Check compliance of identified products against the planogram."""
        def _matches(ek, fk) -> bool:
            (e_ptype, e_base), (f_ptype, f_base) = ek, fk
            if e_ptype != f_ptype:
                return False
            if not e_base or not f_base:
                return True
            # If no base model specified in planogram, accept type-only match
            if not e_base:
                return True
            if f_base == e_base or e_base in f_base or f_base in e_base:
                return True
            if f_base == e_base:
                return True
            # NEW: allow cross-slug promo matching if synonyms overlap
            if e_ptype == "promotional_graphic":
                fam = lambda s: "canvas-tv" if "canvas-tv" in s else s
                return fam(e_base) == fam(f_base)
            # containment: allow 'et-4950' inside 'epson et-4950 bundle' etc.
            return e_base in f_base or f_base in e_base

        results: List[ComplianceResult] = []

        planogram_brand = planogram_description.brand.lower()
        found_brand_product = next((
            p for p in identified_products if p.brand and p.brand.lower() == planogram_brand
        ), None)

        brand = getattr(planogram_description, 'brand', planogram_brand)

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

        for shelf_cfg in planogram_description.shelves:
            shelf_level = shelf_cfg.level
            products_on_shelf = by_shelf.get(shelf_level, [])
            expected = []
            # --- 1. Main matching loop for expected products ---
            for sp in shelf_cfg.products:
                if sp.product_type in ("fact_tag", "price_tag", "slot"):
                    continue

                e_ptype, e_base = self._canonical_expected_key(sp, brand=brand)
                expected.append((e_ptype, e_base))

            # --- Build canonical FOUND keys for this shelf (and keep refs for reporting) ---
            found_keys = []      # list[(ptype, base_model)]
            found_lookup = []    # parallel to found_keys to map back to strings for reporting
            promos = []
            for p in products_on_shelf:
                if p.product_type in ("fact_tag", "price_tag", "slot", "brand_logo"):
                    continue
                f_ptype, f_base, f_conf = self._canonical_found_key(p, brand=brand)
                found_keys.append((f_ptype, f_base))
                if p.product_type == "promotional_graphic":
                    promos.append(p)

                # for human-readable 'found_products' list later:
                label = p.product_model or p.product_type or "unknown"
                found_lookup.append((f_ptype, f_base, label))

            # --- Matching: (ptype must match) AND (base_model equal OR base_model contained in planogram name) ---
            matched = [False] * len(expected)
            consumed = [False] * len(found_keys)
            visual_feature_scores = []  # Track visual feature matching scores

            # Greedy 1:1 matching
            for i, ek in enumerate(expected):
                for j, fk in enumerate(found_keys):
                    if matched[i] or consumed[j]:
                        continue
                    if _matches(ek, fk):
                        matched[i] = True
                        consumed[j] = True

                        # ADD VISUAL FEATURE MATCHING HERE
                        # Find the corresponding ShelfProduct and IdentifiedProduct
                        shelf_product = shelf_cfg.products[i]  # Get the shelf product config
                        identified_product = products_on_shelf[j]  # Get the identified product

                        # Calculate visual feature match score
                        if hasattr(shelf_product, 'visual_features') and shelf_product.visual_features:
                            detected_features = getattr(identified_product, 'visual_features', []) or []
                            vf_score = self._calculate_visual_feature_match(
                                shelf_product.visual_features,
                                detected_features
                            )
                            visual_feature_scores.append(vf_score)
                        break

            # Compute lists for reporting/scoring
            expected_readable = [
                f"{e_ptype}:{e_base}" if e_base else f"{e_ptype}" for (e_ptype, e_base) in expected
            ]
            found_readable = []
            for (used, (f_ptype, f_base), (_, _, original_label)) in zip(consumed, found_keys, found_lookup):
                # Keep the original label for readability but also show our canonicalization
                tag = original_label
                if f_base:
                    tag = f"{original_label} [{f_ptype}:{f_base}]"
                found_readable.append(tag)

            missing = [expected_readable[i] for i, ok in enumerate(matched) if not ok]
            # If extras not allowed, mark unexpected any unconsumed found
            unexpected = []
            if not shelf_cfg.allow_extra_products:
                for used, (f_ptype, f_base), (_, _, original_label) in zip(consumed, found_keys, found_lookup):
                    if not used:
                        lbl = original_label
                        if f_base:
                            lbl = f"{original_label} [{f_ptype}:{f_base}]"
                        unexpected.append(lbl)

            # Product score = fraction of expected matched
            basic_score = (sum(1 for ok in matched if ok) / (len(expected) or 1.0))

            # ADD VISUAL FEATURE SCORING
            visual_feature_score = 1.0
            if visual_feature_scores:
                visual_feature_score = sum(visual_feature_scores) / len(visual_feature_scores)

            text_results, text_score, overall_text_ok = [], 1.0, True

            endcap = planogram_description.advertisement_endcap
            if endcap and endcap.enabled and endcap.position == shelf_level:
                if endcap.text_requirements:
                    # Combine visual features from all promotional items
                    all_features = []
                    ocr_blocks = []
                    for promo in promos:
                        if getattr(promo, "visual_features", None):
                            all_features.extend(promo.visual_features)
                            for feat in promo.visual_features:
                                if isinstance(feat, str) and feat.startswith("ocr:"):
                                    ocr_blocks.append(feat[4:].strip())
                            # if promo have ocr_text, add that too
                            ocr_text = getattr(promo.detection_box, 'ocr_text', '')
                            if ocr_text:
                                ocr_blocks.append(ocr_text.strip())

                    if ocr_blocks:
                        ocr_norm = self._normalize_ocr_text(" ".join(ocr_blocks))
                        if ocr_norm:
                            all_features.append(ocr_norm)

                    # If no promotional graphics found but text required, create default failure
                    if not promos and shelf_level == "header":
                        self.logger.warning(
                            f"No promotional graphics found on {shelf_level} shelf but text requirements exist"
                        )
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
                        # Check text requirements against found features
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

                        # Calculate text compliance score
                        if text_results:
                            text_score = sum(r.confidence for r in text_results if r.found) / len(text_results)

            elif shelf_level != "header":
                overall_text_ok = True
                text_score = 1.0

            threshold = getattr(
                shelf_cfg, "compliance_threshold", planogram_description.global_compliance_threshold or 0.8
            )

            major_unexpected = [
                p for p in unexpected if "ink" not in p.lower() and "price tag" not in p.lower()
            ]

            # MODIFIED: Status determination logic with brand check override
            status = ComplianceStatus.NON_COMPLIANT # Default status
            if shelf_level != "header":
                if basic_score >= threshold and not major_unexpected:
                    status = ComplianceStatus.COMPLIANT
                elif basic_score == 0.0 and len(expected) > 0:
                    status = ComplianceStatus.MISSING
            else: # Header shelf logic
                # The brand check is now a mandatory condition for compliance
                if not brand_check_ok:
                    status = ComplianceStatus.NON_COMPLIANT # OVERRIDE: Brand check failed
                elif basic_score >= threshold and not major_unexpected and overall_text_ok:
                    status = ComplianceStatus.COMPLIANT
                elif basic_score == 0.0 and len(expected) > 0:
                    status = ComplianceStatus.MISSING
                else:
                    status = ComplianceStatus.NON_COMPLIANT

            # MODIFIED: Combined score calculation with visual features
            # Use the existing visual_features_weight from CategoryDetectionConfig
            visual_weight = getattr(
                planogram_description,
                'visual_features_weight',
                0.2
            )  # Default 20%

            if shelf_level == "header" and endcap:
                # Adjust product weight to make room for visual features
                adjusted_product_weight = endcap.product_weight * (1 - visual_weight)
                visual_feature_weight = endcap.product_weight * visual_weight
                combined_score = (
                    (basic_score * adjusted_product_weight) +
                    (text_score * endcap.text_weight) +
                    (brand_compliance_result.confidence * getattr(endcap, "brand_weight", 0.0)) +
                    (visual_feature_score * visual_feature_weight)
                )
            else:
                combined_score = (
                    basic_score * (1 - visual_weight) +
                    text_score * 0.1 +
                    visual_feature_score * visual_weight
                )

            # Ensure score never exceeds 1.0
            combined_score = min(1.0, max(0.0, combined_score))
            text_score = min(1.0, max(0.0, text_score))

            # Prepare human-readable outputs
            expected = expected_readable
            found = found_readable
            results.append(
                ComplianceResult(
                    shelf_level=shelf_level,
                    expected_products=expected,
                    found_products=found,
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

    def _base_model_from_str(self, s: str, brand: str = None) -> str:
        """
        Extract normalized base model from any text, supporting multiple brands.

        Args:
            s: String to extract model from
            brand: Optional brand hint to improve extraction

        Returns:
            Normalized model string or empty string if no model found
        """
        if not s:
            return ""

        t = s.lower().strip()
        # normalize separators
        t = t.replace("—", "-").replace("–", "-").replace("_", "-")

        # Brand-specific patterns
        if brand and brand.lower() == "epson":
            # EPSON EcoTank models: ET-2980, ET-3950, ET-4950
            m = re.search(r"(et)[- ]?(\d{4})", t)
            if m:
                return f"{m.group(1)}-{m.group(2)}"

        elif brand and brand.lower() == "hisense":
            # HISENSE TV models: U6, U7, U8, plus potential series numbers
            # Patterns: U7, U8, U6, 55U8, U7K, etc.
            if re.search(r"canvas[\s-]*tv", t):
                return "canvas-tv"
            if re.search(r"canvas", t):
                return "canvas"
            patterns = [
                r"(\d*)(u\d+)([a-z]*)",  # 55U8K, U7, U8K, etc.
                r"(u\d+)",               # Simple U6, U7, U8
            ]
            for pattern in patterns:
                m = re.search(pattern, t)
                if m:
                    if len(m.groups()) >= 2:
                        # Extract size + series + variant if available
                        size = m.group(1) if m.group(1) else ""
                        series = m.group(2)
                        variant = m.group(3) if len(m.groups()) > 2 and m.group(3) else ""
                        return f"{size}{series}{variant}".lower()
                    else:
                        return m.group(1).lower()

        # Generic patterns for any brand
        generic_patterns = [
            # Model with dashes: ABC-1234, XYZ-567
            r"([a-z]+)[- ]?(\d{3,4})",
            # Series patterns: U7, U8, A6, etc.
            r"([a-z]\d+)",
            # Number-letter combinations: 4950, 2980 (for fallback)
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

    def _looks_like_box(self, visual_features: list[str] | None) -> bool:
        """Heuristic: does the detection look like packaging?"""
        if not visual_features:
            return False
        keywords = {"packaging", "package", "cardboard", "box", "blue packaging", "printer image on box"}
        norm = " ".join(visual_features).lower()
        return any(k in norm for k in keywords)

    def _canonical_expected_key(self, sp: str, brand: str) -> tuple[str, str]:
        """
        From planogram product spec -> (product_type, base_model).
        Example: name='ET-4950', product_type='product_box' -> ('product_box','et-4950')
        """
        ptype = (sp.product_type or "").strip().lower()
        # Normalize product types
        type_mappings = {
            "tv_demonstration": "tv",
            "promotional_graphic": "promotional_graphic",
            "product_box": "product_box",
            "printer": "printer",
            "promotional_materials": "promotional_materials"
        }
        ptype = type_mappings.get(ptype, ptype)
        model_str = getattr(sp, "name", "") or getattr(sp, "product_model", "") or ""
        base = self._base_model_from_str(model_str, brand=brand)
        return ptype or "unknown", base or ""

    def _canonical_found_key(self, p: str, brand: str) -> tuple[str, str, float]:
        """
        From IdentifiedProduct -> (resolved_product_type, base_model, adjusted_confidence).
        If visual features scream 'box', coerce/confirm product_type as 'product_box' and boost conf a bit.
        """
        ptype = (p.product_type or "").strip().lower()
        # Normalize product types
        type_mappings = {
            "tv_demonstration": "tv",
            "promotional_graphic": "promotional_graphic",
            "product_box": "product_box",
            "printer": "printer",
            "promotional_material": "promotional_material",
            "promotional_display": "promotional_display"
        }
        ptype = type_mappings.get(ptype, ptype)
        model_str = p.product_model or p.product_type or ""
        base = self._base_model_from_str(model_str, brand=brand)
        conf = float(getattr(p, "confidence", 0.0) or 0.0)

        if self._looks_like_box(getattr(p, "visual_features", None)):
            if ptype != "product_box":
                ptype = "product_box"
            conf = min(1.0, conf + 0.05)  # gentle nudge for box evidence
        return ptype or "unknown", base or "", conf

    async def _find_poster(
        self,
        image: Image.Image,
        planogram: PlanogramDescription,
        partial_prompt: str
    ) -> tuple[Detections, Detections, Detections, Detections]:
        """
        Ask VISION Model to find the main promotional graphic for the given brand/tags.
        Returns (x1,y1,x2,y2) in absolute pixels, and the parsed JSON for logging.
        """
        brand = (getattr(planogram, "brand", "") or "").strip()
        tags = [t.strip() for t in getattr(planogram, "tags", []) or []]
        endcap = getattr(planogram, "advertisement_endcap", None)
        geometry = self.planogram_config.endcap_geometry
        if endcap and getattr(endcap, "text_requirements", None):
            for tr in endcap.text_requirements:
                if getattr(tr, "required_text", None):
                    tags.append(tr.required_text)
        tag_hint = ", ".join(sorted(set(f"'{t}'" for t in tags if t)))

        # downscale for LLM
        image_small = self._downscale_image(image, max_side=1024, quality=78)
        prompt = partial_prompt.format(
            brand=brand,
            tag_hint=tag_hint,
            image_size=image_small.size
        )
        max_attempts = 2  # Initial attempt + 1 retry
        retry_delay_seconds = 10
        msg = None
        for attempt in range(max_attempts):
            try:
                async with self.roi_client as client:
                    msg = await client.ask_to_image(
                        image=image_small,
                        prompt=prompt,
                        model="gemini-2.5-flash",
                        no_memory=True,
                        structured_output=Detections,
                        max_tokens=8192
                    )
                # If the call succeeds, break out of the loop
                break
            except ServerError as e:
                # Check if this was the last attempt
                if attempt < max_attempts - 1:
                    print(
                        f"WARNING: Model is overloaded. Retrying in {retry_delay_seconds} seconds... (Attempt {attempt + 1}/{max_attempts})"
                    )
                    await asyncio.sleep(retry_delay_seconds)
                else:
                    print(
                        f"ERROR: Model is still overloaded after {max_attempts} attempts. Failing."
                    )
                    # Re-raise the exception if the last attempt fails
                    raise e
        # Evaluate the Output:
        # print('MSG >> ', msg)
        # print('OUTPUT > ', msg.output)
        data = msg.structured_output or msg.output or {}
        dets = data.detections or []
        if not dets:
            return None, data
        # pick detections
        panel_det = next(
            (d for d in dets if d.label == "poster_panel"), None) \
            or next((d for d in dets if d.label == "poster"), None) \
            or (max(dets, key=lambda x: float(x.confidence)) if dets else None
        )
        # poster text:
        text_det = next((d for d in dets if d.label == "poster_text"), None)
        # brand logo:
        brand_det = next((d for d in dets if d.label == "brand_logo"), None)
        if not panel_det:
            self.logger.error("Critical failure: Could not detect the poster_panel.")
            return None, None, None, None

        # promotional graphic (inside the panel):
        promo_graphic_det = next(
            (d for d in dets if d.label == "promotional_graphic"), None
        )

        # check if promo_graphic is contained by panel_det, if not, increase the panel:
        if promo_graphic_det and panel_det:
            # If promo graphic is outside panel, expand panel to include it
            if not (
                promo_graphic_det.bbox.x1 >= panel_det.bbox.x1 and
                promo_graphic_det.bbox.x2 <= panel_det.bbox.x2
            ):
                self.logger.info("Expanding poster_panel to include promotional_graphic.")
                panel_det.bbox.x1 = min(panel_det.bbox.x1, promo_graphic_det.bbox.x1)
                panel_det.bbox.x2 = max(panel_det.bbox.x2, promo_graphic_det.bbox.x2)

        # Get planogram advertisement config with safe defaults
        advertisement_config = getattr(planogram, "advertisement_endcap", {})
        # # Default values if not in planogram, normalized to image (not ROI)
        # config_width_percent = advertisement_config.width_margin_percent
        # config_height_percent = advertisement_config.height_margin_percent
        # config_top_margin_percent = advertisement_config.top_margin_percent
        # # E.g., 5% of panel width
        # side_margin_percent = advertisement_config.side_margin_percent

        config_width_percent = geometry.width_margin_percent
        config_height_percent = geometry.height_margin_percent
        config_top_margin_percent = geometry.top_margin_percent
        side_margin_percent = geometry.side_margin_percent

        # --- Refined Panel Padding ---
        # Apply padding to the panel_det itself to ensure it captures the full visual area
        panel_det.bbox.x1 = max(0.0, panel_det.bbox.x1 - side_margin_percent)
        panel_det.bbox.x2 = min(1.0, panel_det.bbox.x2 + side_margin_percent)

        if panel_det and text_det:
            text_bottom_y2 = text_det.bbox.y2
            padding = 0.08
            new_panel_y2 = min(text_bottom_y2 + padding, 1.0)
            panel_det.bbox.y2 = new_panel_y2

        # --- endcap Detected:
        endcap_det = next((d for d in dets if d.label == "endcap"), None)

        # panel
        px1, py1, px2, py2 = panel_det.bbox.x1, panel_det.bbox.y1, panel_det.bbox.x2, panel_det.bbox.y2

        # Initial endcap box: Use the LLM's endcap detection if it exists, otherwise fall back to the panel
        if endcap_det:
            ex1, ey1, ex2, ey2 = endcap_det.bbox.x1, endcap_det.bbox.y1, endcap_det.bbox.x2, endcap_det.bbox.y2
        else:
            ex1, ey1, ex2, ey2 = px1, py1, px2, py2

        if endcap_det is None:
            panel_h = py2 - py1
            ratio = max(1e-6, float(config_height_percent))
            top_margin = float(config_top_margin_percent)
            ey1 = max(0.0, py1 - top_margin)
            ey2 = min(1.0, ey1 + panel_h / ratio)

        x_buffer = max(self.left_margin_ratio * (px2-px1), self.right_margin_ratio * (px2-px1))
        ex1 = min(ex1, px1 - x_buffer)
        ex2 = max(ex2, px2 + x_buffer)

        # Clamp & monotonic
        ex1 = max(0.0, ex1)
        ex2 = min(1.0, ex2)
        if ex2 <= ex1:
            ex2 = ex1 + 1e-6
        ey1 = max(0.0, ey1)
        ey2 = min(1.0, ey2)
        if ey2 <= ey1:
            ey2 = ey1 + 1e-6

        # Update the endcap_det bbox with the corrected values
        if endcap_det is None:
            endcap_det = DetectionBox(
                x1=ex1, y1=ey1, x2=ex2, y2=ey2,
                confidence=0.9, # Assign a default confidence
                label="endcap"
            )
        else:
            endcap_det.bbox.x1 = ex1
            endcap_det.bbox.x2 = ex2
            endcap_det.bbox.y1 = ey1
            endcap_det.bbox.y2 = ey2

        return endcap_det, panel_det, brand_det, text_det, dets

    # Complete Pipeline
    async def run(
        self,
        image: Union[str, Path, Image.Image],
        debug_raw="/tmp/data/yolo_raw_debug.png",
        return_overlay: Optional[str] = None,  # "identified" | "detections" | "both" | None
        overlay_save_path: Optional[Union[str, Path]] = None,
    ) -> Dict[str, Any]:
        """
        Run the complete 3-step planogram compliance pipeline

        Returns:
            Complete analysis results including all steps
        """
        self.logger.debug("Step 1: Find Region of Interest...")
        # Optimize Image for Classification:
        img = self.open_image(image)

        # ROI detection:
        img_array = np.array(img)  # RGB

        # 1) Find the poster:
        planogram_description = self.planogram_config.get_planogram_description()
        endcap, ad, brand, panel_text, dets = await self._find_poster(
            img,
            planogram_description,
            partial_prompt=self.planogram_config.roi_detection_prompt
        )
        if return_overlay == 'detections' or return_overlay == 'both':
            debug_poster_path = debug_raw.replace(".png", "_poster_debug.png") if debug_raw else None
            panel_px = ad.bbox.get_coordinates()
            self._save_detections(
                image, panel_px, dets, debug_poster_path
            )
        # Check if detections are valid before proceeding
        if not endcap or not ad:
            print("ERROR: Failed to get required detections.")
            return # or raise an exception

        # Locate Shelves and Objects:
        shelf_regions, detections = await self.detect_objects_and_shelves(
            image,
            img_array,
            endcap=endcap,
            ad=ad,
            brand=brand,
            panel_text=panel_text,
            planogram_description=planogram_description
        )

        self.logger.debug(
            f"Found {len(detections)} objects in {len(shelf_regions)} shelf regions"
        )

        self.logger.notice("Step 2: Identifying objects with LLM...")
        identified_products = await self.identify_objects_with_references(
            image,
            detections,
            shelf_regions,
            self.reference_images,
            prompt=self.planogram_config.object_identification_prompt
        )

        self.logger.debug(
            f"Identified Products: {identified_products}"
        )

        compliance_results = self.check_planogram_compliance(
            identified_products, planogram_description
        )

        # Calculate overall compliance
        total_score = sum(
            r.compliance_score for r in compliance_results
        ) / len(compliance_results) if compliance_results else 0.0
        if total_score >= (planogram_description.global_compliance_threshold or 0.8):
            overall_compliant = True
        else:
            overall_compliant = all(
                r.compliance_status == ComplianceStatus.COMPLIANT for r in compliance_results
            )
        overlay_image = None
        overlay_path = None
        if return_overlay == 'identified' or return_overlay == 'both':
            try:
                overlay_image = self.render_evaluated_image(
                    image,
                    shelf_regions=shelf_regions,
                    detections=detections,
                    identified_products=identified_products,
                    mode=return_overlay,
                    show_shelves=True,
                    save_to=overlay_save_path,
                )
                if overlay_save_path:
                    overlay_path = str(Path(overlay_save_path))
            except Exception as e:
                self.logger.error(f"Failed to render overlay image: {e}")
                # is not mandatory to fail the whole pipeline
                overlay_image = None
                overlay_path = None

        return {
            "step1_detections": detections,
            "step1_shelf_regions": shelf_regions,
            "step2_identified_products": identified_products,
            "step3_compliance_results": compliance_results,
            "overall_compliance_score": total_score,
            "overall_compliant": overall_compliant,
            "analysis_timestamp": datetime.now(),
            "overlay_image": overlay_image,
            "overlay_path": overlay_path,
        }

    def render_evaluated_image(
        self,
        image: Union[str, Path, Image.Image],
        *,
        shelf_regions: Optional[List[ShelfRegion]] = None,
        detections: Optional[List[DetectionBox]] = None,
        identified_products: Optional[List[IdentifiedProduct]] = None,
        mode: str = "identified",
        show_shelves: bool = True,
        save_to: Optional[Union[str, Path]] = None,
    ) -> Image.Image:
        """
        Enhanced render with safe coordinate handling
        """
        def _norm_box(x1, y1, x2, y2):
            """Normalize box coordinates to ensure valid rectangle"""
            x1, x2 = int(x1), int(x2)
            y1, y2 = int(y1), int(y2)

            # Ensure coordinates are in correct order
            if x1 > x2:
                x1, x2 = x2, x1
            if y1 > y2:
                y1, y2 = y2, y1

            # Ensure minimum size
            if x2 - x1 < 1:
                x2 = x1 + 1
            if y2 - y1 < 1:
                y2 = y1 + 1

            return x1, y1, x2, y2

        # Get base image
        if isinstance(image, (str, Path)):
            base = Image.open(image).convert("RGB").copy()
        else:
            base = image.convert("RGB").copy()

        draw = ImageDraw.Draw(base)
        try:
            font = ImageFont.load_default()
        except Exception:
            font = None

        W, H = base.size

        def _clip(x1, y1, x2, y2):
            """Clip coordinates to image bounds"""
            return max(0, x1), max(0, y1), min(W-1, x2), min(H-1, y2)

        def _txt(draw_obj, xy, text, fill, bg=None):
            """Safe text drawing with error handling"""
            try:
                if not font:
                    draw_obj.text(xy, text, fill=fill)
                    return
                bbox = draw_obj.textbbox(xy, text, font=font)
                if bg is not None:
                    draw_obj.rectangle(bbox, fill=bg)
                draw_obj.text(xy, text, fill=fill, font=font)
            except Exception:
                # Fallback to simple text if there's any error
                try:
                    draw_obj.text(xy, text, fill=fill)
                except Exception:
                    pass  # Skip this text if it still fails

        # Colors per product type
        colors = {
            "tv_demonstration": (0, 255, 0),      # green for TVs
            "promotional_graphic": (255, 0, 255), # magenta for logos
            "promotional_base": (0, 0, 255),      # blue for partner branding
            "fact_tag": (255, 255, 0),            # yellow for info displays
            "product_box": (255, 128, 0),         # orange
            "printer": (255, 0, 0),               # red
            "unknown": (200, 200, 200),           # gray
        }

        # Draw shelves
        if show_shelves and shelf_regions:
            for sr in shelf_regions:
                try:
                    x1, y1, x2, y2 = _clip(sr.bbox.x1, sr.bbox.y1, sr.bbox.x2, sr.bbox.y2)
                    x1, y1, x2, y2 = _norm_box(x1, y1, x2, y2)
                    draw.rectangle([x1, y1, x2, y2], outline=(255, 255, 0), width=3)
                    _txt(draw, (x1+3, max(0, y1-14)), f"SHELF {sr.level}", fill=(0, 0, 0), bg=(255, 255, 0))
                except Exception as e:
                    print(f"Warning: Could not draw shelf {sr.level}: {e}")

        # Draw detections (thin)
        if mode in ("detections", "both") and detections:
            for i, d in enumerate(detections, start=1):
                try:
                    x1, y1, x2, y2 = _clip(d.x1, d.y1, d.x2, d.y2)
                    x1, y1, x2, y2 = _norm_box(x1, y1, x2, y2)
                    draw.rectangle([x1, y1, x2, y2], outline=(255, 0, 0), width=2)
                    lbl = f"ID:{i} {d.class_name} {d.confidence:.2f}"
                    _txt(draw, (x1+2, max(0, y1-12)), lbl, fill=(0, 0, 0), bg=(255, 0, 0))
                except Exception as e:
                    print(f"Warning: Could not draw detection {i}: {e}")

        # Draw identified products (thick)
        if mode in ("identified", "both") and identified_products:
            for p in sorted(identified_products, key=lambda x: (x.detection_box.area if x.detection_box else 0), reverse=True):
                if not p.detection_box:
                    continue
                try:
                    x1, y1, x2, y2 = _clip(p.detection_box.x1, p.detection_box.y1, p.detection_box.x2, p.detection_box.y2)
                    x1, y1, x2, y2 = _norm_box(x1, y1, x2, y2)

                    c = colors.get(p.product_type, (255, 0, 255))
                    draw.rectangle([x1, y1, x2, y2], outline=c, width=5)

                    # Label
                    pid = p.detection_id if p.detection_id is not None else "NEW"
                    mm = f" {p.product_model}" if p.product_model else ""
                    lab = f"#{pid} {p.product_type}{mm} ({p.confidence:.2f})"
                    _txt(draw, (x1+3, max(0, y1-14)), lab, fill=(0, 0, 0), bg=c)

                except Exception as e:
                    print(f"Warning: Could not draw product {p.product_model}: {e}")

        # Add legend
        legend_y = 8
        for key in ("tv_demonstration", "promotional_graphic", "promotional_base", "fact_tag"):
            if key in colors:
                try:
                    c = colors[key]
                    draw.rectangle([8, legend_y, 28, legend_y+10], fill=c)
                    _txt(draw, (34, legend_y-2), key, fill=(255,255,255))
                    legend_y += 14
                except Exception:
                    pass

        # Save if requested
        if save_to:
            try:
                save_to = Path(save_to)
                save_to.parent.mkdir(parents=True, exist_ok=True)
                base.save(save_to, quality=90)
                print(f"Overlay saved to: {save_to}")
            except Exception as e:
                print(f"Warning: Could not save overlay: {e}")

        return base

    def generate_compliance_json(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate comprehensive JSON report from pipeline results.

        Args:
            results: Complete results object from pipeline.run()

        Returns:
            Dictionary containing comprehensive compliance report
        """
        compliance_results = results['step3_compliance_results']

        def serialize_compliance_result(result) -> Dict[str, Any]:
            """Convert ComplianceResult to serializable dictionary."""
            result_dict = {
                "shelf_level": result.shelf_level,
                "compliance_status": result.compliance_status.value,
                "compliance_score": round(result.compliance_score, 3),
                "expected_products": result.expected_products,
                "found_products": result.found_products,
                "missing_products": result.missing_products,
                "unexpected_products": result.unexpected_products,
                "text_compliance": {
                    "score": round(result.text_compliance_score, 3),
                    "overall_compliant": result.overall_text_compliant,
                    "requirements": []
                }
            }

            # Add text compliance details
            for text_result in result.text_compliance_results:
                text_dict = {
                    "required_text": text_result.required_text,
                    "found": text_result.found,
                    "confidence": round(text_result.confidence, 3),
                    "match_type": text_result.match_type,
                    "matched_features": text_result.matched_features
                }
                result_dict["text_compliance"]["requirements"].append(text_dict)

            # Add brand compliance if present
            if hasattr(result, 'brand_compliance_result') and result.brand_compliance_result:
                result_dict["brand_compliance"] = {
                    "expected_brand": result.brand_compliance_result.expected_brand,
                    "found_brand": result.brand_compliance_result.found_brand,
                    "found": result.brand_compliance_result.found,
                    "confidence": round(result.brand_compliance_result.confidence, 3)
                }

            return result_dict

        # Build the main report structure
        report = {
            "metadata": {
                "analysis_timestamp": results['analysis_timestamp'].isoformat(),
                "report_version": "1.0",
                "total_shelves_analyzed": len(compliance_results)
            },
            "overall_compliance": {
                "compliant": results['overall_compliant'],
                "score": round(results['overall_compliance_score'], 3),
                "percentage": f"{results['overall_compliance_score']:.1%}"
            },
            "shelf_results": [serialize_compliance_result(result) for result in compliance_results],
            "summary": {
                "compliant_shelves": sum(1 for r in compliance_results if r.compliance_status.value == "compliant"),
                "non_compliant_shelves": sum(1 for r in compliance_results if r.compliance_status.value == "non_compliant"),
                "missing_shelves": sum(1 for r in compliance_results if r.compliance_status.value == "missing"),
                "average_shelf_score": round(sum(r.compliance_score for r in compliance_results) / len(compliance_results), 3) if compliance_results else 0.0
            }
        }

        # Add overlay path if provided
        if 'overlay_path' in results and results['overlay_path']:
            report["artifacts"] = {
                "overlay_image_path": str(results['overlay_path'])
            }

        return report

    def generate_compliance_markdown(
        self,
        results: Dict[str, Any],
        brand_name: Optional[str] = None,
        additional_notes: Optional[str] = None
    ) -> str:
        """
        Generate comprehensive Markdown report from pipeline results.

        Args:
            results: Complete results object from pipeline.run()
            brand_name: Brand being analyzed (optional)
            additional_notes: Additional notes to include (optional)

        Returns:
            Formatted Markdown string
        """
        compliance_results = results['step3_compliance_results']
        overall_compliance_score = results['overall_compliance_score']
        overall_compliant = results['overall_compliant']
        analysis_timestamp = results['analysis_timestamp']
        overlay_path = results.get('overlay_path')

        def status_emoji(status: str) -> str:
            """Get emoji for compliance status."""
            status_map = {
                "compliant": "✅",
                "non_compliant": "❌",
                "missing": "⚠️",
                "misplaced": "🔄"
            }
            return status_map.get(status, "❓")

        def format_percentage(score: float) -> str:
            """Format score as percentage."""
            return f"{score:.1%}"

        # Start building the markdown
        lines = []

        # Header
        brand_title = f" - {brand_name}" if brand_name else ""
        lines.append(f"# Planogram Compliance Report{brand_title}")
        lines.append("")
        lines.append(
            f"**Analysis Date:** {analysis_timestamp.strftime('%Y-%m-%d %H:%M:%S')}"
        )
        lines.append("")

        # Overall Compliance Section
        overall_emoji = "✅" if overall_compliant else "❌"
        lines.append("## Overall Compliance")
        lines.append("")
        lines.append(f"**Status:** {overall_emoji} {'COMPLIANT' if overall_compliant else 'NON-COMPLIANT'}")
        lines.append(f"**Score:** {format_percentage(overall_compliance_score)}")
        lines.append("")

        # Summary Statistics
        compliant_count = sum(1 for r in compliance_results if r.compliance_status.value == "compliant")
        total_count = len(compliance_results)

        lines.append("## Summary")
        lines.append("")
        lines.append(f"- **Total Shelves:** {total_count}")
        lines.append(f"- **Compliant Shelves:** {compliant_count}/{total_count}")
        lines.append(f"- **Non-Compliant Shelves:** {total_count - compliant_count}/{total_count}")

        if compliance_results:
            avg_score = sum(r.compliance_score for r in compliance_results) / len(compliance_results)
            lines.append(f"- **Average Shelf Score:** {format_percentage(avg_score)}")
        lines.append("")

        # Detailed Shelf Results
        lines.append("## Detailed Results by Shelf")
        lines.append("")

        for result in compliance_results:
            shelf_emoji = status_emoji(result.compliance_status.value)
            lines.append(f"### {result.shelf_level.upper().replace('_', ' ')}")
            lines.append("")
            lines.append(f"**Status:** {shelf_emoji} {result.compliance_status.value.upper()}")
            lines.append(f"**Score:** {format_percentage(result.compliance_score)}")
            lines.append("")

            # Products
            lines.append("**Expected Products:**")
            for product in result.expected_products:
                lines.append(f"- {product}")
            lines.append("")

            lines.append("**Found Products:**")
            if result.found_products:
                for product in result.found_products:
                    lines.append(f"- {product}")
            else:
                lines.append("- *(None)*")
            lines.append("")

            # Missing/Unexpected
            if result.missing_products:
                lines.append("**Missing Products:**")
                for product in result.missing_products:
                    lines.append(f"- ❌ {product}")
                lines.append("")

            if result.unexpected_products:
                lines.append("**Unexpected Products:**")
                for product in result.unexpected_products:
                    lines.append(f"- ⚠️ {product}")
                lines.append("")

            # Text Compliance
            if result.text_compliance_results:
                text_emoji = "✅" if result.overall_text_compliant else "❌"
                lines.append(f"**Text Compliance:** {text_emoji} {format_percentage(result.text_compliance_score)}")
                lines.append("")

                for text_result in result.text_compliance_results:
                    req_emoji = "✅" if text_result.found else "❌"
                    lines.append(f"- {req_emoji} '{text_result.required_text}' (confidence: {text_result.confidence:.2f})")
                    if text_result.matched_features:
                        lines.append(f"  - Matched: {', '.join(text_result.matched_features)}")
                lines.append("")

            # Brand Compliance - only show on promotional graphic shelves
            if (hasattr(result, 'brand_compliance_result') and
                result.brand_compliance_result and
                'promotional_graphic' in str(result.expected_products).lower()):
                brand_emoji = "✅" if result.brand_compliance_result.found else "❌"
                lines.append(f"**Brand Compliance:** {brand_emoji}")
                lines.append(f"- Expected: {result.brand_compliance_result.expected_brand}")
                if result.brand_compliance_result.found_brand:
                    lines.append(f"- Found: {result.brand_compliance_result.found_brand}")
                    lines.append(f"- Confidence: {result.brand_compliance_result.confidence:.2f}")
                else:
                    lines.append("- Found: *(None)*")
                lines.append("")

            lines.append("---")
            lines.append("")

        # Artifacts Section
        if overlay_path:
            lines.append("## Analysis Artifacts")
            lines.append("")
            lines.append(f"**Overlay Image:** `{overlay_path}`")
            lines.append("")

            # Add image link if it's a web-accessible path
            if str(overlay_path).startswith(('http://', 'https://')):
                lines.append(f"![Compliance Overlay]({overlay_path})")
            lines.append("")

        # Additional Notes
        if additional_notes:
            lines.append("## Additional Notes")
            lines.append("")
            lines.append(additional_notes)
            lines.append("")

        # Footer
        lines.append("---")
        lines.append("*Report generated by AI-Parrot Planogram Compliance Pipeline*")

        return '\n'.join(lines)
