"""
3-Step Planogram Compliance Pipeline
Step 1: Object Detection (YOLO/ResNet)
Step 2: LLM Object Identification with Reference Images
Step 3: Planogram Comparison and Compliance Verification
"""
import os
from typing import List, Dict, Any, Optional, Union, Tuple
from collections import defaultdict, Counter
import unicodedata
import re
import traceback
from pathlib import Path
from datetime import datetime
import math
from matplotlib.pyplot import box
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
from navconfig.logging import logging
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
    "product_candidate": 100,
    "box_candidate": 101,
    "price_tag": 102,  # Make sure this is defined
    "shelf_region": 190,
}

PROMO_NAMES = {"promotional_candidate", "promotional_graphic"}


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

        # Endcap geometry defaults (can be tuned per program)
        self.endcap_aspect_ratio = 1.35   # width / height
        self.left_margin_ratio   = 0.12   # expand poster to endcap edges
        self.right_margin_ratio  = 0.12
        self.top_margin_ratio    = 0.02

        # Shelf split defaults: header/middle/bottom
        self.shelf_split = (0.40, 0.25, 0.35)  # sums to ~1.0
        # Useful elsewhere (price tag guardrails, etc.)
        self.label_strip_ratio = 0.06

        # CLIP for open-vocab and ref matching
        self.clip = CLIPModel.from_pretrained(
            "openai/clip-vit-base-patch32"
        ).to(device)
        self.proc = CLIPProcessor.from_pretrained(
            "openai/clip-vit-base-patch32"
        )
        self.logger = logging.getLogger('parrot.pipelines.planogram.RetailDetector')

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
                    cl.append(d)
                    placed = True
                    break
            if not placed:
                clusters.append([d])
        best_cluster = max(clusters, key=lambda cl: sum(x.area for x in cl))
        main = max(best_cluster, key=lambda d: d.area)
        keep.append(main)
        return keep, (main.x1, main.y1, main.x2, main.y2)

    def dedup_identified_by_model(self, items, iou_thr=0.30, center_thr=0.35):
        """
        Collapse duplicates of the same product model within the same shelf.
        Keeps highest-confidence, largest-area boxes.
        """
        def iou(a, b):
            ax1, ay1, ax2, ay2 = a.detection_box.x1, a.detection_box.y1, a.detection_box.x2, a.detection_box.y2
            bx1, by1, bx2, by2 = b.detection_box.x1, b.detection_box.y1, b.detection_box.x2, b.detection_box.y2
            ix1, iy1 = max(ax1, bx1), max(ay1, by1)
            ix2, iy2 = min(ax2, bx2), min(ay2, by2)
            if ix2 <= ix1 or iy2 <= iy1:
                return 0.0
            inter = (ix2-ix1)*(iy2-iy1)
            ua = (ax2-ax1)*(ay2-ay1) + (bx2-bx1)*(by2-by1) - inter
            return inter / max(ua, 1)

        def center_dist(a, b):
            axc = (a.detection_box.x1 + a.detection_box.x2) / 2.0
            ayc = (a.detection_box.y1 + a.detection_box.y2) / 2.0
            bxc = (b.detection_box.x1 + b.detection_box.x2) / 2.0
            byc = (b.detection_box.y1 + b.detection_box.y2) / 2.0
            return ((axc-bxc)**2 + (ayc-byc)**2) ** 0.5

        groups = defaultdict(list)
        for p in items:
            key = (p.product_model or p.product_type, p.shelf_location)
            groups[key].append(p)

        keep = []
        for key, grp in groups.items():
            grp = sorted(grp, key=lambda x: (x.confidence or 0, x.detection_box.area), reverse=True)
            accepted = []
            for cand in grp:
                too_close = False
                for acc in accepted:
                    if iou(cand, acc) >= iou_thr:
                        too_close = True
                        break
                    # distance gate using target width
                    w = acc.detection_box.x2 - acc.detection_box.x1
                    if center_dist(cand, acc) < w * center_thr:
                        too_close = True
                        break
                if not too_close:
                    accepted.append(cand)
            keep.extend(accepted)
        return keep

    # -------------------------- public entry ---------------------------------
    def detect(
        self,
        image: Image.Image,
        planogram: Optional[PlanogramDescription] = None,
        debug_raw: Optional[str] = None,
        debug_phase1: Optional[str] = None,
        debug_phases: Optional[str] = None,
    ):
        # 0) PIL -> enhanced -> numpy
        pil = image.convert("RGB") if isinstance(image, Image.Image) else Image.open(image).convert("RGB")
        enhanced = self._enhance(pil)
        img_array = np.array(enhanced)  # RGB

        h, w = img_array.shape[:2]

        # 1) Find the poster:
        ad_box = self._find_poster(img_array)

        # 2) endcap ROI
        sc = planogram.advertisement_endcap.size_constraints if planogram and planogram.advertisement_endcap else {}
        roi_box = self._roi_from_poster(ad_box, h, w, sc)
        rx1, ry1, rx2, ry2 = roi_box
        roi = img_array[ry1:ry2, rx1:rx2]

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
            w=w, h=h,
            planogram_config=planogram_config
        )
        # header_limit_y = min(v[0] for v in bands.values()) if bands else int(0.4 * h)
        # classification fallback limit = header bottom (or 40% of ROI height)
        if bands and "header" in bands:
            header_limit_y = bands["header"][1]
        else:
            roi_h = max(1, ry2 - ry1)
            header_limit_y = ry1 + int(0.4 * roi_h)

        if debug_raw:
            dbg = self._draw_phase_areas(img_array.copy(), yolo_props, roi_box)
            cv2.imwrite(
                debug_phases,
                cv2.cvtColor(dbg, cv2.COLOR_RGB2BGR)
            )
            dbg = self._draw_yolo(img_array.copy(), yolo_props, roi_box, shelf_lines)
            cv2.imwrite(
                debug_raw,
                cv2.cvtColor(dbg, cv2.COLOR_RGB2BGR)
            )

        # 5) classify YOLO → proposals (works w/ bands={}, header_limit_y above)
        proposals = self._classify_proposals(img_array, yolo_props, bands, header_limit_y, ad_box)
        # 6) shrink -> merge -> remove those fully inside the poster
        proposals = self._shrink(img_array, proposals)
        proposals = self._merge(proposals, iou_same=0.45)

        # 7) keep exactly ONE promo & align ROI to it
        proposals, promo_roi = self._consolidate_promos(proposals, ad_box)
        if promo_roi is not None:
            ad_box = promo_roi

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
            dbg = self._draw_phase1(img_array.copy(), roi_box, shelf_lines, proposals, ad_box)
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

    def _roi_from_poster(self, ad_box, h, w, size_constraints: Optional[dict] = None):
        """
        Compute endcap ROI using planogram size constraints.
        No detections are used here (YOLO needs this ROI).
        Returns (rx1, ry1, rx2, ry2) in full-image coords.
        """
        sc = self._normalize_size_constraints(size_constraints or {})
        roi_min_width_frac   = sc["roi_min_width_frac"]
        roi_max_width_frac   = sc["roi_max_width_frac"]
        fallback_left_frac   = sc["roi_fallback_left_frac"]
        fallback_right_frac  = sc["roi_fallback_right_frac"]
        left_margin_ratio    = sc["left_margin_ratio"]
        right_margin_ratio   = sc["right_margin_ratio"]
        top_margin_ratio     = sc["top_margin_ratio"]
        endcap_width_scale   = sc["endcap_width_scale"]

        # ---- Fallback when no poster ----
        if ad_box is None:
            rx1 = int(fallback_left_frac * w)
            rx2 = int(fallback_right_frac * w)
            ry1 = int(0.08 * h)
            ry2 = h - 1
            return (rx1, ry1, rx2, ry2)

        ax1, ay1, ax2, ay2 = ad_box
        aw, ah = max(1, ax2 - ax1), max(1, ay2 - ay1)
        cx = (ax1 + ax2) / 2.0

        # ---- Base width proposal (poster aware) ----
        width_from_margins = aw * (1.0 + left_margin_ratio + right_margin_ratio)
        width_from_scale   = aw * endcap_width_scale
        width_fallback     = (fallback_right_frac - fallback_left_frac) * w

        proposed = sorted([width_from_margins, width_from_scale, width_fallback])[1]
        min_w = roi_min_width_frac * w
        max_w = roi_max_width_frac * w
        target_w = int(max(min_w, min(max_w, proposed)))

        # ---- Center horizontally on poster (clipped) ----
        rx1 = int(max(0, min(w - 1, cx - target_w / 2)))
        rx2 = int(min(w - 1, rx1 + target_w))
        if rx2 - rx1 < target_w:
            rx1 = int(max(0, min(w - target_w, cx - target_w / 2)))
            rx2 = int(min(w - 1, rx1 + target_w))

        # ---- Vertical: start a hair above poster; go to bottom ----
        ry1 = int(max(0, ay1 - ah * top_margin_ratio - 0.02 * h))
        ry2 = h - 1
        return (rx1, ry1, rx2, ry2)

    def _normalize_size_constraints(self, sc: dict) -> dict:
        def _get(keys, default):
            for k in ([keys] if isinstance(keys, str) else keys):
                if isinstance(sc, dict) and k in sc:
                    return float(sc[k])
            return float(default)

        return {
            # ROI clamping (already used by _roi_from_poster, but safe to keep here)
            "roi_min_width_frac":     _get(["roi_min_width_frac","min_width_frac","min_w_frac"], 0.52),
            "roi_max_width_frac":     _get(["roi_max_width_frac","max_width_frac","max_w_frac"], 0.66),
            "roi_fallback_left_frac": _get(["roi_fallback_left_frac","fallback_left_frac"], 0.18),
            "roi_fallback_right_frac":_get(["roi_fallback_right_frac","fallback_right_frac"], 0.86),
            "left_margin_ratio":      _get(["left_margin_ratio","margin_left_ratio"], 0.40),
            "right_margin_ratio":     _get(["right_margin_ratio","margin_right_ratio"], 0.40),
            "top_margin_ratio":       _get("top_margin_ratio", 0.06),
            "endcap_width_scale":     _get(["endcap_width_scale","width_scale_from_poster"], 1.9),

            # Band rules
            "vertical_gap_frac":            _get("vertical_gap_frac", 0.006),  # gaps between bands (h fraction)
            "header_pad_frac":              _get("header_pad_frac", 0.00),     # tiny pad around promo

            # Middle sizing (robust target + minimum from promo)
            "middle_from_header_frac":      _get("middle_from_header_frac", 0.35),
            "middle_target_frac":           _get("middle_target_frac", 0.30),  # of (ROI - header)
            "middle_min_frac":              _get("middle_min_frac", 0.25),
            "middle_max_frac":              _get("middle_max_frac", 0.35),
            "middle_from_promo_min_frac":   _get("middle_from_promo_min_frac", 0.60),  # ≥60% of promo
            "middle_min_px":                _get("middle_min_px", 80),         # practical min for printers

            # Bottom sizing (from promo, with image-height cap)
            "bottom_from_promo_frac":       _get("bottom_from_promo_frac", 1.00),  # = promo height by default
            "bottom_max_image_frac":        _get("bottom_max_image_frac", 0.35),   # ≤ 35% of image height
            "bottom_min_px":                _get("bottom_min_px",  40),
        }

    # --------------------------- shelves -------------------------------------
    def _box_conf(self, p):
        """
        Return (x1,y1,x2,y2,conf) from an object-like or dict-like proposal.
        Expected class name is handled by the caller.
        """
        if hasattr(p, "x1"):
            return p.x1, p.y1, p.x2, p.y2, getattr(p, "confidence", 0.0)
        if hasattr(p, "get"):
            box = p.get("box", p)
            if isinstance(box, (list, tuple)) and len(box) >= 4:
                x1, y1, x2, y2 = box[:4]
            else:
                x1, y1, x2, y2 = box.get("x1"), box.get("y1"), box.get("x2"), box.get("y2")
            return x1, y1, x2, y2, float(p.get("confidence", 0.0))
        return None

    def _find_shelves(
        self,
        roi_box,                 # (rx1, ry1, rx2, ry2)
        ad_box,                  # (px1, py1, px2, py2) from _find_poster (may be None)
        h, w,
        planogram_config: dict = None  # Add planogram config parameter
    ):
        """
        Simplified shelf detection based on planogram configuration.
        Divides ROI proportionally based on shelf order and height settings.
        """
        rx1, ry1, rx2, ry2 = map(int, roi_box)
        roi_h = max(1, ry2 - ry1)

        # Get shelf configuration from planogram
        if not planogram_config or 'shelves' not in planogram_config:
            # Fallback to proportional layout if no config
            return self._find_shelves_proportional(roi_box, rx1, ry1, rx2, ry2, h)

        shelf_configs = planogram_config['shelves']
        num_shelves = len(shelf_configs)

        if num_shelves == 0:
            return [], {}

        # Calculate shelf heights based on configuration
        shelf_heights = []
        total_height_ratio = 0.0

        for shelf_config in shelf_configs:
            # Check if shelf has height attribute (0.30 = 30% of ROI)
            height_ratio = shelf_config.get('height_ratio', None)
            if height_ratio is None:
                # Default: equal division among all shelves
                height_ratio = 1.0 / num_shelves
            shelf_heights.append(height_ratio)
            total_height_ratio += height_ratio

        # Normalize heights to ensure they sum to 1.0
        if total_height_ratio != 1.0:
            shelf_heights = [h / total_height_ratio for h in shelf_heights]

        # Calculate actual pixel boundaries
        levels = []
        bands = {}
        current_y = ry1

        for i, (shelf_config, height_ratio) in enumerate(zip(shelf_configs, shelf_heights)):
            shelf_level = shelf_config['level']
            shelf_pixel_height = int(height_ratio * roi_h)

            # Ensure we don't exceed ROI boundaries
            shelf_bottom = min(ry2, current_y + shelf_pixel_height)

            # For the last shelf, extend to ROI bottom to avoid gaps
            if i == len(shelf_configs) - 1:
                shelf_bottom = ry2

            bands[shelf_level] = (current_y, shelf_bottom)
            levels.append(shelf_bottom)

            current_y = shelf_bottom

        # Remove the last level as it represents the bottom boundary
        if levels:
            levels = levels[:-1]

        self.logger.debug(
            f"📊 Simplified Shelves: {len(shelf_configs)} shelves configured, "
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
    def _yolo_props(self, roi: np.ndarray, rx1, ry1, detection_phases: Optional[List[Dict[str, Any]]] = None):
        """
        Multi-phase YOLO detection with configurable confidence levels and weighted scoring.

        REPLACES the existing _yolo_props method with enhanced two-phase detection.
        Returns proposals in the same format expected by existing _classify_proposals method.

        Args:
            roi: ROI image array
            rx1, ry1: ROI offset coordinates
            detection_phases: List of phase configurations. If None, uses default 2-phase approach.
        """
        if detection_phases is None:
            detection_phases = [
                {
                    "name": "poster_high",
                    "conf": 0.40,
                    "iou": 0.35,
                    "weight": 0.15,
                    "allow": ["person","tv","monitor","screen","display","billboard","poster"],
                    "min_area": 0.06,      # >= 6% of ROI
                    "region": "top40"      # only top 40% of ROI
                },  # backlit/TV/person near header
                {
                    "name": "high_confidence",
                    "conf": 0.05,
                    "iou": 0.20,
                    "weight": 0.70,
                    "description": "High confidence pass for clear objects"
                }, # printers + product boxes
                {
                    "name": "aggressive",
                    "conf": 0.003,
                    "iou": 0.15,
                    "weight": 0.15,
                    "description": "Selective aggressive pass for missed objects only"
                }
            ]

        try:
            H, W = roi.shape[:2]
            roi_area = H * W
            all_proposals = []

            print(f"\n🔄 Detection with Your Preferred Settings on ROI {W}x{H}")
            print("   " + "="*70)

            # Run both phases with your settings
            for phase_idx, phase in enumerate(detection_phases):
                phase_name = phase["name"]
                conf_thresh = phase["conf"]
                iou_thresh = phase["iou"]
                weight = phase["weight"]

                print(f"\n📡 Phase {phase_idx + 1}: {phase_name}")
                print(f"   Config: conf={conf_thresh}, iou={iou_thresh}, weight={weight}")

                r = self.yolo(roi, conf=conf_thresh, iou=iou_thresh, verbose=False)[0]

                if not hasattr(r, 'boxes') or r.boxes is None:
                    print(f"   📊 No boxes detected in {phase_name}")
                    continue

                xyxy = r.boxes.xyxy.cpu().numpy()
                confs = r.boxes.conf.cpu().numpy()
                classes = r.boxes.cls.cpu().numpy().astype(int)
                names = r.names

                print(f"   📊 Raw YOLO output: {len(xyxy)} detections")

                phase_count = 0
                for i, ((x1, y1, x2, y2), conf, cls_id) in enumerate(zip(xyxy, confs, classes)):
                    gx1, gy1, gx2, gy2 = int(x1) + rx1, int(y1) + ry1, int(x2) + rx1, int(y2) + ry1

                    width, height = x2 - x1, y2 - y1
                    if width <= 0 or height <= 0 or width < 8 or height < 8:
                        continue

                    if conf < conf_thresh:
                        continue

                    area = width * height
                    area_ratio = area / roi_area
                    aspect_ratio = width / max(height, 1)
                    yolo_class = names[cls_id]
                    min_area = phase.get("min_area")
                    if min_area and area_ratio < float(min_area):
                        continue

                    # allow-list
                    allow = phase.get("allow")
                    if allow and yolo_class not in allow:
                        continue

                    # Light filtering - let classification handle the heavy lifting
                    if (area_ratio >= 0.0008 and area_ratio <= 0.9 and
                        0.1 <= aspect_ratio <= 10.0 and conf >= conf_thresh):
                        # conf >= (0.12 if phase_name == "high_confidence" else 0.003)):

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
                            "phase": phase_name
                        }
                        all_proposals.append(proposal)
                        phase_count += 1

                print(f"   ✅ Kept {phase_count} detections from {phase_name}")

            # Light deduplication (let classification handle quality control)
            deduplicated = self._object_deduplication(all_proposals)

            print(f"\n📊 Detection Summary: {len(deduplicated)} total proposals")
            print("   Focus: Let classification phase handle object type distinction")

            return deduplicated

        except Exception as e:
            print(f"Detection failed: {e}")
            traceback.print_exc()
            return []

    def _analyze_visual_features(self, crop: Image.Image, area_ratio: float, aspect: float, yolo_class: str) -> Dict[str, Any]:
        """
        Enhanced visual feature analysis with skin tone and bottle detection
        """
        try:
            crop_array = np.array(crop)

            if crop_array.ndim == 3:
                r_mean = np.mean(crop_array[:, :, 0])
                g_mean = np.mean(crop_array[:, :, 1])
                b_mean = np.mean(crop_array[:, :, 2])

                # Blue dominance (for Epson boxes)
                is_blue_dominant = (b_mean > r_mean * 1.2 and b_mean > g_mean * 1.15 and b_mean > 100)

                # White/gray dominance (for printers)
                color_std = np.std([r_mean, g_mean, b_mean])
                avg_brightness = (r_mean + g_mean + b_mean) / 3
                is_white_gray = (color_std < 25 and avg_brightness > 140)

                # Skin tone detection (to avoid human fingers)
                is_skin_tone = (r_mean > g_mean * 0.9 and g_mean > b_mean * 1.1 and
                            r_mean > 120 and g_mean > 80 and b_mean < 120)

                # Bottle shape detection (tall and narrow)
                has_bottle_shape = (aspect < 0.6 and area_ratio < 0.02)

                # Person features (for promotional graphics)
                has_person_features = yolo_class == "person"

                brightness = avg_brightness / 255.0
            else:
                is_blue_dominant = False
                is_white_gray = False
                is_skin_tone = False
                has_bottle_shape = False
                has_person_features = False
                brightness = 0.5
                r_mean = g_mean = b_mean = 0

            # Edge analysis
            gray = cv2.cvtColor(crop_array, cv2.COLOR_RGB2GRAY) if crop_array.ndim == 3 else crop_array
            edges = cv2.Canny(gray, 50, 150)
            edge_density = np.sum(edges > 0) / edges.size

            return {
                "is_blue_dominant": is_blue_dominant,
                "is_white_gray": is_white_gray,
                "is_skin_tone": is_skin_tone,
                "has_bottle_shape": has_bottle_shape,
                "has_person_features": has_person_features,
                "brightness": brightness,
                "edge_density": edge_density,
                "r_mean": r_mean, "g_mean": g_mean, "b_mean": b_mean,
            }

        except Exception:
            return {
                "is_blue_dominant": False, "is_white_gray": False, "is_skin_tone": False,
                "has_bottle_shape": False, "has_person_features": False,
                "brightness": 0.5, "edge_density": 0.0,
                "r_mean": 0, "g_mean": 0, "b_mean": 0,
            }

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
            "tv": ["printer", "promotional_graphic"],
            "monitor": ["printer", "promotional_graphic"],
            "laptop": ["printer", "promotional_graphic"],
            "book": ["product_box", "printer"],
            "box": ["product_box"],
            "suitcase": ["product_box", "printer"],
            "bottle": ["ink_bottle", "price_tag"],
            "person": ["promotional_graphic"],
            "clock": ["small_object", "price_tag"],
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

            for kept in deduplicated:
                kept_box = kept["box"]
                kx1, ky1, kx2, ky2 = kept_box
                kept_area = (kx2 - kx1) * (ky2 - ky1)

                iou = self._calculate_iou_tuples(detection_box, kept_box)

                # Standard IoU-based deduplication (lowered threshold)
                if iou > 0.5:  # Reduced from 0.7 to 0.5
                    is_duplicate = True
                    break

                # Check if current detection is contained within a much larger kept detection
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
                        break

            if not is_duplicate and not is_contained:
                deduplicated.append(detection)

        print(f"   🔄 Deduplication: {len(sorted_detections)} → {len(deduplicated)} detections")
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

    def _safe_extract_crop(self, img: np.ndarray, x1: int, y1: int, x2: int, y2: int) -> Optional[Image.Image]:
        """
        Safely extract a crop from an image with full validation
        Returns None if crop would be invalid
        """
        H, W = img.shape[:2]

        # Clamp coordinates to image bounds
        x1_safe = max(0, min(W-1, int(x1)))
        x2_safe = max(x1_safe + 8, min(W, int(x2)))
        y1_safe = max(0, min(H-1, int(y1)))
        y2_safe = max(y1_safe + 8, min(H, int(y2)))

        # Validate final dimensions
        crop_width = x2_safe - x1_safe
        crop_height = y2_safe - y1_safe

        if crop_width <= 0 or crop_height <= 0 or crop_width < 8 or crop_height < 8:
            return None

        try:
            crop_array = img[y1_safe:y2_safe, x1_safe:x2_safe]
            if crop_array.size == 0:
                return None

            crop = Image.fromarray(crop_array)

            if crop.width == 0 or crop.height == 0:
                return None

            return crop

        except Exception:
            return None

    def _iou_xyxy(self, a, b) -> float:
        ax1, ay1, ax2, ay2 = a
        bx1, by1, bx2, by2 = b
        ix1, iy1 = max(ax1, bx1), max(ay1, by1)
        ix2, iy2 = min(ax2, bx2), min(ay2, by2)
        if ix2 <= ix1 or iy2 <= iy1:
            return 0.0
        inter = (ix2 - ix1) * (iy2 - iy1)
        aarea = (ax2 - ax1) * (ay2 - ay1)
        barea = (bx2 - bx1) * (by2 - by1)
        return inter / max(1.0, aarea + barea - inter)

    # ------------------- OCR + CLIP preselection -----------------------------
    def _classify_proposals(self, img, props, bands, header_limit_y, ad_box=None):
        """
        classification with better visual analysis for accurate object type detection.

        Focus on distinguishing:
        - White printers (compact, square-ish) → product_candidate
        - Blue boxes (tall/wide, colorful) → box_candidate
        - Large banners (wide, in header) → promotional_candidate
        - Small tags (very small, specific aspect ratio) → price_tag
        """
        H, W = img.shape[:2]
        out = []
        text_feats = self.text_feats

        print(f"\n🎯 Classification with Visual Analysis:")
        print("   " + "="*60)

        # STEP 1: Find clearly detected high-confidence product boxes for baseline
        high_confidence_boxes = []
        for p in props:
            if (p.get("phase") == "high_confidence" and
                p.get("weighted_conf", 0) > 0.5 and
                p.get("area_ratio", 0) > 0.02):
                high_confidence_boxes.append(p)

        min_box_confidence = min(
            [p.get("weighted_conf", 0) for p in high_confidence_boxes],
            default=0.3
        )
        print(
            f"   📊 Found {len(high_confidence_boxes)} high-confidence boxes, min confidence: {min_box_confidence:.3f}"
        )

        for p in props:
            x1, y1, x2, y2 = p["box"]
            base_conf = p.get("weighted_conf", p.get("yolo_conf", 0.5))
            yolo_class = p["yolo_label"]
            phase = p.get("phase", "unknown")
            orientation = p.get("orientation", self._detect_orientation(x1, y1, x2, y2))
            raw_index = p.get("raw_index", "?")

            width = x2 - x1
            height = y2 - y1
            area = width * height
            area_ratio = area / (H * W)
            aspect = width / max(height, 1)

            # Enhanced visual analysis for classification
            try:
                crop = img[max(0, y1):min(H, y2), max(0, x1):min(W, x2)]
                visual_analysis = self._analyze_visual_features(crop)
            except Exception:
                visual_analysis = {}

            # CLIP scoring
            s_poster = s_printer = s_box = 0.4
            try:
                if self.proc is not None and crop.size > 0:
                    crop_rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB) if len(crop.shape) == 3 else crop
                    crop_pil = Image.fromarray(crop_rgb)
                    crop_enhanced = self._enhance(crop_pil)

                    with torch.no_grad():
                        ip = self.proc(images=crop_enhanced, return_tensors="pt").to(self.device)
                        img_feat = self.clip.get_image_features(**ip)
                        img_feat = img_feat / img_feat.norm(dim=-1, keepdim=True)
                        text_sims = (img_feat @ text_feats.T).squeeze().tolist()
                        s_poster, s_printer, s_box = float(text_sims[0]), float(text_sims[1]), float(text_sims[2])
            except Exception:
                pass

            # Reference matching
            ref_match_score = 0.0
            if self.ref_prod_feats:
                try:
                    with torch.no_grad():
                        ref_scores = [float((img_feat @ ref_feat.T).squeeze()) for ref_feat in self.ref_prod_feats]
                        ref_match_score = max(ref_scores) if ref_scores else 0.0
                        s_printer = max(s_printer, ref_match_score)
                except Exception:
                    pass

            # POSITION ANALYSIS
            center_y = (y1 + y2) / 2

            # If we have shelf bands, use them; otherwise use header_limit_y
            if bands and "header" in bands:
                actual_header_limit = bands["header"][1]  # y2 of header band = first shelf line
                first_line_y = bands["header"][1]  # y2 of the 'header' band
            else:
                actual_header_limit = header_limit_y
                first_line_y = header_limit_y

            in_header = (y2 <= first_line_y + 2)

            ad_iou = 0.0
            if ad_box is not None:
                ad_iou = self._iou_xyxy((x1, y1, x2, y2), ad_box)

            # FIX 1: CORRECTED promotional graphic assignment based on area overlap
            promotional_assignment = self._get_promotional_assignment(x1, y1, x2, y2, bands, ad_box, yolo_class, area_ratio, aspect)
            if promotional_assignment["is_promotional"]:
                cname = "promotional_candidate"
                score = max(0.85, base_conf)
                out.append(
                    DetectionBox(
                        x1=int(x1), y1=int(y1), x2=int(x2), y2=int(y2),
                        confidence=float(min(1.0, score)),
                        class_id=103,  # promotional_candidate
                        class_name=cname,
                        area=int(area)
                    )
                )
                print(
                    f"   #{raw_index:2}: {yolo_class:10s} {orientation:8s} → {cname:18s} "
                    f"conf={score:.3f} ({promotional_assignment['reason']})"
                )
                continue

            # Skip overlapping promotional content (legacy logic)
            if in_header and ad_iou >= 0.65:
                cname = "promotional_candidate"
                score = max(0.9, base_conf)
                out.append(
                    DetectionBox(
                        x1=int(x1), y1=int(y1), x2=int(x2), y2=int(y2),
                        confidence=float(min(1.0, score)),
                        class_id=103,
                        class_name=cname,
                        area=int(area)
                    )
                )
                print(
                    f"   #{raw_index:2}: {yolo_class:10s} {orientation:8s} → {cname:18s} "
                    f"conf={score:.3f} (person in promotional area)"
                )
                continue

            # Check for large promotional objects that span multiple areas
            is_large_promotional = (
                area_ratio > 0.15 and aspect > 1.8 and (y1 < actual_header_limit or area_ratio > 0.25)
            )

            # If a detection substantially overlaps the poster, treat as promotional
            if ad_iou >= 0.50 and (yolo_class == "person" or aspect > 1.6 or area_ratio > 0.15):
                cname = "promotional_candidate"
                score = max(0.9, base_conf)
                decision_reason = "overlaps poster (IoU≥0.5)"
                clamped_confidence = float(min(1.0, max(0.0, score)))
                out.append(
                    DetectionBox(
                        x1=int(x1), y1=int(y1), x2=int(x2), y2=int(y2),
                        confidence=clamped_confidence,
                        class_id=103, class_name=cname, area=int(area)
                    )
                )
                print(
                    f"   #{raw_index:2}: {yolo_class:10s} {orientation:8s} → {cname:18s} "
                    f"conf={clamped_confidence:.3f} (poster-overlap)"
                )
                continue

            HEADER_MIN_AREA = 0.02  # 2%
            decision_reason = ""

            if center_y < actual_header_limit or is_large_promotional:
                # HEADER AREA: Enhanced promotional detection
                if area_ratio > 0.15 and aspect > 1.5:
                    cname = "promotional_candidate"
                    score = max(0.85, s_poster, base_conf)
                    decision_reason = f"large banner (area={area_ratio:.3f}, aspect={aspect:.1f})"
                elif yolo_class == "person" or visual_analysis.get("has_person_features", False):
                    cname = "promotional_candidate"
                    score = max(0.90, s_poster, base_conf)
                    decision_reason = "person in promotional area"
                elif area_ratio > 0.05 or is_large_promotional:
                    cname = "promotional_candidate"
                    score = max(0.80, s_poster, base_conf)
                    decision_reason = f"promotional object in header"
                elif area_ratio < HEADER_MIN_AREA and (ad_iou < 0.65):
                    # Very small objects in header - likely noise
                    print(f"   ⚠️  Skipping #{raw_index}: Too small for header ({area_ratio:.4f})")
                    continue
                print(f"Decision reason: {decision_reason}")

            else:
                # PRODUCT AREAS: CORRECTED classification logic

                # FIX 2: Enhanced price tag detection FIRST (before other scoring)
                if self._is_likely_price_tag(width, height, area_ratio, yolo_class, visual_analysis):
                    cname = "price_tag"
                    score = 0.8
                    out.append(
                        DetectionBox(
                            x1=int(x1), y1=int(y1), x2=int(x2), y2=int(y2),
                            confidence=float(score),
                            class_id=102,  # price_tag
                            class_name=cname,
                            area=int(area)
                        )
                    )
                    print(f"   #{raw_index:2}: {yolo_class:10s} {orientation:8s} → {cname:18s} conf={score:.3f} (detected as price tag)")
                    continue

                # FIX 3: CORRECTED scoring system for box vs printer distinction
                # Initialize base scores (RESTORED original balance)
                scores = {
                    "promotional_candidate": s_poster * 0.2,
                    "product_candidate": s_printer,
                    "box_candidate": s_box,
                    "price_tag": 0.0,
                    "ink_bottle": 0.3
                }
                yolo_cls = (yolo_class or "").lower()

                # Filter non-retail objects with very low confidence
                if base_conf < 0.01 and any(k in yolo_cls for k in ("keyboard", "mouse", "remote", "cell phone")):
                    print(
                        f"   ⚠️  Skipping #{raw_index}: non-retail {yolo_class} conf={base_conf:.3f}"
                    )
                    continue

                # SHELF POSITION ANALYSIS
                shelf_level = self._determine_shelf_level(center_y, bands)

                # CORRECTED YOLO class bias - restored proper balance
                if any(k in yolo_cls for k in ("suitcase", "book", "box", "backpack", "handbag", "luggage")):
                    if shelf_level in ["bottom", "middle"]:  # Lower shelves = boxes
                        scores["box_candidate"] *= 2.0  # RESTORED original strong bias for boxes
                        if "book" in yolo_cls:
                            scores["box_candidate"] *= 1.8  # Strong book → box association
                        decision_reason = f"YOLO box-like class in lower shelf: {yolo_class}"
                    elif shelf_level == "top":  # Top shelf = could be printers
                        scores["box_candidate"] *= 1.3  # Moderate box bias
                        scores["product_candidate"] *= 1.2  # Give printers a fighting chance
                        decision_reason = f"YOLO box-like class in top shelf: {yolo_class}"
                    else:
                        # Header or unknown - be conservative
                        scores["box_candidate"] *= 1.1
                        scores["product_candidate"] *= 1.1
                        decision_reason = f"YOLO box-like class in upper area: {yolo_class}"

                if "microwave" in yolo_cls:  # YOLO-11 quirk for printers
                    scores["product_candidate"] *= 1.5  # Strong printer bias for microwaves

                # CONFIDENCE FILTERING for aggressive detections
                if phase == "aggressive" and base_conf < 0.15:
                    high_conf_overlap = any(
                        self._iou_xyxy((x1, y1, x2, y2), (h["box"])) > 0.7
                        for h in high_confidence_boxes
                    )
                    if high_conf_overlap:
                        print(f"   ⚠️  Skipping #{raw_index}: Weak aggressive detection overlaps strong box")
                        continue

                # SIZE-BASED ADJUSTMENTS (CORRECTED to favor boxes for large objects)
                if area_ratio > 0.08:  # Large objects
                    if shelf_level in ["bottom", "middle"]:
                        scores["box_candidate"] *= 1.5  # Large objects in lower shelves = boxes
                        scores["product_candidate"] *= 0.9  # Reduce printer score
                    else:
                        scores["product_candidate"] *= 1.3  # Large objects in top = printers
                        scores["box_candidate"] *= 1.1  # Moderate box score
                elif area_ratio < 0.008:  # Small objects
                    scores["price_tag"] *= 1.5
                    scores["product_candidate"] *= 0.7
                    scores["box_candidate"] *= 0.8

                # VISUAL FEATURE ADJUSTMENTS
                if visual_analysis.get("is_blue_dominant", False):
                    scores["box_candidate"] *= 1.6  # Blue = product boxes
                    scores["product_candidate"] *= 0.8  # Less likely to be printers
                if visual_analysis.get("is_white_gray", False):
                    scores["product_candidate"] *= 1.4  # White/gray = printers
                    scores["price_tag"] *= 1.2  # Price tags are often white
                    scores["box_candidate"] *= 0.9  # Less likely to be blue boxes

                # ASPECT RATIO ADJUSTMENTS
                if aspect > 2.0:  # Very wide objects
                    scores["promotional_candidate"] *= 1.5
                    scores["price_tag"] *= 0.5
                elif aspect < 0.5:  # Very tall objects
                    scores["box_candidate"] *= 1.2
                    scores["price_tag"] *= 0.8

                # Final decision
                best_class = max(scores.keys(), key=lambda k: scores[k])
                best_score = scores[best_class]

                if best_score < 0.1:
                    print(f"   ⚠️  Skipping #{raw_index}: All scores too low (max={best_score:.3f})")
                    continue

                # Map to final class names
                class_mapping = {
                    "product_candidate": "product_candidate",
                    "box_candidate": "box_candidate",
                    "promotional_candidate": "promotional_candidate",
                    "price_tag": "price_tag",
                    "ink_bottle": "ink_bottle"
                }

                class_id_mapping = {
                    "product_candidate": 100,
                    "box_candidate": 101,
                    "promotional_candidate": 103,
                    "price_tag": 102,
                    "ink_bottle": 104
                }

                final_class = class_mapping[best_class]
                final_score = min(1.0, best_score)

                out.append(
                    DetectionBox(
                        x1=int(x1), y1=int(y1), x2=int(x2), y2=int(y2),
                        confidence=float(final_score),
                        class_id=class_id_mapping[best_class],
                        class_name=final_class,
                        area=int(area)
                    )
                )

                print(
                    f"   #{raw_index:2}: {yolo_class:10s} {orientation:8s} → {final_class:18s} "
                    f"conf={final_score:.3f} ({yolo_class}({orientation})→{final_class}@{shelf_level})"
                )

        return out

    def _get_promotional_assignment(self, x1, y1, x2, y2, bands, ad_box, yolo_class, area_ratio, aspect):
        """
        Promotional graphic assignment based on area overlap with header
        """
        if not bands or "header" not in bands:
            return {"is_promotional": False, "reason": "no header band defined"}

        # Calculate area overlap with header shelf
        header_y1, header_y2 = bands["header"]

        # Calculate intersection with header band
        intersection_y1 = max(y1, header_y1)
        intersection_y2 = min(y2, header_y2)

        if intersection_y2 <= intersection_y1:
            header_overlap_ratio = 0.0
        else:
            object_height = y2 - y1
            intersection_height = intersection_y2 - intersection_y1
            header_overlap_ratio = intersection_height / max(object_height, 1)

        # Calculate IoU with ad_box if available
        ad_iou = 0.0
        if ad_box is not None:
            ad_iou = self._iou_xyxy((x1, y1, x2, y2), ad_box)

        # More aggressive assignment to header based on different criteria
        reasons = []

        # Criterion 1: High header overlap
        if header_overlap_ratio > 0.5:  # Lowered from 0.6 to catch more cases
            reasons.append(f"header_overlap={header_overlap_ratio:.2f}")

        # Criterion 2: Large banner with some header presence
        if area_ratio > 0.1 and aspect > 1.5 and header_overlap_ratio > 0.2:  # Lowered thresholds
            reasons.append(
                f"large_banner(area={area_ratio:.3f},aspect={aspect:.1f},header={header_overlap_ratio:.2f})"
            )

        # Criterion 3: Person detection with header presence
        if yolo_class == "person" and header_overlap_ratio > 0.3:  # Lowered from 0.4
            reasons.append(
                f"person_in_header(overlap={header_overlap_ratio:.2f})"
            )

        # Criterion 4: Strong ad_box overlap
        if ad_iou > 0.4:  # Lowered from 0.5
            reasons.append(f"ad_box_overlap(iou={ad_iou:.2f})")

        # Criterion 5: TV/monitor classes that are likely promotional
        yolo_cls = (yolo_class or "").lower()
        if any(cls in yolo_cls for cls in ["tv", "monitor", "laptop"]) and header_overlap_ratio > 0.2:
            reasons.append(f"display_device_in_header({yolo_class})")

        # Criterion 6: Very large objects that span header (regardless of center)
        if area_ratio > 0.2 and header_overlap_ratio > 0.1:  # Any presence in header for very large objects
            reasons.append(f"very_large_object(area={area_ratio:.3f})")

        is_promotional = len(reasons) > 0
        reason = "; ".join(reasons) if reasons else "not promotional"

        if is_promotional:
            print(f"   📍 Promotional detected: {reason}")

        return {
            "is_promotional": is_promotional,
            "reason": reason,
            "header_overlap_ratio": header_overlap_ratio,
            "ad_iou": ad_iou
        }

    def _is_likely_price_tag(self, width, height, area_ratio, yolo_class, visual_analysis):
        """
        FIX 2: Enhanced price tag detection logic (unchanged - working correctly)
        """
        # Size-based criteria (stricter than before)
        size_criteria = (
            width <= 120 and
            height <= 90 and
            area_ratio <= 0.012
        )

        # Visual criteria
        is_white_or_light = visual_analysis.get("is_white_gray", False) or visual_analysis.get("brightness", 0.5) > 0.7
        is_not_blue_box = not visual_analysis.get("is_blue_dominant", False)

        # YOLO class criteria - be more specific about what could be price tags
        yolo_cls = (yolo_class or "").lower()
        tag_friendly_classes = ["book", "clock", "bottle", "mouse", "remote", "cell phone"]
        is_tag_friendly_yolo = any(cls in yolo_cls for cls in tag_friendly_classes)

        # Aspect ratio criteria - price tags are usually not extremely elongated
        aspect_ratio = width / max(height, 1)
        reasonable_aspect = 0.3 <= aspect_ratio <= 3.0

        # Combine criteria
        is_price_tag = (
            size_criteria and
            is_not_blue_box and  # Not a blue product box
            reasonable_aspect and
            (is_white_or_light or is_tag_friendly_yolo)
        )

        return is_price_tag

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

    def _merge(self, dets: List[DetectionBox], iou_same=0.3) -> List[DetectionBox]:  # Reduced from 0.45 to 0.3
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
        planogram_description: Optional[PlanogramDescription] = None,
        confidence_threshold: float = 0.5
    ):
        self.logger.debug("Step 1: Detecting generic shapes and boundaries...")

        pil_image = Image.open(image) if isinstance(image, (str, Path)) else image

        det_out = self.shape_detector.detect(
            image=pil_image,
            planogram=planogram_description,
            debug_raw="/tmp/data/yolo_raw_debug.png",
            debug_phase1="/tmp/data/yolo_phase1_debug.png",
            debug_phases="/tmp/data/yolo_phases_debug.png",
        )

        shelves = det_out["shelves"]          # {'top': DetectionBox(...), 'middle': ...}
        proposals    = det_out["proposals"]        # List[DetectionBox]

        print("PROPOSALS:", proposals)
        print("SHELVES:", shelves)

        # --- IMPORTANT: use Phase-1 shelf bands (not %-of-image buckets) ---
        shelf_regions = self._materialize_shelf_regions(shelves, proposals)

        detections = list(proposals)

        self.logger.debug(
            "Found %d objects in %d shelf regions", len(detections), len(shelf_regions)
        )

        # Recover price tags and re-map to the same Phase-1 shelves
        try:
            tag_dets = self._recover_price_tags(pil_image, shelf_regions)
            if tag_dets:
                detections.extend(tag_dets)
                shelf_regions = self._materialize_shelf_regions(shelves, detections)
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

        # Header: anything fully above the header shelf band
        if "header" in shelves_dict:
            cut_y = shelves_dict["header"].y1
            # Anything fully above the top band OR any promotional that touches the header area.
            header_objs = [
                d for d in dets
                if (d.y2 <= cut_y) or (d.class_name == "promotional_candidate" and d.y1 < cut_y + 5)
            ]
            if header_objs:
                x1 = min(o.x1 for o in header_objs)
                y1 = min(o.y1 for o in header_objs)
                x2 = max(o.x2 for o in header_objs)
                y2 = cut_y
                bbox = DetectionBox(
                    x1=x1, y1=y1, x2=x2, y2=y2,
                    confidence=1.0,
                    class_id=190,
                    class_name="shelf_region",
                    area=(x2-x1)*(y2-y1)
                )
                regions.append(
                    ShelfRegion(
                        shelf_id="header",
                        bbox=bbox,
                        level="header",
                        objects=header_objs
                    )
                )

        for level in ["header", "middle", "bottom"]:
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

    def _organize_into_shelves(
        self,
        detections: List[DetectionBox],
        image_size: Tuple[int, int]
    ) -> List[ShelfRegion]:
        """
        Organize detections into shelf regions with non-overlapping boundaries
        """
        width, height = image_size
        shelf_regions = []

        header_objects = []
        top_objects = []
        middle_objects = []
        bottom_objects = []

        for d in detections:
            center_y = (d.y1 + d.y2) / 2
            y_ratio = center_y / height

            if (d.class_name == "promotional_candidate" or
                (y_ratio < 0.3 and d.area > 0.1 * width * height)):
                # Large objects in upper area OR promotional candidates go to header
                header_objects.append(d)
            elif y_ratio < 0.5:
                # Upper area products go to top shelf
                top_objects.append(d)
            elif y_ratio < 0.75:
                # Middle area
                middle_objects.append(d)
            else:
                # Lower area
                bottom_objects.append(d)

        # Create shelf regions
        if header_objects:
            shelf_regions.append(self._create_shelf_region("header", "header", header_objects))
        if top_objects:
            shelf_regions.append(self._create_shelf_region("top_shelf", "top", top_objects))
        if middle_objects:
            shelf_regions.append(self._create_shelf_region("middle_shelf", "middle", middle_objects))
        if bottom_objects:
            shelf_regions.append(self._create_shelf_region("bottom_shelf", "bottom", bottom_objects))

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
                    for product in identified_products:
                        if product.product_type == "promotional_graphic":
                            if lines := await self._extract_text_from_region(image, product.detection_box):
                                snippet = " ".join(lines)[:120]
                                product.visual_features = (product.visual_features or []) + [f"ocr:{snippet}"]
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
                            if product.detection_id and 1 <= product.detection_id <= len(effective_dets):
                                det_idx = product.detection_id - 1
                                product.detection_box = effective_dets[det_idx]

                                # ⬅️ Do OCR *after* we have the box
                                if product.product_type == "promotional_graphic":
                                    lines = await self._extract_text_from_region(image, product.detection_box)
                                    if lines:
                                        snippet = " ".join(lines)[:120]
                                        product.visual_features = (product.visual_features or []) + [f"ocr:{snippet}"]

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
            elif p.product_type == "promotional_graphic":
                if lines := await self._extract_text_from_region(image, p.detection_box):
                    snippet = " ".join(lines)[:160]
                    p.visual_features = (p.visual_features or []) + [f"ocr:{snippet}"]
                    joined = " ".join(lines)
                    if norm := self._normalize_ocr_text(joined):
                        p.visual_features.append(norm)
                        # also feed per-line normals (helps 'contains' on shorter phrases)
                        for ln in lines:
                            if ln and (nln := self._normalize_ocr_text(ln)) and nln not in p.visual_features:
                                p.visual_features.append(nln)
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
1. **PRINTERS (actual devices)**: Use model name only (e.g., "ET-2980", "ET-3950", "ET-4950")
   - Look for: White/gray color, compact square shape, LCD screens, physical ink tanks, control panels
   - Typically positioned on shelves, not stacked

