"""
3-Step Planogram Compliance Pipeline
Step 1: Object Detection (YOLO/ResNet)
Step 2: LLM Object Identification with Reference Images
Step 3: Planogram Comparison and Compliance Verification
"""
import os
from typing import List, Dict, Any, Optional, Union, Tuple
from collections import defaultdict
import re
import traceback
from pathlib import Path
from datetime import datetime
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
from transformers import CLIPProcessor, CLIPModel
from .abstract import AbstractPipeline
from ..models.detections import (
    DetectionBox,
    ShelfRegion,
    IdentifiedProduct,
    PlanogramDescription,
    PlanogramDescriptionFactory,
)
from ..models.compliance import (
    ComplianceResult,
    ComplianceStatus,
    TextComplianceResult,
    TextMatcher,
)
try:
    from ultralytics import YOLO  # yolo12m works with this API
except Exception:
    YOLO = None

CID = {
    "promotional_candidate": 103,
    "product_candidate":     100,
    "box_candidate":         101,
    "shelf_region":          190,
}


def _clamp(W,H,x1,y1,x2,y2):
    x1,x2 = int(max(0,min(W-1,min(x1,x2)))), int(max(0,min(W-1,max(x1,x2))))
    y1,y2 = int(max(0,min(H-1,min(y1,y2)))), int(max(0,min(H-1,max(y1,y2))))
    return x1, y1, x2, y2

class IdentificationResponse(BaseModel):
    """Response model for product identification"""
    identified_products: List[IdentifiedProduct] = Field(
        alias="detections",
        description="List of identified products from the image"
    )


class RetailDetector:
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
    ):
        if isinstance(yolo_model, str):
            assert YOLO is not None, "ultralytics is required"
            self.yolo = YOLO(yolo_model)
        else:
            self.yolo = yolo_model
        self.conf = conf
        self.iou = iou
        self.device = device

        # CLIP for open-vocab and ref matching
        self.clip = CLIPModel.from_pretrained("openai/clip-vit-base-patch32").to(device)
        self.proc = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")

        self.ref_paths = reference_images or []
        self.ref_ad = self.ref_paths[0] if self.ref_paths else None
        self.ref_products = self.ref_paths[1:] if len(self.ref_paths) > 1 else []

        self.ref_ad_feat = self._embed_image(self.ref_ad) if self.ref_ad else None
        self.ref_prod_feats = [self._embed_image(p) for p in self.ref_products] if self.ref_products else []

        # text prompts (backup if no product refs)
        self.text_tokens = self.proc(text=[
            "retail promotional poster lightbox",
            "Epson EcoTank printer device on shelf",
            "printer product box carton"
        ], return_tensors="pt", padding=True).to(self.device)
        with torch.no_grad():
            self.text_feats = self.clip.get_text_features(**self.text_tokens)
            self.text_feats = self.text_feats / self.text_feats.norm(dim=-1, keepdim=True)

    def _iou(self, a: DetectionBox, b: DetectionBox) -> float:
        ix1, iy1 = max(a.x1, b.x1), max(a.y1, b.y1)
        ix2, iy2 = min(a.x2, b.x2), min(a.y2, b.y2)
        iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
        inter = iw * ih
        if inter <= 0:
            return 0.0
        ua = a.area + b.area - inter
        return inter / float(max(1, ua))

    def _iou_box_tuple(self, d: "DetectionBox", box: tuple[int,int,int,int]) -> float:
        ax1, ay1, ax2, ay2 = box
        ix1, iy1 = max(d.x1, ax1), max(d.y1, ay1)
        ix2, iy2 = min(d.x2, ax2), min(d.y2, ay2)
        if ix2 <= ix1 or iy2 <= iy1:
            return 0.0
        inter = (ix2 - ix1) * (iy2 - iy1)
        return inter / float(d.area + (ax2-ax1)*(ay2-ay1) - inter + 1e-6)

    def _pick_main_promo(self, promos: list[DetectionBox], ad_box: tuple[int,int,int,int] | None):
        """Return a single promo box; prefer the largest union of overlapping boxes.
        If none, synthesize from ad_box. Also return the chosen (x1,y1,x2,y2) for ROI."""
        merged = promos[:]
        # if we also have an external ad_box, turn it into a promo candidate for voting
        if ad_box is not None:
            ax1, ay1, ax2, ay2 = ad_box
            merged.append(
                DetectionBox(
                    x1=ax1, y1=ay1, x2=ax2, y2=ay2,
                    confidence=0.95,
                    class_id=CID["promotional_candidate"],
                    class_name="promotional_candidate",
                    area=(ax2-ax1)*(ay2-ay1)
                )
            )

        if not merged:
            return None, None

        # cluster overlapping promos (IoU >= 0.5), keep the largest in each cluster
        merged.sort(key=lambda d: d.area, reverse=True)
        clusters: list[list[DetectionBox]] = []
        for d in merged:
            placed = False
            for cl in clusters:
                if any(self._iou(d, e) >= 0.5 for e in cl):
                    cl.append(d)
                    placed = True
                    break
            if not placed:
                clusters.append([d])

        # pick cluster with largest total area, then pick its largest member
        best_cluster = max(clusters, key=lambda cl: sum(x.area for x in cl))
        main = max(best_cluster, key=lambda d: d.area)
        roi = (main.x1, main.y1, main.x2, main.y2)
        return main, roi

    def _consolidate_promos(
        self,
        dets: List["DetectionBox"],
        ad_box: Optional[tuple[int,int,int,int]],
    ) -> tuple[List["DetectionBox"], Optional[tuple[int,int,int,int]]]:
        """Keep a single promotional candidate, remove the rest.
        If none, synthesize one from ad_box.
        """
        promos = [d for d in dets if d.class_name == "promotional_candidate"]
        keep = [d for d in dets if d.class_name != "promotional_candidate"]

        # if YOLO didn’t produce a promo, synthesize one from ad_box
        if not promos and ad_box:
            x1, y1, x2, y2 = ad_box
            promos = [
                DetectionBox(
                    x1=x1, y1=y1, x2=x2, y2=y2,
                    confidence=0.95,
                    class_id=103,
                    class_name="promotional_candidate",
                    area=(x2-x1)*(y2-y1)
                )
            ]

        if not promos:
            return keep, ad_box

        # cluster by IoU and keep the biggest in the biggest cluster
        promos = sorted(promos, key=lambda d: d.area, reverse=True)
        clusters: list[list["DetectionBox"]] = []
        for d in promos:
            placed = False
            for cl in clusters:
                if any(self._iou(d, e) >= 0.5 for e in cl):
                    cl.append(d); placed = True; break
            if not placed:
                clusters.append([d])
        best_cluster = max(clusters, key=lambda cl: sum(x.area for x in cl))
        main = max(best_cluster, key=lambda d: d.area)
        keep.append(main)
        return keep, (main.x1, main.y1, main.x2, main.y2)

    # -------------------------- public entry ---------------------------------
    def detect(
        self,
        image: Image.Image,
        debug_raw: Optional[str] = None,
        debug_phase1: Optional[str] = None,
    ):
        # 0) PIL -> enhanced -> numpy
        pil = image.convert("RGB") if isinstance(image, Image.Image) else Image.open(image).convert("RGB")
        enhanced = self._enhance(pil)
        img_array = np.array(enhanced)  # RGB
        h, w = img_array.shape[:2]

        # 1) find promo (OCR + CLIP + fallbacks)
        ad_box = self._find_poster(img_array)

        # 2) endcap ROI from promo width (+ margin)
        roi_box = self._roi_from_poster(ad_box, h, w)
        rx1, ry1, rx2, ry2 = roi_box
        roi = img_array[ry1:ry2, rx1:rx2]

        # 3) shelf lines & 3 bands (top/middle/bottom) in full-image coords
        shelf_lines, bands = self._find_shelves(roi, rx1, ry1, rx2, ry2, h)
        header_limit_y = min(v[0] for v in bands.values()) if bands else int(0.4 * h)

        # 4) YOLO proposals inside ROI (class-agnostic)
        yolo_props = self._yolo_props(roi, rx1, ry1)
        if debug_raw:
            dbg = self._draw_yolo(img_array.copy(), yolo_props, roi_box, shelf_lines)
            cv2.imwrite(debug_raw, cv2.cvtColor(dbg, cv2.COLOR_RGB2BGR))

        # 5) classify proposals -> product_candidate / box_candidate / promotional_candidate
        proposals = self._classify_proposals(img_array, yolo_props, bands, header_limit_y, ad_box)

        if "top" in bands:
            top_y1, top_y2 = bands["top"]
            top_box = DetectionBox(x1=rx1, y1=top_y1, x2=rx2, y2=top_y2,
                                confidence=1.0, class_id=190, class_name="shelf_region",
                                area=(rx2-rx1)*(top_y2-top_y1))
            already_top = [d for d in proposals
                        if d.class_name == "product_candidate" and (d.y1 + d.y2) / 2 < top_y2]
            if len(already_top) < 3:              # only help when YOLO under-detects
                fallback_devs = self._fallback_top_devices(img_array, top_box)
                if fallback_devs:
                    proposals.extend(fallback_devs)

        # 6) shrink -> merge -> remove those fully inside the poster
        proposals = self._shrink(img_array, proposals)
        proposals = self._merge(proposals, iou_same=0.45)
        proposals = self._suppress_inside_poster(proposals, ad_box)

        # 7) keep exactly ONE promo & align ROI to it
        proposals, promo_roi = self._consolidate_promos(proposals, ad_box)
        if promo_roi is not None:
            ad_box = promo_roi

        # shelves as DetectionBox regions (dict keyed by name)
        shelves = {
            name: DetectionBox(
                x1=rx1, y1=y1, x2=rx2, y2=y2,
                confidence=1.0,
                class_id=190,
                class_name="shelf_region",
                area=(rx2-rx1)*(y2-y1),
            )
            for name, (y1, y2) in bands.items()
        }

        # (OPTIONAL) draw Phase-1 debug
        if debug_phase1:
            dbg = self._draw_phase1(img_array.copy(), roi_box, shelf_lines, proposals, ad_box)
            cv2.imwrite(
                debug_phase1,
                cv2.cvtColor(dbg, cv2.COLOR_RGB2BGR)
            )

        # 8) ensure the promo exists exactly once (don’t re-add if already merged)
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

    # ----------------------- enhancement & CLIP -------------------------------
    def _enhance(self, pil_img: "Image.Image") -> "Image.Image":
        """Enhance a PIL image and return PIL."""
        # Brightness/contrast + autocontrast; tweak if needed
        pil = ImageEnhance.Brightness(pil_img).enhance(1.10)
        pil = ImageEnhance.Contrast(pil).enhance(1.20)
        pil = ImageOps.autocontrast(pil)
        return pil

    def _embed_image(self, path: Optional[str]):
        if not path:
            return None
        im = Image.open(path).convert("RGB")
        with torch.no_grad():
            inputs = self.proc(images=im, return_tensors="pt").to(self.device)
            feat = self.clip.get_image_features(**inputs)
            feat = feat / feat.norm(dim=-1, keepdim=True)
        return feat

    # ---------------------- poster localization -------------------------------
    def _find_poster(self, img: np.ndarray) -> Optional[Tuple[int,int,int,int]]:
        """
        Find the entire endcap display area, not just the poster text
        """
        H, W = img.shape[:2]

        # 1) Look for the main promotional display using OCR
        data = pytesseract.image_to_data(Image.fromarray(img), output_type=pytesseract.Output.DICT)
        xs, ys, xe, ye = [], [], [], []

        for i, word in enumerate(data.get("text", [])):
            if not word:
                continue
            w = word.lower()

            # Target keywords for Epson displays
            if any(k in w for k in ("epson","hello","savings","cartridges","ecotank","goodbye")):
                x, y = data["left"][i], data["top"][i]
                bw, bh = data["width"][i], data["height"][i]

                # FILTER: Ignore text found in the leftmost 15% (Microsoft signage)
                if x < 0.15 * W:
                    continue

                # FILTER: Focus on upper portion (promotional graphics)
                if y > 0.5 * H:  # Skip text too low
                    continue

                xs.append(x)
                ys.append(y)
                xe.append(x+bw)
                ye.append(y+bh)

        # If we found promotional text, use it as anchor for the full display area
        if xs:
            text_x1, text_y1, text_x2, text_y2 = min(xs), min(ys), max(xe), max(ye)

            # STRATEGY: Use the promotional text as center point, but expand to capture full endcap
            # The endcap display typically spans from edge to edge of the visible product area

            # Find the actual product display boundaries by looking for the white shelf/products
            display_x1 = int(0.12 * W)  # Start after Microsoft signage
            display_x2 = int(0.92 * W)  # Go nearly to edge but leave some margin

            # Vertical: Start from promotional area, go to bottom
            display_y1 = max(0, int(text_y1 - 0.05 * H))  # Slightly above promotional text
            display_y2 = H - 1  # Go to bottom

            return _clamp(W, H, display_x1, display_y1, display_x2, display_y2)

        # 2) CLIP approach as backup
        if self.ref_ad_feat is not None:
            windows = []
            ww, hh = int(0.6 * W), int(0.35 * H)  # Larger windows to capture more

            # Sample wider area to find promotional content
            for cx in (int(0.35 * W), int(0.5 * W), int(0.65 * W)):
                for cy in (int(0.25 * H), int(0.35 * H)):
                    x1 = max(0, cx - ww // 2)
                    x2 = min(W - 1, x1 + ww)
                    y1 = max(0, cy - hh // 2)
                    y2 = min(H - 1, y1 + hh)
                    windows.append((x1, y1, x2, y2))

            best = None
            best_s = -1.0

            for (x1, y1, x2, y2) in windows:
                crop = Image.fromarray(img[y1:y2, x1:x2])
                with torch.no_grad():
                    ip = self.proc(images=crop, return_tensors="pt").to(self.device)
                    f = self.clip.get_image_features(**ip)
                    f = f / f.norm(dim=-1, keepdim=True)
                    s = float((f @ self.ref_ad_feat.T).squeeze())
                if s > best_s:
                    best_s = s
                    best = (x1, y1, x2, y2)

            if best is not None and best_s > 0.12:
                # Use CLIP result as center, but expand to full display width
                _, by1, _, by2 = best
                display_x1 = int(0.12 * W)
                display_x2 = int(0.92 * W)
                return _clamp(W, H, display_x1, by1, display_x2, H - 1)

        # 3) Fallback: Define the full endcap display area
        return (
            int(0.12 * W),  # Start after left-side signage
            int(0.12 * H),  # Start from upper area
            int(0.92 * W),  # Go nearly to right edge
            H - 1           # Go to bottom
        )

    def _roi_from_poster(self, ad_box, h, w):
        """
        Create focused ROI with reduced margins
        """
        # Tighter horizontal bounds - reduce by ~5-10% on each side
        rx1 = int(0.15 * w)   # Move right edge in (was 0.08)
        rx2 = int(0.88 * w)   # Move left edge in (was 0.95)

        # Vertical: Start from promotional area, go to bottom
        if ad_box is not None:
            # Use promotional area as top reference
            _, y1, _, _ = ad_box
            ry1 = max(0, int(y1 - 0.03 * h))  # Start slightly above promotional area
        else:
            # Fallback: start from upper portion
            ry1 = int(0.08 * h)

        ry2 = h - 1  # Always go to bottom to capture all shelves

        return (rx1, ry1, rx2, ry2)

    def _find_shelves(self, roi: np.ndarray, rx1, ry1, rx2, ry2, H):
        """
        IMPROVED: More robust shelf line detection
        """
        g = cv2.cvtColor(roi, cv2.COLOR_RGB2GRAY)

        # Enhanced edge detection
        g = cv2.GaussianBlur(g, (3, 3), 0)
        e = cv2.Canny(g, 40, 120, apertureSize=3)

        # More conservative Hough line detection
        roi_width = rx2 - rx1
        min_line_length = int(0.4 * roi_width)  # Shorter minimum

        lines = cv2.HoughLinesP(
            e, 1, np.pi/180,
            threshold=max(50, int(0.3 * roi_width)),  # Adaptive threshold
            minLineLength=min_line_length,
            maxLineGap=15
        )

        ys = []
        if lines is not None:
            for x1, y1, x2, y2 in lines[:, 0]:
                # More strict horizontal line filtering
                if abs(y2 - y1) <= 3 and abs(x2 - x1) >= min_line_length * 0.8:
                    ys.append(y1 + ry1)

        ys = sorted(set(ys))
        levels = []
        for y in ys:
            if not levels or abs(y - levels[-1]) > 20:  # Increased minimum separation
                levels.append(y)

        # IMPROVED: More robust fallback shelf positioning
        roi_height = ry2 - ry1
        if len(levels) < 2:
            # Create 3 evenly spaced shelf levels in the ROI
            shelf_height = roi_height // 3
            levels = [
                ry1 + int(0.45 * roi_height),  # Top shelf (below header)
                ry1 + int(0.7 * roi_height),   # Middle shelf
                ry1 + int(0.9 * roi_height)    # Bottom shelf
            ]
        elif len(levels) == 2:
            # Add a third level if we only found 2
            levels.append(min(H - 1, int(levels[1] + 0.25 * roi_height)))

        # Take only the best 3 levels
        levels = levels[:3]

        # Create bands with appropriate height
        band_h = max(int(0.05 * H), 25)  # Minimum band height
        bands = {}

        if len(levels) >= 1:
            bands["top"] = (max(0, levels[0] - band_h), min(H-1, levels[0] + band_h))
        if len(levels) >= 2:
            bands["middle"] = (max(0, levels[1] - band_h), min(H-1, levels[1] + band_h))
        if len(levels) >= 3:
            bands["bottom"] = (max(0, levels[2] - band_h), min(H-1, levels[2] + band_h))

        return levels, bands

    # --------------------------- shelves -------------------------------------
    def _find_shelves(self, roi: np.ndarray, rx1, ry1, rx2, ry2, H):
        g = cv2.cvtColor(roi, cv2.COLOR_RGB2GRAY)
        e = cv2.Canny(g, 50, 150)
        lines = cv2.HoughLinesP(
            e, 1, np.pi/180, threshold=70,
            minLineLength=int(0.45 * (rx2 - rx1)), maxLineGap=10
        )

        # Collect horizontal line y's in full-image coords
        ys = []
        if lines is not None:
            for x1, y1_, x2, y2_ in lines[:, 0]:
                if abs(y2_ - y1_) <= 4:
                    ys.append(y1_ + ry1)
        ys = sorted(set(ys))

        # De-dup near lines
        levels = []
        for y in ys:
            if not levels or abs(y - levels[-1]) > 12:
                levels.append(y)

        # Fallback: estimate two shelf edges at fixed fractions inside the ROI
        if len(levels) < 2:
            levels = [int(ry1 + 0.44 * (ry2 - ry1)), int(ry1 + 0.73 * (ry2 - ry1))]
        elif len(levels) > 3:
            # Keep three closest to expected positions
            targets = [0.44, 0.73, 0.90]
            levels = sorted(
                levels,
                key=lambda y: min(abs((y - ry1) / (ry2 - ry1) - t) for t in targets)
            )[:3]
            levels = sorted(levels)

        # Partition by midpoints → ensures non-overlapping bands
        cuts = [ry1]
        for i in range(len(levels) - 1):
            cuts.append(int(0.5 * (levels[i] + levels[i + 1])))
        cuts.append(ry2)

        # Ensure exactly 3 bands
        while len(cuts) < 4:
            cuts.insert(1, int(ry1 + len(cuts) * ((ry2 - ry1) // 4)))
        cuts = cuts[:4]

        bands = {
            "top": (cuts[0], cuts[1]),
            "middle": (cuts[1], cuts[2]),
            "bottom": (cuts[2], cuts[3]),
        }
        return levels[:3], bands


    # ---------------------------- YOLO ---------------------------------------
    def _yolo_props(self, roi: np.ndarray, rx1, ry1):
        """
        Multi-scale, multi-pass YOLO detection with retail-specific filtering
        """
        H, W = roi.shape[:2]
        all_props = []

        # Multi-scale detection - different sizes for different object types
        detection_configs = [
            # Large objects (printers, promotional graphics)
            {
                "imgsz": 640,
                "conf": max(0.10, self.conf * 0.7),  # Lower confidence for large objects
                "iou": 0.4,
                "min_area_ratio": 0.02,  # Minimum 2% of ROI area
                "max_area_ratio": 0.8,   # Maximum 80% of ROI area
                "target_types": ["printer", "promotional_graphic", "large_box"]
            },
            # Medium objects (product boxes)
            {
                "imgsz": 832,  # Higher resolution for better box detection
                "conf": self.conf,
                "iou": 0.5,
                "min_area_ratio": 0.008,  # Minimum 0.8% of ROI area
                "max_area_ratio": 0.25,   # Maximum 25% of ROI area
                "target_types": ["product_box", "medium_object"]
            },
            # Small objects (price tags, ink bottles)
            {
                "imgsz": 1024,  # Highest resolution for small objects
                "conf": max(0.05, self.conf * 0.5),  # Very low confidence for small objects
                "iou": 0.3,  # Lower IoU for better small object separation
                "min_area_ratio": 0.0005,  # Minimum 0.05% of ROI area
                "max_area_ratio": 0.05,    # Maximum 5% of ROI area
                "target_types": ["price_tag", "fact_tag", "small_object"]
            }
        ]

        for config in detection_configs:
            props = self._single_yolo_pass(roi, rx1, ry1, config)
            all_props.extend(props)

        # Remove duplicates and filter by quality
        filtered_props = self._filter_and_deduplicate_props(all_props, H, W)

        return filtered_props

    def _fallback_top_devices(self, img: np.ndarray, shelf_box: DetectionBox) -> list[DetectionBox]:
        """Edge/rect fallback for bright devices on the top shelf."""
        x1, y1, x2, y2 = shelf_box.x1, shelf_box.y1, shelf_box.x2, shelf_box.y2
        band = img[y1:y2, x1:x2]   # RGB

        gray = cv2.cvtColor(band, cv2.COLOR_RGB2GRAY)
        # enhance contrast
        gray = cv2.equalizeHist(gray)
        # adaptive threshold → edges
        thr = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                    cv2.THRESH_BINARY, 31, -5)
        edges = cv2.Canny(thr, 60, 160)
        edges = cv2.dilate(edges, np.ones((5,5), np.uint8), iterations=2)

        cnts, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        out = []
        H, W = img.shape[:2]
        min_area = 0.006 * (W * H)     # fairly large boxes only
        for c in cnts:
            rx, ry, rw, rh = cv2.boundingRect(c)
            area = rw * rh
            if area < min_area:
                continue
            ar = rw / float(rh)
            if not (0.85 <= ar <= 2.7):
                continue
            # back to full-image coords
            bx1, by1 = x1 + rx, y1 + ry
            bx2, by2 = bx1 + rw, by1 + rh
            out.append(
                DetectionBox(
                    x1=bx1, y1=by1, x2=bx2, y2=by2,
                    confidence=0.56,
                    class_id=CID["product_candidate"],
                    class_name="product_candidate",
                    area=area
                )
            )

        # merge overlapping rects
        out = self._merge(out, iou_same=0.50)
        return out

    # ------------------- OCR + CLIP preselection -----------------------------
    def _classify_proposals(self, img, props, bands, header_limit_y, ad_box):
        H, W = img.shape[:2]
        out = []
        text = self.text_feats

        BOX_LIKE = {"book", "box", "suitcase", "backpack", "handbag", "cardboard box"}  # YOLO names that often hit cartons
        DEVICE_LIKE = {"microwave", "tv", "monitor"}                   # YOLO mislabels for printers

        def blue_dominant(rgb_crop: np.ndarray) -> bool:
            # Epson cartons are very blue; check channel dominance
            b = rgb_crop[..., 2].mean() if rgb_crop.ndim == 3 else 0.0
            g = rgb_crop[..., 1].mean() if rgb_crop.ndim == 3 else 0.0
            r = rgb_crop[..., 0].mean() if rgb_crop.ndim == 3 else 0.0
            return (b > r * 1.12) and (b > g * 1.08)

        # build padded bands for safer membership
        padded = {k: (max(0, y1 - 12), min(H - 1, y2 + 12)) for k, (y1, y2) in bands.items()}

        for p in props:
            x1, y1, x2, y2 = p["box"]
            w, h = max(1, x2 - x1), max(1, y2 - y1)
            area = w * h
            if area < 0.0018 * W * H:
                continue

            # poster overlap — keep printers in front of poster
            if ad_box is not None:
                ax1, ay1, ax2, ay2 = ad_box
                ix1, iy1 = max(x1, ax1), max(y1, ay1)
                ix2, iy2 = min(x2, ax2), min(y2, ay2)
                inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
                if inter > 0.80 * area:
                    continue

            crop = img[y1:y2, x1:x2]
            ocr_txt = ""
            try:
                ocr_txt = pytesseract.image_to_string(Image.fromarray(crop), config="--psm 6").lower()
            except Exception:
                pass

            with torch.no_grad():
                ip = self.proc(images=Image.fromarray(crop), return_tensors="pt").to(self.device)
                f  = self.clip.get_image_features(**ip)
                f  = f / f.norm(dim=-1, keepdim=True)
                s = (f @ text.T).squeeze().tolist()
                s_poster, s_prod, s_box = float(s[0]), float(s[1]), float(s[2])
                if self.ref_prod_feats:
                    s_prod = max(s_prod, max(float((f @ rf.T).squeeze()) for rf in self.ref_prod_feats))

            # band membership
            band_scores = {k: max(0, min(y2, b2) - max(y1, b1)) for k, (b1, b2) in padded.items()}
            main_band = max(band_scores, key=band_scores.get) if band_scores else "middle"

            aspect = w / float(h)
            y_mid  = 0.5 * (y1 + y2)
            raw_lbl = (p.get("yolo_label") or "").lower()

            # --- Rules ---
            # A) Anything above header limit + landscape looks like poster
            if y_mid < header_limit_y and aspect > 1.10 and h > 0.10 * H:
                cname, score = "promotional_candidate", max(0.72, s_poster)
            # B) Top band → prefer device (printers) even if YOLO says 'microwave'
            elif main_band == "top":
                cname, score = "product_candidate", max(0.56, s_prod)
            else:
                looks_box = (
                    raw_lbl in BOX_LIKE or
                    ("epson" in ocr_txt) or ("ecotank" in ocr_txt) or
                    ("et-" in ocr_txt) or ("et " in ocr_txt) or
                    any(tok in ocr_txt for tok in ("2980", "3950", "4950")) or
                    (aspect >= 1.10 and area > 0.01 * W * H) or
                    blue_dominant(crop)
                )
                if looks_box and (s_box >= s_prod - 0.02):
                    cname, score = "box_candidate", max(0.56, s_box)
                else:
                    # if YOLO thinks 'book' and we’re not sure, still call it a box
                    if raw_lbl in BOX_LIKE and s_box >= 0.15:
                        cname, score = "box_candidate", max(0.56, s_box)
                    else:
                        cname, score = "product_candidate", max(0.52, s_prod)

            out.append(
                DetectionBox(
                    x1=x1, y1=y1, x2=x2, y2=y2,
                    confidence=float(score),
                    class_id=CID[cname],
                    class_name=cname,
                    area=area
                )
            )

        return out

    # --------------------- shrink/merge/cleanup ------------------------------
    def _shrink(self, img, dets: List[DetectionBox]) -> List[DetectionBox]:
        H,W = img.shape[:2]
        out=[]
        for d in dets:
            roi=img[d.y1:d.y2, d.x1:d.x2]
            if roi.size==0:
                continue
            g=cv2.cvtColor(roi, cv2.COLOR_RGB2GRAY)
            e=cv2.Canny(g,40,120)
            e=cv2.morphologyEx(e, cv2.MORPH_CLOSE, np.ones((5,5),np.uint8),1)
            cnts,_=cv2.findContours(e, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if not cnts:
                out.append(d)
                continue
            c=max(cnts, key=cv2.contourArea)
            x,y,w,h=cv2.boundingRect(c)
            x1,y1,x2,y2=_clamp(W,H,d.x1+x,d.y1+y,d.x1+x+w,d.y1+y+h)
            out.append(
                DetectionBox(
                    x1=x1,y1=y1,x2=x2,y2=y2,
                    confidence=d.confidence,
                    class_id=d.class_id,
                    class_name=d.class_name,
                    area=(x2-x1)*(y2-y1)
                )
            )
        return out

    def _merge(self, dets: List[DetectionBox], iou_same=0.45)->List[DetectionBox]:
        dets=sorted(dets, key=lambda d:(d.class_name,-d.confidence,-d.area))
        out=[]
        for d in dets:
            placed=False
            for m in out:
                if d.class_name == m.class_name and self._iou(d,m) > iou_same:
                    m.x1=min(m.x1,d.x1)
                    m.y1=min(m.y1,d.y1)
                    m.x2=max(m.x2,d.x2)
                    m.y2=max(m.y2,d.y2)
                    m.area = (m.x2 - m.x1) * (m.y2 - m.y1)
                    m.confidence = max(m.confidence, d.confidence)
                    placed = True
                    break
            if not placed:
                out.append(d)
        return out

    def _suppress_inside_poster(
        self,
        dets: List["DetectionBox"],
        ad_box: Optional[tuple[int,int,int,int]],
    ):
        """Drop candidates only if they are mostly inside the poster.
        This prevents top-shelf printers (in front of the lightbox) from being removed.
        """
        if ad_box is None:
            return dets

        ax1, ay1, ax2, ay2 = ad_box
        clean = []

        for d in dets:
            cy = (d.y1 + d.y2) * 0.5
            if d.class_name in {"product_candidate", "box_candidate"}:
                # intersection area
                ix1, iy1 = max(d.x1, ax1), max(d.y1, ay1)
                ix2, iy2 = min(d.x2, ax2), min(d.y2, ay2)
                inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
                if d.area > 0 and (inter / float(d.area)) > 0.80:
                    # mostly *inside* the poster → drop
                    continue
            clean.append(d)

        return clean

    # ------------------------------ debug ------------------------------------
    def _draw_yolo(self, img, props, roi_box, shelf_lines):
        rx1, ry1, rx2, ry2 = roi_box
        cv2.rectangle(img, (rx1, ry1), (rx2, ry2), (0, 255, 0), 2)
        for y in shelf_lines:
            cv2.line(img, (rx1, y), (rx2, y), (0, 255, 255), 2)
        for p in props:
            (x1, y1, x2, y2) = p["box"]
            cv2.rectangle(img, (x1, y1), (x2, y2), (255, 0, 0), 2)
            cv2.putText(
                img,
                f"{p['yolo_label']} {p['yolo_conf']:.2f}",
                (x1, max(12, y1 - 4)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                (255, 0, 0),
                1,
                cv2.LINE_AA,
            )
        return img

    def _draw_phase1(self, img, roi_box, shelf_lines, dets, ad_box=None):
        rx1, ry1, rx2, ry2 = roi_box
        cv2.rectangle(img, (rx1, ry1), (rx2, ry2), (0, 255, 0), 2)

        for y in shelf_lines:
            cv2.line(img, (rx1, y), (rx2, y), (0, 255, 255), 2)

        colors = {
            "promotional_candidate": (0, 200, 0),
            "product_candidate": (255, 140, 0),
            "box_candidate": (0, 140, 255),
        }

        for d in dets:
            c = colors.get(d.class_name, (200, 200, 200))
            cv2.rectangle(img, (d.x1, d.y1), (d.x2, d.y2), c, 2)
            cv2.putText(
                img,
                f"{d.class_name}:{d.confidence:.2f}",
                (d.x1, max(12, d.y1 - 4)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                c,
                1,
                cv2.LINE_AA,
            )

        if ad_box is not None:
            cv2.rectangle(img, (ad_box[0], ad_box[1]), (ad_box[2], ad_box[3]), (0, 255, 128), 2)
            cv2.putText(
                img,
                "poster_roi",
                (ad_box[0], max(12, ad_box[1] - 4)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                (0, 255, 128),
                1,
                cv2.LINE_AA,
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
        llm: Any = None,
        llm_provider: str = "claude",
        llm_model: Optional[str] = None,
        detection_model: str = "yolov8n",
        reference_images: List[Path] = None,
        confidence_threshold: float = 0.25,
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
        self.detection_model_name = detection_model
        self.factory = PlanogramDescriptionFactory()
        super().__init__(
            llm=llm,
            llm_provider=llm_provider,
            llm_model=llm_model,
            **kwargs
        )
        # Initialize the generic shape detector
        self.shape_detector = RetailDetector(
            yolo_model=detection_model,
            conf=confidence_threshold,
            device="cuda" if torch.cuda.is_available() else "cpu",
            reference_images=reference_images
        )
        self.logger.debug(
            f"Initialized RetailDetector with {detection_model}"
        )
        self.reference_images = reference_images or []
        self.confidence_threshold = confidence_threshold

    def detect_objects_and_shelves(
        self,
        image,
        confidence_threshold: float = 0.5
    ):
        self.logger.debug("Step 1: Detecting generic shapes and boundaries...")

        pil_image = Image.open(image) if isinstance(image, (str, Path)) else image

        det_out = self.shape_detector.detect(
            image=pil_image,
            debug_raw="/tmp/data/yolo_raw_debug.png",
            debug_phase1="/tmp/data/yolo_phase1_debug.png"
        )

        shelves_dict = det_out["shelves"]          # {'top': DetectionBox(...), 'middle': ...}
        proposals    = det_out["proposals"]        # List[DetectionBox]

        print("PROPOSALS:", proposals)
        print("SHELVES:", shelves_dict)

        # --- IMPORTANT: use Phase-1 shelf bands (not %-of-image buckets) ---
        shelf_regions = self._materialize_shelf_regions(shelves_dict, proposals)

        detections = list(proposals)

        self.logger.debug("Found %d objects in %d shelf regions",
                        len(detections), len(shelf_regions))

        # Recover price tags and re-map to the same Phase-1 shelves
        try:
            tag_dets = self._recover_price_tags(pil_image, shelf_regions)
            if tag_dets:
                detections.extend(tag_dets)
                shelf_regions = self._materialize_shelf_regions(shelves_dict, detections)
                self.logger.debug("Recovered %d fact tags on shelf edges", len(tag_dets))
        except Exception as e:
            self.logger.warning(f"Tag recovery failed: {e}")

        self.logger.debug("Found %d objects in %d shelf regions",
                        len(detections), len(shelf_regions))
        return shelf_regions, detections

    def _materialize_shelf_regions(
        self,
        shelves_dict: Dict[str, DetectionBox],
        dets: List[DetectionBox]
    ) -> List[ShelfRegion]:
        """Turn Phase-1 shelf bands into ShelfRegion objects and assign detections by y-overlap."""
        def y_overlap(a1, a2, b1, b2) -> int:
            return max(0, min(a2, b2) - max(a1, b1))

        regions: List[ShelfRegion] = []

        # Header: anything fully above the top shelf band
        if "top" in shelves_dict:
            cut_y = shelves_dict["top"].y1
            header_objs = [d for d in dets if d.y2 <= cut_y]
            if header_objs:
                x1 = min(o.x1 for o in header_objs)
                y1 = min(o.y1 for o in header_objs)
                x2 = max(o.x2 for o in header_objs)
                y2 = cut_y
                bbox = DetectionBox(x1=x1, y1=y1, x2=x2, y2=y2,
                                    confidence=1.0, class_id=190,
                                    class_name="shelf_region", area=(x2-x1)*(y2-y1))
                regions.append(ShelfRegion(shelf_id="header", bbox=bbox, level="header", objects=header_objs))

        for level in ["top", "middle", "bottom"]:
            if level not in shelves_dict:
                continue
            band = shelves_dict[level]
            objs = [d for d in dets if y_overlap(d.y1, d.y2, band.y1, band.y2) > 0]
            if not objs:
                continue
            x1 = min(o.x1 for o in objs)
            y1 = band.y1
            x2 = max(o.x2 for o in objs)
            y2 = band.y2
            bbox = DetectionBox(x1=x1, y1=y1, x2=x2, y2=y2,
                                confidence=1.0, class_id=190,
                                class_name="shelf_region", area=(x2-x1)*(y2-y1))
            regions.append(ShelfRegion(shelf_id=f"{level}_shelf", bbox=bbox, level=level, objects=objs))

        return regions


    def _recover_price_tags(
        self,
        image: Union[str, Path, Image.Image],
        shelf_regions: List[ShelfRegion],
        *,
        min_width: int = 40,
        max_width: int = 280,
        min_height: int = 14,
        max_height: int = 100,
        iou_suppress: float = 0.2,
    ) -> List[DetectionBox]:
        """
        Heuristic price-tag recovery:
        - For each shelf region, scan a thin horizontal strip at the *front edge*.
        - Use morphology (blackhat + gradients) to pick up dark text on light tags.
        - Return small rectangular boxes classified as 'fact_tag'.
        """
        if isinstance(image, (str, Path)):
            pil = Image.open(image).convert("RGB")
        else:
            pil = image.convert("RGB")

        import numpy as np, cv2

        img = np.array(pil)  # RGB
        H, W = img.shape[:2]
        tags: List[DetectionBox] = []

        for sr in shelf_regions:
            # Only look where tags actually live
            if sr.level not in {"top", "middle", "bottom"}:
                continue

            # Build a strip hugging the shelf's lower edge
            y_top = sr.bbox.y1
            y_bot = sr.bbox.y2
            shelf_h = max(1, y_bot - y_top)

            # Tag strip: bottom ~12% of shelf + a little margin below
            strip_h = int(np.clip(0.12 * shelf_h, 24, 90))
            y1 = max(0, y_bot - strip_h - int(0.02 * shelf_h))
            y2 = min(H - 1, y_bot + int(0.04 * shelf_h))
            x1 = max(0, sr.bbox.x1)
            x2 = min(W - 1, sr.bbox.x2)
            if y2 <= y1 or x2 <= x1:
                continue

            roi = img[y1:y2, x1:x2]  # RGB
            gray = cv2.cvtColor(roi, cv2.COLOR_RGB2GRAY)

            # Highlight dark text on light tag
            rectK = cv2.getStructuringElement(cv2.MORPH_RECT, (13, 5))
            blackhat = cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT, rectK)

            # Horizontal gradient to emphasize tag edges
            gradX = cv2.Sobel(blackhat, ddepth=cv2.CV_32F, dx=1, dy=0, ksize=-1)
            gradX = cv2.convertScaleAbs(gradX)

            # Close gaps & threshold
            closeK = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 5))
            closed = cv2.morphologyEx(gradX, cv2.MORPH_CLOSE, closeK, iterations=2)
            th = cv2.threshold(closed, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]

            # Clean up
            th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (5, 3)))
            th = cv2.dilate(th, None, iterations=1)

            cnts, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for c in cnts:
                x, y, w, h = cv2.boundingRect(c)
                if w < min_width or w > max_width or h < min_height or h > max_height:
                    continue
                ar = w / float(h)
                if ar < 1.2 or ar > 6.5:
                    continue

                # rectangularity = how "tag-like" the contour is
                rect_area = w * h
                cnt_area = max(1.0, cv2.contourArea(c))
                rectangularity = cnt_area / rect_area
                if rectangularity < 0.45:
                    continue

                # Score → confidence
                confidence = float(min(0.95, 0.55 + 0.4 * rectangularity))

                # Map to full-image coords
                gx1, gy1 = x1 + x, y1 + y
                gx2, gy2 = gx1 + w, gy1 + h

                tags.append(
                    DetectionBox(
                        x1=int(gx1), y1=int(gy1), x2=int(gx2), y2=int(gy2),
                        confidence=confidence,
                        class_id=102,
                        class_name="price_tag",
                        area=int(rect_area),
                    )
                )

        # Light NMS to avoid duplicates
        def iou(a: DetectionBox, b: DetectionBox) -> float:
            ix1, iy1 = max(a.x1, b.x1), max(a.y1, b.y1)
            ix2, iy2 = min(a.x2, b.x2), min(a.y2, b.y2)
            if ix2 <= ix1 or iy2 <= iy1:
                return 0.0
            inter = (ix2 - ix1) * (iy2 - iy1)
            return inter / float(a.area + b.area - inter)

        tags_sorted = sorted(tags, key=lambda d: (d.confidence, d.area), reverse=True)
        kept: List[DetectionBox] = []
        for d in tags_sorted:
            if all(iou(d, k) <= iou_suppress for k in kept):
                kept.append(d)
        return kept

    def _is_promotional_by_size_and_position(
        self,
        detection: DetectionBox,
        height: int,
        width: int
    ) -> bool:
        """
        Helper method to identify promotional graphics by size and position characteristics
        """
        # Promotional graphics are typically:
        # 1. Large relative to image size
        # 2. Wide aspect ratio (landscape)
        # 3. Located in upper portion of image

        box_width = detection.x2 - detection.x1
        box_height = detection.y2 - detection.y1
        aspect_ratio = box_width / max(box_height, 1)

        relative_area = detection.area / (width * height)
        y_center_ratio = ((detection.y1 + detection.y2) / 2) / height

        # Criteria for promotional graphic
        is_large = relative_area > 0.15  # Covers significant portion of image
        is_landscape = aspect_ratio > 2.0  # Wide format
        is_upper = y_center_ratio < 0.4  # In upper portion
        is_horizontal_span = box_width > width * 0.6  # Spans most of width

        return (is_large and is_landscape) or (is_upper and is_horizontal_span)

    def _organize_into_shelves(
        self,
        detections: List[DetectionBox],
        image_size: Tuple[int, int]
    ) -> List[ShelfRegion]:
        """
        Fixed: Organize detections into shelf regions with non-overlapping boundaries
        """
        width, height = image_size
        shelf_regions = []

        # FIX 1: Use non-overlapping Y boundaries to prevent misassignment
        header_objects = [d for d in detections if d.y1 < height * 0.25]  # Top 25%
        top_objects = [d for d in detections if height * 0.25 <= d.y1 < height * 0.55]  # 25%-55%
        middle_objects = [d for d in detections if height * 0.55 <= d.y1 < height * 0.75]  # 55%-75%
        bottom_objects = [d for d in detections if d.y1 >= height * 0.75]  # Bottom 25%

        # Additional filtering: Promotional graphics should go to header
        # Move large promotional graphics from top shelf to header if they're in the upper portion
        promotional_in_top = [
            d for d in top_objects if (
                d.class_name in ['promotional_graphic', 'tv', 'promotional_candidate', 'advertisement', 'poster', 'display']
                or self._is_promotional_by_size_and_position(d, height, width)
            )
        ]

        for promo in promotional_in_top:
            if promo.y1 < height * 0.35:  # If in upper portion of top shelf, move to header
                top_objects.remove(promo)
                header_objects.append(promo)

        # Create shelf regions
        if header_objects:
            shelf_regions.append(
                self._create_shelf_region("header", "header", header_objects)
            )
        if top_objects:
            shelf_regions.append(
                self._create_shelf_region("top_shelf", "top", top_objects))
        if middle_objects:
            shelf_regions.append(
                self._create_shelf_region("middle_shelf", "middle", middle_objects)
            )
        if bottom_objects:
            shelf_regions.append(
                self._create_shelf_region("bottom_shelf", "bottom", bottom_objects)
            )

        return shelf_regions

    def _create_shelf_region(self, shelf_id: str, level: str, objects: List[DetectionBox]) -> ShelfRegion:
        """Create a shelf region from objects"""
        if not objects:
            return None

        x1 = min(obj.x1 for obj in objects)
        y1 = min(obj.y1 for obj in objects)
        x2 = max(obj.x2 for obj in objects)
        y2 = max(obj.y2 for obj in objects)

        bbox = DetectionBox(
            x1=x1, y1=y1, x2=x2, y2=y2,
            confidence=1.0, class_id=-1, class_name="shelf_region",
            area=(x2-x1) * (y2-y1)
        )

        return ShelfRegion(
            shelf_id=shelf_id,
            bbox=bbox,
            level=level,
            objects=objects
        )

    def _debug_dump_crops(self, img: Image.Image, dets, tag="step1"):
        os.makedirs("/tmp/data/debug", exist_ok=True)
        h, w = img.size[1], img.size[0]
        img = np.array(img)  # RGB
        for i, d in enumerate(dets, 1):
            b = d.detection_box if hasattr(d, "detection_box") else d
            x1 = max(0, min(w-1, int(min(b.x1, b.x2))))
            x2 = max(0, min(w-1, int(max(b.x1, b.x2))))
            y1 = max(0, min(h-1, int(min(b.y1, b.y2))))
            y2 = max(0, min(h-1, int(max(b.y1, b.y2))))
            crop = img[y1:y2, x1:x2]
            cv2.imwrite(
                f"/tmp/data/debug/{tag}_{i}_{b.class_name}_{x1}_{y1}_{x2}_{y2}.png",
                cv2.cvtColor(crop, cv2.COLOR_RGB2BGR)
            )

    # STEP 2: LLM Object Identification
    async def identify_objects_with_references(
        self,
        image: Union[str, Path, Image.Image],
        detections: List[DetectionBox],
        shelf_regions: List[ShelfRegion],
        reference_images: List[Union[str, Path, Image.Image]]
    ) -> List[IdentifiedProduct]:
        """
        Step 2: Use LLM to identify detected objects using reference images

        Args:
            image: Original endcap image
            detections: Object detections from Step 1
            shelf_regions: Shelf regions from Step 1
            reference_images: Reference product images

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
        effective_dets = [d for d in detections if d.class_name not in {"slot", "shelf_region"}]
        self._debug_dump_crops(pil_image, effective_dets, tag="effective")
        self._debug_dump_crops(pil_image, detections, tag="raw")

        annotated_image = self._create_annotated_image(pil_image, effective_dets)
        # annotated_image = self._create_annotated_image(image, detections)

        # Build identification prompt (without structured output request)
        prompt = self._build_identification_prompt(effective_dets, shelf_regions)

        async with self.llm as client:

            try:
                if self.llm_provider == "claude":
                    response = await client.ask_to_image(
                        image=annotated_image,
                        prompt=prompt,
                        reference_images=reference_images,
                        max_tokens=4000,
                        structured_output=IdentificationResponse,
                    )
                elif self.llm_provider == "google":
                    response = await client.ask_to_image(
                        image=annotated_image,
                        prompt=prompt,
                        reference_images=reference_images,
                        structured_output=IdentificationResponse,
                        max_tokens=4000
                    )
                elif self.llm_provider == "openai":
                    extra_refs = [annotated_image] + (reference_images or [])
                    identified_products = await client.image_identification(
                        image=image,
                        prompt=prompt,
                        detections=effective_dets,
                        shelf_regions=shelf_regions,
                        reference_images=extra_refs,
                        temperature=0.0,
                        ocr_hints=True
                    )
                    identified_products = await self._augment_products_with_box_ocr(
                        image,
                        identified_products
                    )
                    return identified_products
                else:  # Fallback
                    response = await client.ask_to_image(
                        image=annotated_image,
                        prompt=prompt,
                        reference_images=reference_images,
                        structured_output=IdentificationResponse,
                        max_tokens=4000
                    )

                self.logger.debug(f"Response type: {type(response)}")
                self.logger.debug(f"Response content: {response}")

                if hasattr(response, 'structured_output') and response.structured_output:
                    identification_response = response.structured_output

                    self.logger.debug(f"Structured output type: {type(identification_response)}")

                    # Handle IdentificationResponse object directly
                    if isinstance(identification_response, IdentificationResponse):
                        # Access the identified_products list from the IdentificationResponse
                        identified_products = identification_response.identified_products

                        self.logger.debug(
                            f"Got {len(identified_products)} products from IdentificationResponse"
                        )

                        # Add detection_box to each product based on detection_id
                        valid_products = []
                        for product in identified_products:
                            if product.product_type == "promotional_graphic":
                                product.visual_features = await self._extract_text_from_region(
                                    image, product.detection_box
                                )
                            if product.detection_id and 1 <= product.detection_id <= len(effective_dets):
                                det_idx = product.detection_id - 1  # Convert to 0-based index
                                product.detection_box = effective_dets[det_idx]
                                valid_products.append(product)
                                self.logger.debug(
                                    f"Linked {product.product_type} {product.product_model} (ID: {product.detection_id}) to detection box"
                                )
                            else:
                                self.logger.warning(
                                    f"Product has invalid detection_id: {product.detection_id}"
                                )

                        self.logger.debug(f"Successfully linked {len(valid_products)} out of {len(identified_products)} products")
                        return valid_products

                    else:
                        self.logger.error(
                            f"Expected IdentificationResponse, got: {type(identification_response)}"
                        )
                        fallbacks = self._create_simple_fallbacks(effective_dets, shelf_regions)
                        fallbacks = await self._augment_products_with_box_ocr(image, fallbacks)
                        return fallbacks
                else:
                    self.logger.warning("No structured output received")
                    fallbacks = self._create_simple_fallbacks(effective_dets, shelf_regions)
                    fallbacks = await self._augment_products_with_box_ocr(image, fallbacks)
                    return fallbacks

            except Exception as e:
                self.logger.error(f"Error in structured identification: {e}")
                traceback.print_exc()
                fallbacks = self._create_simple_fallbacks(effective_dets, shelf_regions)
                fallbacks = await self._augment_products_with_box_ocr(image, fallbacks)
                return fallbacks

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
        if "epson" in t:
            return "Epson"
        if "ecotank" in t:
            return "Epson"  # brand inference via line
        return None

    async def _augment_products_with_box_ocr(
        self,
        image: Union[str, Path, Image.Image],
        products: List[IdentifiedProduct]
    ) -> List[IdentifiedProduct]:
        """Add OCR-derived evidence to boxes/printers and fix product_model when we see ET-xxxx."""
        for p in products:
            if not p.detection_box:
                continue
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
                        #  - printers: "ET-4950"
                        #  - boxes:    "ET-4950 box"
                        if p.product_type == "product_box":
                            target = f"{model.upper()} box"
                        else:
                            target = model.upper()

                        # If missing or mismatched, replace
                        if not p.product_model:
                            p.product_model = target
                        else:
                            # If current looks generic/incorrect, fix it
                            cur = (p.product_model or "").lower()
                            if "et-" in target.lower() and ("et-" not in cur or "box" in target.lower() and "box" not in cur):
                                p.product_model = target
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
            import re
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

    def _build_identification_prompt(
        self,
        detections: List[DetectionBox],
        shelf_regions: List[ShelfRegion]
    ) -> str:
        """Build prompt for LLM object identification"""

        prompt = f"""

You are an expert at identifying retail products in planogram displays.

I've provided an annotated image showing {len(detections)} detected objects with red bounding boxes and ID numbers.

DETECTED OBJECTS:
"""

        for i, detection in enumerate(detections, 1):
            prompt += f"ID {i}: {detection.class_name} at ({detection.x1},{detection.y1},{detection.x2},{detection.y2})\n"

        # Add shelf organization
        prompt += "\nSHELF ORGANIZATION:\n"
        for shelf in shelf_regions:
            object_ids = []
            for obj in shelf.objects:
                for i, detection in enumerate(detections, 1):
                    if (obj.x1 == detection.x1 and obj.y1 == detection.y1):
                        object_ids.append(str(i))
                        break
            prompt += f"{shelf.level.upper()}: Objects {', '.join(object_ids)}\n"

        prompt += f"""
TASK: Identify each detected object using the reference images.

IMPORTANT NAMING RULES:
1. For printer devices: Use model name only (e.g., "ET-2980", "ET-3950", "ET-4950")
2. For product boxes: Use model name + " box" (e.g., "ET-2980 box", "ET-3950 box", "ET-4950 box")
3. For promotional graphics: Use descriptive name (e.g., "Epson EcoTank Advertisement") and look for promotional text.
4. For price/fact tags: Use "price tag" or "fact tag"

For each detection (ID 1-{len(detections)}), provide:
- detection_id: The exact ID number from the red bounding box (1-{len(detections)})
- product_type: printer, product_box, fact_tag, promotional_graphic, or ink_bottle
- product_model: Follow naming rules above based on product_type
- confidence: Your confidence (0.0-1.0)
- visual_features: List of visual features
- reference_match: Which reference image matches (or "none")
- shelf_location: header, top, middle, or bottom
- position_on_shelf: left, center, or right
- Remove any duplicates - only one entry per detection_id

EXAMPLES:
- If you see a printer device: product_type="printer", product_model="ET-2980"
- If you see a product box: product_type="product_box", product_model="ET-2980 box"
- If you see a price tag: product_type="fact_tag", product_model="price tag"

Example format:
{{
  "detections": [
    {{
      "detection_id": 1,
      "product_type": "printer",
      "product_model": "ET-2980",
      "confidence": 0.95,
      "visual_features": ["white printer", "LCD screen", "ink tanks visible"],
      "reference_match": "first reference image",
      "shelf_location": "top",
      "position_on_shelf": "left"
    }},
    {{
      "detection_id": 2,
      "product_type": "product_box",
      "product_model": "ET-2980 box",
      "confidence": 0.90,
      "visual_features": ["blue box", "printer image", "Epson branding"],
      "reference_match": "box reference image",
      "shelf_location": "bottom",
      "position_on_shelf": "left"
    }}
  ]
}}

REFERENCE IMAGES show Epson printer models - compare visual design, control panels, ink systems.

CLASSIFICATION RULES FOR ADS
- Large horizontal banners/displays with brand logo and/or slogan, should be classified as promotional_graphic.
- If you detect any poster/graphic/signage, set product_type="promotional_graphic".
- Always fill:
  brand := the logo or text brand on the asset (e.g., "Epson"). Use OCR hints.
  advertisement_type := one of ["backlit_graphic","endcap_poster","shelf_talker","banner","digital_display"].
- Heuristics:
  * If the graphic is in shelf_location="header" and appears illuminated or framed, use advertisement_type="backlit_graphic".
  * If the OCR includes "Epson" or "EcoTank", set brand="Epson".
- If the brand or type cannot be determined, keep them as null (not empty strings).

Respond with the structured data for all {len(detections)} objects.
"""

        return prompt

    def _create_simple_fallbacks(
        self,
        detections: List[DetectionBox],
        shelf_regions: List[ShelfRegion]
    ) -> List[IdentifiedProduct]:
        """Create simple fallback identifications"""

        results = []
        for detection in detections:
            shelf_location = "unknown"
            for shelf in shelf_regions:
                if detection in shelf.objects:
                    shelf_location = shelf.level
                    break

            if detection.class_name == "element" and shelf_location == "header":
                product_type = "promotional_graphic"
            elif detection.class_name == "element" and shelf_location == "top":
                product_type = "printer"
            elif detection.class_name == "tag":
                product_type = "fact_tag"
            elif detection.class_name == "box":
                product_type = "product_box"
            else:
                cls = detection.class_name
                if cls == "promotional_graphic":
                    product_type = "promotional_graphic"
                elif cls == "printer":
                    product_type = "printer"
                elif cls == "product_box":
                    product_type = "product_box"
                elif cls in ("price_tag", "fact_tag"):
                    product_type = "fact_tag"
                else:
                    product_type = "unknown"

            product = IdentifiedProduct(
                detection_box=detection,
                product_type=product_type,
                product_model=None,
                confidence=0.3,
                visual_features=["fallback_identification"],
                reference_match=None,
                shelf_location=shelf_location,
                position_on_shelf="center"
            )
            results.append(product)

        return results

    def _is_promotional_product(self, product_name: str) -> bool:
        """Check if a product name refers to promotional material"""
        promotional_keywords = [
            'advertisement', 'graphic', 'promo', 'banner', 'sign', 'poster', 'display'
        ]
        product_lower = product_name.lower()
        return any(keyword in product_lower for keyword in promotional_keywords)

    # STEP 3: Planogram Compliance Check
    def check_planogram_compliance(
        self,
        identified_products: List[IdentifiedProduct],
        planogram_description: PlanogramDescription
    ) -> List[ComplianceResult]:
        """Check compliance of identified products against the planogram

        Args:
            identified_products (List[IdentifiedProduct]): The products identified in the image
            planogram_description (PlanogramDescription): The expected planogram layout

        Returns:
            List[ComplianceResult]: The compliance results for each shelf
        """
        results: List[ComplianceResult] = []

        # Group found products by shelf level
        by_shelf = defaultdict(list)
        for p in identified_products:
            by_shelf[p.shelf_location].append(p)

        # Iterate through expected shelves
        for shelf_cfg in planogram_description.shelves:
            shelf_level = shelf_cfg.level

            # Build expected product list (excluding tags)
            expected = []
            for sp in shelf_cfg.products:
                if sp.product_type in ("fact_tag", "price_tag", "slot"):
                    continue
                nm = self._normalize_product_name((sp.name or sp.product_type) or "unknown")
                expected.append(nm)

            # Gather found products on this shelf
            found, promos = [], []
            for p in by_shelf.get(shelf_level, []):
                if p.product_type in ("fact_tag", "price_tag", "slot"):
                    continue
                nm = self._normalize_product_name(p.product_model or p.product_type)
                found.append(nm)
                if p.product_type == "promotional_graphic":
                    promos.append(p)

            # Calculate basic product compliance
            missing = [e for e in expected if e not in found]
            unexpected = [] if shelf_cfg.allow_extra_products else [f for f in found if f not in expected]
            basic_score = (sum(1 for e in expected if e in found) / (len(expected) or 1))

            # FIX 3: Enhanced text compliance handling
            text_results, text_score, overall_text_ok = [], 1.0, True

            # Check for advertisement endcap on this shelf
            endcap = planogram_description.advertisement_endcap
            if endcap and endcap.enabled and endcap.position == shelf_level:
                if endcap.text_requirements:
                    # Combine visual features from all promotional items
                    all_features = []
                    for promo in promos:
                        if hasattr(promo, 'visual_features') and promo.visual_features:
                            all_features.extend(promo.visual_features)

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

            # For non-header shelves without text requirements, don't penalize
            elif shelf_level != "header":
                overall_text_ok = True  # Don't require text compliance on product shelves
                text_score = 1.0

            # Determine compliance threshold
            threshold = getattr(shelf_cfg, "compliance_threshold",
                            planogram_description.global_compliance_threshold or 0.8)

            # FIX 4: Better status determination logic
            # For product shelves (non-header), focus on product compliance
            if shelf_level != "header":
                if basic_score >= threshold and not unexpected:
                    status = ComplianceStatus.COMPLIANT
                elif basic_score == 0.0:
                    status = ComplianceStatus.MISSING
                else:
                    status = ComplianceStatus.NON_COMPLIANT
            else:
                # For header shelf, require both product and text compliance
                if basic_score >= threshold and not unexpected and overall_text_ok:
                    status = ComplianceStatus.COMPLIANT
                elif basic_score == 0.0:
                    status = ComplianceStatus.MISSING
                else:
                    status = ComplianceStatus.NON_COMPLIANT

            # Calculate combined score with appropriate weighting
            if shelf_level == "header":
                # Header: Balance product and text compliance
                weights = {"product_compliance": 0.5, "text_compliance": 0.5}
            else:
                # Product shelves: Emphasize product compliance
                weights = {"product_compliance": 0.9, "text_compliance": 0.1}

            combined_score = (basic_score * weights["product_compliance"] +
                            text_score * weights["text_compliance"])

            results.append(ComplianceResult(
                shelf_level=shelf_level,
                expected_products=expected,
                found_products=found,
                missing_products=missing,
                unexpected_products=unexpected,
                compliance_status=status,
                compliance_score=combined_score,
                text_compliance_results=text_results,
                text_compliance_score=text_score,
                overall_text_compliant=overall_text_ok
            ))

        return results

    def _normalize_product_name(self, product_name: str) -> str:
        """Normalize product names for comparison"""
        if not product_name:
            return "unknown"

        name = product_name.lower().strip()

        # Map various representations to standard names
        mapping = {
            # Printer models (device only)
            "et-2980": "et_2980",
            "et2980": "et_2980",
            "et-3950": "et_3950",
            "et3950": "et_3950",
            "et-4950": "et_4950",
            "et4950": "et_4950",

            # Box versions (explicit box naming)
            "et-2980 box": "et_2980_box",
            "et2980 box": "et_2980_box",
            "et-3950 box": "et_3950_box",
            "et3950 box": "et_3950_box",
            "et-4950 box": "et_4950_box",
            "et4950 box": "et_4950_box",

            # Alternative box patterns
            "et-2980 product box": "et_2980_box",
            "et-3950 product box": "et_3950_box",
            "et-4950 product box": "et_4950_box",

            # Generic terms
            "printer": "device",
            "product_box": "box",
            "fact_tag": "price_tag",
            "price_tag": "price_tag",
            "fact tag": "price_tag",
            "price tag": "price_tag",
            "promotional_graphic": "promotional_graphic",
            "epson ecotank advertisement": "promotional_graphic",
            "backlit_graphic": "promotional_graphic",

            # Handle promotional graphics correctly
            "promotional_graphic": "promotional_graphic",
            "epson ecotank advertisement": "promotional_graphic",
            "backlit_graphic": "promotional_graphic",
            "advertisement": "promotional_graphic",
            "graphic": "promotional_graphic",
            "promo": "promotional_graphic",
            "banner": "promotional_graphic",
            "sign": "promotional_graphic",
            "poster": "promotional_graphic",
            "display": "promotional_graphic",
            # Handle None values for promotional graphics
            "none": "promotional_graphic"
        }

        # First try exact matches
        if name in mapping:
            return mapping[name]

        promotional_keywords = ['advertisement', 'graphic', 'promo', 'banner', 'sign', 'poster', 'display', 'ecotank']
        if any(keyword in name for keyword in promotional_keywords):
            return "promotional_graphic"

        # Then try pattern matching for boxes
        for pattern in ["et-2980", "et2980"]:
            if pattern in name and "box" in name:
                return "et_2980_box"
        for pattern in ["et-3950", "et3950"]:
            if pattern in name and "box" in name:
                return "et_3950_box"
        for pattern in ["et-4950", "et4950"]:
            if pattern in name and "box" in name:
                return "et_4950_box"

        # Pattern matching for printers (without box)
        for pattern in ["et-2980", "et2980"]:
            if pattern in name and "box" not in name:
                return "et_2980"
        for pattern in ["et-3950", "et3950"]:
            if pattern in name and "box" not in name:
                return "et_3950"
        for pattern in ["et-4950", "et4950"]:
            if pattern in name and "box" not in name:
                return "et_4950"

        return name

    # Complete Pipeline
    async def run(
        self,
        image: Union[str, Path, Image.Image],
        planogram_description: PlanogramDescription,
        return_overlay: Optional[str] = None,  # "identified" | "detections" | "both" | None
        overlay_save_path: Optional[Union[str, Path]] = None,
    ) -> Dict[str, Any]:
        """
        Run the complete 3-step planogram compliance pipeline

        Returns:
            Complete analysis results including all steps
        """

        self.logger.debug("Step 1: Detecting objects and shelves...")
        shelf_regions, detections = self.detect_objects_and_shelves(
            image, self.confidence_threshold
        )

        self.logger.debug(
            f"Found {len(detections)} objects in {len(shelf_regions)} shelf regions"
        )

        self.logger.info("Step 2: Identifying objects with LLM...")
        identified_products = await self.identify_objects_with_references(
            image, detections, shelf_regions, self.reference_images
        )

        # De-duplicate promotional_graphic (keep the largest)
        promos = [p for p in identified_products if p.product_type == "promotional_graphic" and p.detection_box]
        if len(promos) > 1:
            keep = max(promos, key=lambda p: p.detection_box.area)
            identified_products = [
                p for p in identified_products if p.product_type != "promotional_graphic"
            ] + [keep]

        print('==== ')
        print(identified_products)
        W, H = (image.width, image.height) if hasattr(image, "width") else Image.open(image).size
        for p in identified_products:
            if p.product_type == "promotional_graphic" and p.detection_box:
                if self._is_promotional_by_size_and_position(p.detection_box, H, W) or \
                ((p.detection_box.y1 + p.detection_box.y2) / 2.0) < 0.45 * H:
                    p.shelf_location = "header"

        self.logger.debug(f"Identified {len(identified_products)} products")

        self.logger.info("Step 3: Checking planogram compliance...")


        compliance_results = self.check_planogram_compliance(
            identified_products, planogram_description
        )

        # Calculate overall compliance
        total_score = sum(
            r.compliance_score for r in compliance_results
        ) / len(compliance_results) if compliance_results else 0.0
        overall_compliant = all(
            r.compliance_status == ComplianceStatus.COMPLIANT for r in compliance_results
        )
        overlay_image = None
        overlay_path = None
        if return_overlay:
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
        mode: str = "identified",            # "identified" | "detections" | "both"
        show_shelves: bool = True,
        save_to: Optional[Union[str, Path]] = None,
    ) -> Image.Image:
        """
        Draw an overlay of shelves + boxes.

        - mode="detections": draw Step-1 boxes with IDs and confidences.
        - mode="identified": draw Step-2 products color-coded by type with model/shelf labels.
        - mode="both": draw detections (thin) + identified (thick).
        If `save_to` is provided, the image is saved there.
        Returns a PIL.Image either way.
        """

        # --- get base image ---
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

        # --- helpers ---
        def _clip(x1, y1, x2, y2):
            return max(0, x1), max(0, y1), min(W-1, x2), min(H-1, y2)

        def _txt(draw_obj, xy, text, fill, bg=None):
            if not font:
                draw_obj.text(xy, text, fill=fill)
                return
            # background
            bbox = draw_obj.textbbox(xy, text, font=font)
            if bg is not None:
                draw_obj.rectangle(bbox, fill=bg)
            draw_obj.text(xy, text, fill=fill, font=font)

        # colors per product type
        colors = {
            "printer": (255, 0, 0),              # red
            "product_box": (255, 128, 0),        # orange
            "fact_tag": (0, 128, 255),           # blue
            "promotional_graphic": (0, 200, 0),  # green
            "sign": (0, 200, 0),
            "ink_bottle": (160, 0, 200),
            "element": (180, 180, 180),
            "unknown": (200, 200, 200),
        }

        # --- shelves ---
        if show_shelves and shelf_regions:
            for sr in shelf_regions:
                x1, y1, x2, y2 = _clip(sr.bbox.x1, sr.bbox.y1, sr.bbox.x2, sr.bbox.y2)
                draw.rectangle([x1, y1, x2, y2], outline=(255, 255, 0), width=3)
                _txt(draw, (x1+3, max(0, y1-14)), f"SHELF {sr.level}", fill=(0, 0, 0), bg=(255, 255, 0))

        # --- detections (thin) ---
        if mode in ("detections", "both") and detections:
            for i, d in enumerate(detections, start=1):
                x1, y1, x2, y2 = _clip(d.x1, d.y1, d.x2, d.y2)
                draw.rectangle([x1, y1, x2, y2], outline=(255, 0, 0), width=2)
                lbl = f"ID:{i} {d.class_name} {d.confidence:.2f}"
                _txt(draw, (x1+2, max(0, y1-12)), lbl, fill=(0, 0, 0), bg=(255, 0, 0))

        # --- identified products (thick) ---
        if mode in ("identified", "both") and identified_products:
            # Draw larger boxes first (helps labels remain readable)
            for p in sorted(identified_products, key=lambda x: (x.detection_box.area if x.detection_box else 0), reverse=True):
                if not p.detection_box:
                    continue
                x1, y1, x2, y2 = _clip(p.detection_box.x1, p.detection_box.y1, p.detection_box.x2, p.detection_box.y2)
                c = colors.get(p.product_type, (255, 0, 255))
                draw.rectangle([x1, y1, x2, y2], outline=c, width=5)

                # label: #id type model (conf) [shelf/pos]
                pid = p.detection_id if p.detection_id is not None else "–"
                mm = f" {p.product_model}" if p.product_model else ""
                lab = f"#{pid} {p.product_type}{mm} ({p.confidence:.2f}) [{p.shelf_location}/{p.position_on_shelf}]"
                _txt(draw, (x1+3, max(0, y1-14)), lab, fill=(0, 0, 0), bg=c)

        # --- legend (optional, tiny) ---
        legend_y = 8
        for key in ("printer","product_box","fact_tag","promotional_graphic"):
            c = colors[key]
            draw.rectangle([8, legend_y, 28, legend_y+10], fill=c)
            _txt(draw, (34, legend_y-2), key, fill=(255,255,255), bg=None)
            legend_y += 14

        # save if requested
        if save_to:
            save_to = Path(save_to)
            save_to.parent.mkdir(parents=True, exist_ok=True)
            base.save(save_to, quality=90)

        return base

    def create_planogram_description(
        self,
        config: Dict[str, Any]
    ) -> PlanogramDescription:
        """
        Create a planogram description from a dictionary configuration.
        This replaces the hardcoded method with a fully configurable approach.

        Args:
            config: Complete planogram configuration dictionary

        Returns:
            PlanogramDescription object ready for compliance checking
        """
        return self.factory.create_planogram_description(config)