2. **PRODUCT BOXES**: Use model name + " box" (e.g., "ET-2980 box", "ET-3950 box", "ET-4950 box")
   - Look for: Blue packaging, product images on box, stacked arrangement, larger rectangular shape
   - Contains pictures of the printer device, not the device itself

3. **KEY DISTINCTION**: If you see the actual printer device (white/gray with visible controls/tanks) = "printer"
   If you see packaging with printer images on it = "product_box"

4. For promotional graphics: Use descriptive name (e.g., "Epson EcoTank Advertisement") and look for promotional text.
5. For price/fact tags: Use "price tag" or "fact tag"
6. always set product_type accordingly: printer, product_box, promotional_graphic, fact_tag, no matter if was classified differently.
7. If two objects overlap, but are the same product_type, ignore the smaller one (likely a duplicate detection).

VISUAL IDENTIFICATION GUIDE:
- **Blue rectangular objects with product imagery** → product_box
- **White/gray compact devices with control panels** → printer
- **Large colorful banners with text/people** → promotional_graphic
- **Small white rectangular labels** → fact_tag


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
                    ocr_blocks = []
                    for promo in promos:
                        if getattr(promo, "visual_features", None):
                            all_features.extend(promo.visual_features)
                            for feat in promo.visual_features:
                                if isinstance(feat, str) and feat.startswith("ocr:"):
                                    ocr_blocks.append(feat[4:].strip())

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

            # For non-header shelves without text requirements, don't penalize
            elif shelf_level != "header":
                overall_text_ok = True  # Don't require text compliance on product shelves
                text_score = 1.0

            # Determine compliance threshold
            threshold = getattr(
                shelf_cfg,
                "compliance_threshold",
                planogram_description.global_compliance_threshold or 0.8
            )

            # FIX 4: Better status determination logic
            # Allow minor unexpected (ink bottles, price tags)
            major_unexpected = [
                p for p in unexpected if not any(
                    word in p.lower() for word in ["ink bottle", "price tag", "502"]
                )
            ]
            # For product shelves (non-header), focus on product compliance
            if shelf_level != "header":
                if basic_score >= threshold and not major_unexpected:
                    status = ComplianceStatus.COMPLIANT
                elif basic_score == 0.0:
                    status = ComplianceStatus.MISSING
                else:
                    status = ComplianceStatus.NON_COMPLIANT
            else:
                # For header shelf, require both product and text compliance
                if basic_score >= threshold and not major_unexpected and overall_text_ok:
                    status = ComplianceStatus.COMPLIANT
                elif basic_score == 0.0:
                    status = ComplianceStatus.MISSING
                else:
                    status = ComplianceStatus.NON_COMPLIANT

            # Calculate combined score with appropriate weighting
            if shelf_level == "header":
                # Header: Balance product and text compliance
                endcap = planogram_description.advertisement_endcap
                weights = {
                    "product_compliance": endcap.product_weight,
                    "text_compliance": endcap.text_weight
                }
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

        # Just handle the essential mappings
        if "promotional" in name or "advertisement" in name or "graphic" in name:
            return "promotional_graphic"

        # Map various representations to standard names
        # TODO: get the product list from planogram_config
        # example: "ET-2980", "ET-2980 box", "Epson EcoTank Advertisement", "price tag", etc.
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
            image, planogram_description, self.confidence_threshold
        )

        self.logger.debug(
            f"Found {len(detections)} objects in {len(shelf_regions)} shelf regions"
        )

        self.logger.info("Step 2: Identifying objects with LLM...")
        identified_products = await self.identify_objects_with_references(
            image, detections, shelf_regions, self.reference_images
        )

        print(identified_products)

        # De-duplicate promotional_graphic (keep the largest)
        promos = [p for p in identified_products if p.product_type == "promotional_graphic" and p.detection_box]
        if len(promos) > 1:
            keep = max(promos, key=lambda p: p.detection_box.area)
            identified_products = [
                p for p in identified_products if p.product_type != "promotional_graphic"
            ] + [keep]

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
        def _norm_box(x1, y1, x2, y2):
            x1, x2 = (int(x1), int(x2))
            y1, y2 = (int(y1), int(y2))
            return min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)

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
                x1, y1, x2, y2 = _norm_box(x1, y1, x2, y2)
                draw.rectangle([x1, y1, x2, y2], outline=(255, 255, 0), width=3)
                _txt(draw, (x1+3, max(0, y1-14)), f"SHELF {sr.level}", fill=(0, 0, 0), bg=(255, 255, 0))

        # --- detections (thin) ---
        if mode in ("detections", "both") and detections:
            for i, d in enumerate(detections, start=1):
                x1, y1, x2, y2 = _clip(d.x1, d.y1, d.x2, d.y2)
                x1, y1, x2, y2 = _norm_box(x1, y1, x2, y2)
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
