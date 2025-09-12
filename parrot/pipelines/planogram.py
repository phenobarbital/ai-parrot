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
from enum import Enum
import unicodedata
import re
import traceback
from pathlib import Path
from datetime import datetime
import math
import io
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
from google.genai.errors import ServerError
from navconfig.logging import logging
from .abstract import AbstractPipeline
from ..models.detections import (
    DetectionBox,
    Detections,
    ShelfRegion,
    IdentifiedProduct,
    PlanogramDescription,
    PlanogramDescriptionFactory,
)
from ..clients.google import GoogleGenAIClient, GoogleModel
from ..models.compliance import (
    ComplianceResult,
    ComplianceStatus,
    TextComplianceResult,
    TextMatcher,
    BrandComplianceResult
)
try:
    from ultralytics import YOLO  # yolo12m works with this API
except Exception:
    YOLO = None


def clean_ocr_text(text: str) -> str:
    """
    Cleans an OCR string by removing non-alphanumeric characters (except spaces)
    and normalizing whitespace.

    Args:
        text: The raw OCR output string.

    Returns:
        A cleaned-up string.
    """
    if not text:
        return ""

    # 1. Remove all characters that are NOT letters, numbers, or whitespace
    #    [^a-zA-Z0-9\s] means "match any character that is not in this set"
    only_alnum_and_space = re.sub(r'[^a-zA-Z0-9\s-]', '', text)
    # 2. Normalize whitespace: collapse multiple spaces into one, and trim ends
    cleaned_text = " ".join(only_alnum_and_space.split())
    return cleaned_text

CID = {
    "promotional_candidate": 103,
    "product_candidate": 100,
    "box_candidate": 101,
    "price_tag": 102,
    "shelf_region": 190,
    "brand_logo": 105,
    "poster_text": 106,
}


PROMO_NAMES = {"promotional_candidate", "promotional_graphic"}

# An Enum to constrain the classification to only the types we want
class ObjectType(str, Enum):
    PRODUCT_CANDIDATE = "product_candidate"
    BOX_CANDIDATE = "box_candidate"
    UNCLEAR = "unclear"

class VerificationResult(BaseModel):
    """The result of verifying a single cropped object image."""
    object_type: ObjectType = Field(..., description="The classification of the object in the image.")
    visible_text: Optional[str] = Field(
        None,
        description="Any clearly visible text extracted from the image, cleaned up. Null if no legible text is found."
    )

def _clamp(W,H,x1,y1,x2,y2):
    x1,x2 = int(max(0,min(W-1,min(x1,x2)))), int(max(0,min(W-1,max(x1,x2))))
    y1,y2 = int(max(0,min(H-1,min(y1,y2)))), int(max(0,min(H-1,max(y1,y2))))
    return x1, y1, x2, y2


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
        llm: Any = None,
        conf: float = 0.15,
        iou: float = 0.5,
        device: str = "cuda" if torch.cuda.is_available() else "cpu",
        reference_images: Optional[List[str]] = None,  # first is the poster
        **kwargs
    ):
        if isinstance(yolo_model, str):
            assert YOLO is not None, "ultralytics is required"
            self.yolo = YOLO(yolo_model)
        else:
            self.yolo = yolo_model
        self.conf = conf
        self.iou = iou
        self.device = device
        self.llm = llm
        self.google = GoogleGenAIClient(
            model=GoogleModel.GEMINI_2_5_FLASH,
            temperature=0.0,
            max_retries=2,
            timeout=20
        )
        # Endcap geometry defaults (can be tuned per program)
        self.endcap_aspect_ratio = 1.35   # width / height
        self.left_margin_ratio   = kwargs.get('left_margin_ratio', 0.01)
        self.right_margin_ratio  = kwargs.get('right_margin_ratio', 0.03)
        self.top_margin_ratio    = kwargs.get('top_margin_ratio', 0.02)

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
            "Printer device",
            "Epson Product cardboard box",
            "Price Tag",
            "Cartridge ink bottle",
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

    # -------------------------- public entry ---------------------------------
    async def detect(
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
        debug_poster_path = debug_raw.replace(".png", "_poster_debug.png") if debug_raw else None
        endcap, ad, brand, panel_text = await self._find_poster(
            enhanced, planogram, debug_poster_path
        )
        # Check if detections are valid before proceeding
        if not endcap or not ad:
            print("ERROR: Failed to get required detections.")
            return # or raise an exception

        # 2) endcap ROI
        roi_box = endcap.bbox.get_pixel_coordinates(width=w, height=h)
        ad_box = ad.bbox.get_pixel_coordinates(width=w, height=h)

        # Unpack the Pixel coordinates
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

        if debug_raw:
            dbg = self._draw_phase_areas(img_array.copy(), yolo_props, roi_box)
            if debug_phases:
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
        proposals = await self._classify_proposals(
            img_array,
            yolo_props,
            bands,
            header_limit_y,
            ad_box
        )
        # 6) shrink -> merge -> remove those fully inside the poster
        # proposals = self._shrink(img_array, proposals)
        # proposals = self._merge(proposals, iou_same=0.45)

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

        # 7) keep exactly ONE promo & align ROI to it
        # proposals, promo_roi = self._consolidate_promos(proposals, ad_box)
        # if promo_roi is not None:
        #     ad_box = promo_roi

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

    def _coerce_bbox(self, bbox, W, H):
        if bbox is None:
            return None
        if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
            x1, y1, x2, y2 = map(float, bbox)
        elif isinstance(bbox, dict):
            if {"x1","y1","x2","y2"} <= bbox.keys():
                x1, y1, x2, y2 = map(float, (bbox["x1"], bbox["y1"], bbox["x2"], bbox["y2"]))
            elif {"x","y","w","h"} <= bbox.keys():
                x1, y1 = float(bbox["x"]), float(bbox["y"])
                x2, y2 = x1 + float(bbox["w"]), y1 + float(bbox["h"])
            else:
                return None
        else:
            return None
        def to_px(v, M):
            return int(round(v * M)) if v <= 1.5 else int(round(v))
        x1, y1, x2, y2 = to_px(x1, W), to_px(y1, H), to_px(x2, W), to_px(y2, H)
        if x2 < x1:
            x1, x2 = x2, x1
        if y2 < y1:
            y1, y2 = y2, y1
        x1 = max(0, min(W-1, x1))
        x2 = max(0, min(W-1, x2))
        y1 = max(0, min(H-1, y1))
        y2 = max(0, min(H-1, y2))
        if (x2-x1) < 4 or (y2-y1) < 4:
            return None
        return (x1, y1, x2, y2)

    def _downscale_image(self, img: Image.Image, max_side=1024, quality=82) -> Image.Image:
        if img.mode != "RGB":
            img = img.convert("RGB")
        w, h = img.size
        s = max(w, h)
        if s > max_side:
            scale = max_side / float(s)
            img = img.resize((int(w*scale), int(h*scale)), Image.LANCZOS)
        # (Optional) strip metadata by re-encoding
        bio = io.BytesIO()
        img.save(bio, format="JPEG", quality=quality, optimize=True)
        bio.seek(0)
        return Image.open(bio)

    # ---------------------- poster localization -------------------------------
    async def _find_poster(
        self,
        image: Image.Image,
        planogram: PlanogramDescription,
        debug_path: Optional[str] = None
    ) -> tuple[Detections, Detections, Detections, Detections]:
        """
        Ask the vision model to find the main promotional graphic for the given brand/tags.
        Returns (x1,y1,x2,y2) in absolute pixels, and the parsed JSON for logging.
        """
        w, _ = image.size
        brand = (getattr(planogram, "brand", "") or "").strip()
        tags = [t.strip() for t in getattr(planogram, "tags", []) or []]
        endcap = getattr(planogram, "advertisement_endcap", None)
        if endcap and getattr(endcap, "text_requirements", None):
            for tr in endcap.text_requirements:
                if getattr(tr, "required_text", None):
                    tags.append(tr.required_text)
        tag_hint = ", ".join(sorted(set(f"'{t}'" for t in tags if t)))

        # downscale for LLM
        image_small = self._downscale_image(image, max_side=1024, quality=78)
        prompt = f"""
Analyze the image to identify the entire retail endcap display and its key components.

Your response must be a single JSON object with a 'detections' list. Each detection must have a 'label', 'confidence', a 'content' with any detected text, and a 'bbox' with normalized coordinates (x1, y1, x2, y2).

Useful phrases to look for inside the lightbox: {tag_hint}

Return exactly FIVE detections with the following strict criteria:

1. **'brand_logo'**: A bounding box for the '{brand}' brand logo at the top of the sign.

2. **'poster_text'**: A bounding box for the main marketing text on the sign, must include phrases like {tag_hint}.

3. **'promotional_graphic'**: A bounding box for the main promotional graphic on the sign, which may include images of products, people (e.g. A man pointing up), or other marketing visuals. The box should tightly enclose the graphic area without cutting off any important elements. For this detection, 'content' should be null.

4. **'poster_panel'**: A bounding box that **tightly encloses the entire backlit sign, The box must **tightly enclose the sign's outer silver/gray frame on all four sides.** For this detection, 'content' should be null.

5. **'endcap'**: A bounding box for the entire retail endcap display structure. It must start at the top of the sign and extend down to the **base of the lowest shelf**, including price tags and products boxes. The box must be wide enough to **include all products and product boxes on all shelves without cropping.** For this detection, 'content' should be null.

"""
        max_attempts = 2  # Initial attempt + 1 retry
        retry_delay_seconds = 10
        msg = None
        for attempt in range(max_attempts):
            try:
                async with self.google as client:
                    msg = await client.ask_to_image(
                        image=image_small,
                        prompt=prompt,
                        model="gemini-2.5-flash",
                        no_memory=True,
                        structured_output=Detections,
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
        data = msg.structured_output or msg.output or {}
        dets = data.detections or []
        if not dets:
            return None, data
        # print('detections > ', dets)
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
        promo_graphic_det = next((d for d in dets if d.label == "promotional_graphic"), None)

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
        advertisement_config = getattr(planogram, "advertisement", {})
        # Default values if not in planogram, normalized to image (not ROI)
        config_width_percent = advertisement_config.get('width_percent', 0.45)
        config_height_percent = advertisement_config.get('height_percent', 0.33)
        config_top_margin_percent = advertisement_config.get('top_margin_percent', 0.02)
        # E.g., 5% of panel width
        side_margin_percent = advertisement_config.get('side_margin_percent', 0.05)

        # --- Refined Panel Padding ---
        # Apply padding to the panel_det itself to ensure it captures the full visual area
        panel_det.bbox.x1 = max(0.0, panel_det.bbox.x1 - side_margin_percent)
        panel_det.bbox.x2 = min(1.0, panel_det.bbox.x2 + side_margin_percent)

        if panel_det and text_det:
            print(
                "INFO: Found both panel and text. Applying boundary correction."
            )
            # Get the bottom of the text box
            text_bottom_y2 = text_det.bbox.y2
            # Optional: Add a small amount of padding (e.g., 8% of image height)
            padding = 0.08
            new_panel_y2 = min(text_bottom_y2 + padding, 1.0) # Ensure it doesn't exceed 1.0
            panel_det.bbox.y2 = new_panel_y2

        # --- endcap Detected:
        endcap_det = next((d for d in dets if d.label == "endcap"), None)
        # compares if endcap x2 and x1 are equal to panel x2 and x1
        # panel (yellow)
        px1, py1, px2, py2 = panel_det.bbox.x1, panel_det.bbox.y1, panel_det.bbox.x2, panel_det.bbox.y2
        panel_w = px2 - px1
        panel_h  = py2 - py1

        # panel_height : endcap_height ratio, e.g., 0.33 if panel ~33% of endcap height
        ratio = max(1e-6, float(config_height_percent))
        top_margin = float(config_top_margin_percent)  # e.g., 0.01
        x_tol = 0.003 * panel_w                        # ~0.3% of panel width
        y_tol = 0.005                                  # ~0.5% absolute; tune to taste

        # --- Target Y from panel + config ---
        target_y1 = max(0.0, py1 - top_margin)
        target_y2 = min(0.98, target_y1 + panel_h / ratio)    # cap a little above floor

        # If no endcap or Y is off-target, override Y with target values
        if (endcap_det is None or
            abs(endcap_det.bbox.y1 - target_y1) > y_tol or
            abs(endcap_det.bbox.y2 - target_y2) > y_tol):
            ex1, ex2 = (px1, px2) if endcap_det is None else (endcap_det.bbox.x1, endcap_det.bbox.x2)
            ey1, ey2 = target_y1, target_y2
        else:
            ex1, ex2 = endcap_det.bbox.x1, endcap_det.bbox.x2
            ey1, ey2 = endcap_det.bbox.y1, endcap_det.bbox.y2

        # --- X correction: expand only when inside the panel band ---
        if ex1 > px1 + x_tol:
            ex1 = px1 - self.left_margin_ratio  * panel_w
        if ex2 < px2 - x_tol:
            ex2 = px2 + self.right_margin_ratio * panel_w

        # Clamp & monotonic
        ex1 = max(0.0, ex1)
        ex2 = min(1.0, ex2)
        if ex2 <= ex1:
            ex2 = ex1 + 1e-6

        endcap_det.bbox.x1, endcap_det.bbox.x2 = ex1, ex2
        endcap_det.bbox.y1, endcap_det.bbox.y2 = ey1, ey2

        if debug_path:
            panel_px = panel_det.bbox.get_coordinates()
            self._save_poster_debug(image, panel_px, dets, debug_path)

        return endcap_det, panel_det, brand_det, text_det

    def _save_poster_debug(
        self,
        pil_image: Image.Image,
        poster_bounds: Tuple[int, int, int, int],
        detections: List[dict],
        save_path: str
    ) -> None:
        """Save debug image showing poster detection results"""
        try:
            debug_img = pil_image.copy()
            draw = ImageDraw.Draw(debug_img)
            # draw the detections:
            for det in detections:
                label = det.label
                conf = float(det.confidence or 0.0)
                bbox = det.bbox
                x1 = int(bbox.x1 * debug_img.width)
                y1 = int(bbox.y1 * debug_img.height)
                x2 = int(bbox.x2 * debug_img.width)
                y2 = int(bbox.y2 * debug_img.height)
                x1, y1, x2, y2 = _clamp(debug_img.width, debug_img.height, x1, y1, x2, y2)

                color = (255, 165, 0) if label == "poster_panel" else (0, 255, 255)
                draw.rectangle(
                    [(x1, y1), (x2, y2)],
                    outline=color,
                    width=3
                )
                draw.text(
                    (x1, y1 - 20),
                    f"{label} {conf:.2f}",
                    fill=color
                )

            # Draw final poster bounds in bright green
            x1, y1, x2, y2 = poster_bounds
            draw.rectangle(
                [(x1, y1), (x2, y2)],
                outline=(0, 255, 0),
                width=4
            )
            draw.text(
                (x1, y1 - 45),
                f"POSTER: {x2-x1}x{y2-y1}",
                fill=(0, 255, 0)
            )

            # Save debug image
            Path(save_path).parent.mkdir(parents=True, exist_ok=True)
            debug_img.save(save_path, quality=95)
            self.logger.debug(f"Saved poster debug image to {save_path}")

        except Exception as e:
            self.logger.error(f"Failed to save debug image: {e}")

    # --------------------------- shelves -------------------------------------
    def _find_shelves(
            self,
            roi_box: tuple[int, int, int, int],
            ad_box: tuple[int, int, int, int],
            h: int, w: int,
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
        Gentle, adaptive preprocessing that only enhances when needed.
        Preserves well-contrasted images and applies minimal enhancement.
        """
        try:
            # Convert BGR to RGB if needed
            if len(roi.shape) == 3 and roi.shape[2] == 3:
                rgb_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2RGB)
            else:
                rgb_roi = roi.copy()

            # Analyze image quality to determine if preprocessing is needed
            gray = cv2.cvtColor(rgb_roi, cv2.COLOR_RGB2GRAY)

            # Calculate contrast metrics
            contrast = gray.std()  # Standard deviation as contrast measure
            mean_brightness = gray.mean()

            # Calculate edge density (measure of detail/sharpness)
            edges = cv2.Canny(gray, 50, 150)
            edge_density = np.sum(edges > 0) / edges.size

            # Determine if image needs enhancement
            needs_contrast_boost = contrast < 45  # Low contrast threshold
            needs_brightness_adjustment = mean_brightness < 80 or mean_brightness > 180
            needs_edge_enhancement = edge_density < 0.02  # Very few edges detected

            # If image quality is already good, apply minimal or no processing
            if not (needs_contrast_boost or needs_brightness_adjustment or needs_edge_enhancement):
                # Image is already well-contrasted, return with minimal enhancement
                result = rgb_roi.copy().astype(np.float32)

                # Very subtle sharpening only
                kernel = np.array([[-0.1, -0.1, -0.1],
                                [-0.1,  1.8, -0.1],
                                [-0.1, -0.1, -0.1]])
                for i in range(3):
                    result[:,:,i] = cv2.filter2D(result[:,:,i], -1, kernel)

                result = np.clip(result, 0, 255).astype(np.uint8)

                # Convert back to BGR if needed
                if len(roi.shape) == 3 and roi.shape[2] == 3:
                    result = cv2.cvtColor(result, cv2.COLOR_RGB2BGR)

                return result

            # Apply gentle enhancement for images that need it
            result = rgb_roi.copy()

            # Gentle contrast enhancement only if needed
            if needs_contrast_boost:
                lab = cv2.cvtColor(result, cv2.COLOR_RGB2LAB)

                # Very mild CLAHE
                clahe = cv2.createCLAHE(clipLimit=1.5, tileGridSize=(12,12))
                lab[:,:,0] = clahe.apply(lab[:,:,0])

                result = cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)

            # Gentle brightness adjustment only if needed
            if needs_brightness_adjustment:
                if mean_brightness < 80:
                    # Slightly brighten dark images
                    result = cv2.convertScaleAbs(result, alpha=1.0, beta=15)
                elif mean_brightness > 180:
                    # Slightly darken bright images
                    result = cv2.convertScaleAbs(result, alpha=0.95, beta=-10)

            # Very subtle edge enhancement only if edges are weak
            if needs_edge_enhancement:
                gray_enhanced = cv2.cvtColor(result, cv2.COLOR_RGB2GRAY)
                edges_weak = cv2.Canny(gray_enhanced, 30, 100)

                # Create very mild edge mask
                kernel_small = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 1))
                edges_weak = cv2.dilate(edges_weak, kernel_small, iterations=1)

                edge_mask = edges_weak > 0
                result_float = result.astype(np.float32)

                # Very gentle edge enhancement
                for i in range(3):
                    channel = result_float[:,:,i]
                    channel[edge_mask] = np.clip(channel[edge_mask] * 1.1, 0, 255)
                    result_float[:,:,i] = channel

                result = result_float.astype(np.uint8)

            # Convert back to BGR if needed
            if len(roi.shape) == 3 and roi.shape[2] == 3:
                result = cv2.cvtColor(result, cv2.COLOR_RGB2BGR)

            return result

        except Exception as e:
            self.logger.warning(f"ROI preprocessing failed: {e}")
            return roi

    def _preprocess_roi_for_detection_minimal(self, roi: np.ndarray) -> np.ndarray:
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
        enhanced_roi = self._preprocess_roi_for_detection_minimal(roi)

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
                                ocr_text = clean_ocr_text(ocr_text)
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
                    print('PROPOSAL > ', proposal)
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
            "tv": ["promotional_graphic"],
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
        reference_images: Dict[str, Path] = None,
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
            llm=self.llm,
            device="cuda" if torch.cuda.is_available() else "cpu",
            reference_images=list(reference_images.values())
        )
        self.logger.debug(
            f"Initialized RetailDetector with {detection_model}"
        )
        self.reference_images = reference_images or {}
        self.confidence_threshold = confidence_threshold

    async def detect_objects_and_shelves(
        self,
        image,
        planogram_description: Optional[PlanogramDescription] = None
    ):
        self.logger.debug("Step 1: Detecting generic shapes and boundaries...")

        pil_image = Image.open(image) if isinstance(image, (str, Path)) else image

        det_out = await self.shape_detector.detect(
            image=pil_image,
            planogram=planogram_description,
            debug_raw="/tmp/data/yolo_raw_debug.png",
            debug_phase1="/tmp/data/yolo_phase1_debug.png",
            debug_phases="/tmp/data/yolo_phases_debug.png",
        )

        shelves = det_out["shelves"]          # {'top': DetectionBox(...), 'middle': ...}
        proposals    = det_out["proposals"]        # List[DetectionBox]

        # print("PROPOSALS:", proposals)
        # print("SHELVES:", shelves)

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
        effective_dets = [d for d in detections if d.class_name not in {"slot", "shelf_region", "price_tag", "fact_tag"}]
        self._debug_dump_crops(pil_image, effective_dets, tag="effective")
        self._debug_dump_crops(pil_image, detections, tag="raw")

        annotated_image = self._create_annotated_image(pil_image, effective_dets)
        # annotated_image = self._create_annotated_image(image, detections)

        async with self.llm as client:
            try:
                if self.llm_provider == "google":
                    extra_refs = {
                        "annotated_image": annotated_image,
                        **reference_images
                    }
                    identified_products = await client.image_identification(
                        prompt=self._build_gemini_identification_prompt(effective_dets, shelf_regions),
                        image=image,
                        detections=effective_dets,
                        shelf_regions=shelf_regions,
                        reference_images=extra_refs,
                        temperature=0.0
                    )
                elif self.llm_provider == "openai":
                    # Build identification prompt (without structured output request)
                    prompt = self._build_identification_prompt(effective_dets, shelf_regions)
                    extra_refs = [annotated_image] + (list(reference_images.values()) or [])
                    identified_products = await client.image_identification(
                        image=image,
                        prompt=prompt,
                        detections=effective_dets,
                        shelf_regions=shelf_regions,
                        reference_images=extra_refs,
                        temperature=0.0,
                        ocr_hints=True
                    )
                else:
                    # Fallback to your existing logic for other clients like OpenAI
                    self.logger.warning("Using legacy identification logic.")
                    return [] # Placeholder for your other client logic
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
        shelf_regions: List[ShelfRegion]
    ) -> str:
        """Builds a more detailed prompt to help Gemini differentiate similar products."""

        # --- Part 1: Describe Existing Detections ---
        detection_lines = ["\nDETECTED OBJECTS (with pre-assigned IDs):"]
        if detections:
            for i, detection in enumerate(detections, 1):
                detection_lines.append(
                    f"ID {i}: Initial class '{detection.class_name}' at bbox ({detection.x1},{detection.y1},{detection.x2},{detection.y2})"
                )
        else:
            detection_lines.append("None")

        # --- Part 2: Define the Ground-Truth Shelf Layout ---
        shelf_definitions = ["\n**VALID SHELF NAMES & LOCATIONS (Ground Truth):**"]
        valid_shelf_names = []
        for shelf in shelf_regions:
            # Only include the main shelves in the list of options for the LLM
            if shelf.level in ['header', 'middle', 'bottom']:
                valid_shelf_names.append(f"'{shelf.level}'")
                shelf_definitions.append(f"- Shelf '{shelf.level}': Covers the vertical pixel range from y={shelf.bbox.y1} to y={shelf.bbox.y2}.")

        shelf_definitions.append(f"\n**RULE:** For the `shelf_location` field, you MUST use one of these exact names: {', '.join(valid_shelf_names)}.")


        # --- NEW: Enhanced Instructions ---
        prompt = f"""
You are an expert at identifying retail products in planogram displays.
I have provided an image of a retail endcap, labeled reference images, and a list of {len(detections)} pre-detected objects.

{''.join(detection_lines)}
{''.join(shelf_definitions)}

**YOUR TWO-PART TASK:**

1.  **IDENTIFY PRE-DETECTED OBJECTS:** For each object with an ID, identify it using the rules and visual guide below.
2.  **FIND MISSED OBJECTS:** Carefully find any other prominent products (especially printers or large boxes) that DO NOT have an ID. For these new items, set `detection_id` to `null` and provide an approximate `detection_box` array `[x1, y1, x2, y2]`.

---
**!! IMPORTANT VISUAL GUIDE FOR PRINTERS !!**
REFERENCE IMAGES show Epson printer models - compare visual design, control panels, ink systems.

The printer models are visually similar. You MUST use the control panel to tell them apart.
* **ET-2980:** Has a **simple control panel** with a small screen and arrow buttons. **NO number pad.**
* **ET-3950:** Has a **larger control panel with a physical number pad (0-9)** to the right of the screen.
* **ET-4950:** Has a **large color touchscreen** and very few physical buttons.

**Use these specific features to make your final decision on the printer model.**
---

**IDENTIFICATION RULES:**
1.  **PRINTERS (Devices):** White/gray devices. Use the visual guide above to determine the correct `product_model` ('ET-2980', 'ET-3950', or 'ET-4950').
2.  **BOXES (Packaging):** Blue packaging. `product_type` is 'product_box'. `product_model` is 'ET-XXXX box'.
3.  **PROMOTIONAL GRAPHICS:** Large signs/posters. `product_type` is 'promotional_graphic'.

**JSON OUTPUT FORMAT:**
Respond with a single JSON object. For each product you identify (both pre-detected and newly found), provide an entry in the 'detections' list with all the required fields.

For each detection (ID 1-{len(detections)}), provide:
- detection_id: The exact ID number from the red bounding box (1-{len(detections)}), or null if newly found.
- product_type: printer, product_box, fact_tag, promotional_graphic, or ink_bottle
- product_model: Follow naming rules above based on product_type
- confidence: Your confidence (0.0-1.0)
- visual_features: List of visual features
- reference_match: Which reference image matches (or "none")
- shelf_location: header, top, middle, or bottom
- position_on_shelf: left, center, or right
- Remove any duplicates - only one entry per detection_id

**!! FINAL CHECK !!**
Before responding, ensure **every single object** in the 'detections' list includes all required fields, especially `confidence`, `shelf_location`, and `position_on_shelf`. Do not omit any fields.

Analyze all provided images and return the complete JSON response.
    """
        return prompt

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

    # STEP 3: Planogram Compliance Check
    # def check_planogram_compliance(
    #     self,
    #     identified_products: List[IdentifiedProduct],
    #     planogram_description: PlanogramDescription,
    # ) -> List[ComplianceResult]:
    #     """Check compliance of identified products against the planogram

    #     Args:
    #         identified_products (List[IdentifiedProduct]): The products identified in the image
    #         planogram_description (PlanogramDescription): The expected planogram layout

    #     Returns:
    #         List[ComplianceResult]: The compliance results for each shelf
    #     """
    #     results: List[ComplianceResult] = []

    #     # Group found products by shelf level
    #     by_shelf = defaultdict(list)
    #     for p in identified_products:
    #         by_shelf[p.shelf_location].append(p)

    #     # Iterate through expected shelves
    #     for shelf_cfg in planogram_description.shelves:
    #         shelf_level = shelf_cfg.level

    #         # Build expected product list (excluding tags)
    #         expected = []
    #         for sp in shelf_cfg.products:
    #             if sp.product_type in ("fact_tag", "price_tag", "slot"):
    #                 continue
    #             nm = self._normalize_product_name((sp.name or sp.product_type) or "unknown")
    #             expected.append(nm)

    #         # Gather found products on this shelf
    #         found, promos = [], []
    #         for p in by_shelf.get(shelf_level, []):
    #             if p.product_type in ("fact_tag", "price_tag", "slot"):
    #                 continue
    #             nm = self._normalize_product_name(p.product_model or p.product_type)
    #             found.append(nm)
    #             if p.product_type == "promotional_graphic":
    #                 promos.append(p)

    #         # Calculate basic product compliance
    #         missing = [e for e in expected if e not in found]
    #         unexpected = [] if shelf_cfg.allow_extra_products else [f for f in found if f not in expected]
    #         basic_score = (sum(1 for e in expected if e in found) / (len(expected) or 1))

    #         # FIX 3: Enhanced text compliance handling
    #         text_results, text_score, overall_text_ok = [], 1.0, True

    #         # Check for advertisement endcap on this shelf
    #         endcap = planogram_description.advertisement_endcap
    #         if endcap and endcap.enabled and endcap.position == shelf_level:
    #             if endcap.text_requirements:
    #                 # Combine visual features from all promotional items
    #                 all_features = []
    #                 ocr_blocks = []
    #                 for promo in promos:
    #                     if getattr(promo, "visual_features", None):
    #                         all_features.extend(promo.visual_features)
    #                         for feat in promo.visual_features:
    #                             if isinstance(feat, str) and feat.startswith("ocr:"):
    #                                 ocr_blocks.append(feat[4:].strip())

    #                 if ocr_blocks:
    #                     ocr_norm = self._normalize_ocr_text(" ".join(ocr_blocks))
    #                     if ocr_norm:
    #                         all_features.append(ocr_norm)

    #                 # If no promotional graphics found but text required, create default failure
    #                 if not promos and shelf_level == "header":
    #                     self.logger.warning(
    #                         f"No promotional graphics found on {shelf_level} shelf but text requirements exist"
    #                     )
    #                     overall_text_ok = False
    #                     for text_req in endcap.text_requirements:
    #                         text_results.append(TextComplianceResult(
    #                             required_text=text_req.required_text,
    #                             found=False,
    #                             matched_features=[],
    #                             confidence=0.0,
    #                             match_type=text_req.match_type
    #                         ))
    #                 else:
    #                     # Check text requirements against found features
    #                     for text_req in endcap.text_requirements:
    #                         result = TextMatcher.check_text_match(
    #                             required_text=text_req.required_text,
    #                             visual_features=all_features,
    #                             match_type=text_req.match_type,
    #                             case_sensitive=text_req.case_sensitive,
    #                             confidence_threshold=text_req.confidence_threshold
    #                         )
    #                         text_results.append(result)

    #                         if not result.found and text_req.mandatory:
    #                             overall_text_ok = False

    #                 # Calculate text compliance score
    #                 if text_results:
    #                     text_score = sum(r.confidence for r in text_results if r.found) / len(text_results)

    #         # For non-header shelves without text requirements, don't penalize
    #         elif shelf_level != "header":
    #             overall_text_ok = True  # Don't require text compliance on product shelves
    #             text_score = 1.0

    #         # Determine compliance threshold
    #         threshold = getattr(
    #             shelf_cfg,
    #             "compliance_threshold",
    #             planogram_description.global_compliance_threshold or 0.8
    #         )

    #         # FIX 4: Better status determination logic
    #         # Allow minor unexpected (ink bottles, price tags)
    #         major_unexpected = [
    #             p for p in unexpected if not any(
    #                 word in p.lower() for word in ["ink bottle", "price tag", "502"]
    #             )
    #         ]
    #         # For product shelves (non-header), focus on product compliance
    #         if shelf_level != "header":
    #             if basic_score >= threshold and not major_unexpected:
    #                 status = ComplianceStatus.COMPLIANT
    #             elif basic_score == 0.0:
    #                 status = ComplianceStatus.MISSING
    #             else:
    #                 status = ComplianceStatus.NON_COMPLIANT
    #         else:
    #             overall_text_ok = bool(overall_text_ok)
    #             # For header shelf, require both product and text compliance
    #             if basic_score >= threshold and not major_unexpected and overall_text_ok:
    #                 status = ComplianceStatus.COMPLIANT
    #             elif basic_score == 0.0:
    #                 status = ComplianceStatus.MISSING
    #             elif not overall_text_ok:
    #                 status = ComplianceStatus.NON_COMPLIANT
    #             else:
    #                 status = ComplianceStatus.NON_COMPLIANT

    #         # Calculate combined score with appropriate weighting
    #         if shelf_level == "header":
    #             # Header: Balance product and text compliance
    #             endcap = planogram_description.advertisement_endcap
    #             weights = {
    #                 "product_compliance": endcap.product_weight,
    #                 "text_compliance": endcap.text_weight
    #             }
    #         else:
    #             # Product shelves: Emphasize product compliance
    #             weights = {"product_compliance": 0.9, "text_compliance": 0.1}

    #         combined_score = (basic_score * weights["product_compliance"] +
    #                         text_score * weights["text_compliance"])

    #         results.append(
    #             ComplianceResult(
    #                 shelf_level=shelf_level,
    #                 expected_products=expected,
    #                 found_products=found,
    #                 missing_products=missing,
    #                 unexpected_products=unexpected,
    #                 compliance_status=status,
    #                 compliance_score=combined_score,
    #                 text_compliance_results=text_results,
    #                 text_compliance_score=text_score,
    #                 overall_text_compliant=overall_text_ok
    #             )
    #         )

    #     return results

    def check_planogram_compliance(
        self,
        identified_products: List[IdentifiedProduct],
        planogram_description: PlanogramDescription,
    ) -> List[ComplianceResult]:
        """Check compliance of identified products against the planogram."""
        results: List[ComplianceResult] = []

        by_shelf = defaultdict(list)
        for p in identified_products:
            by_shelf[p.shelf_location].append(p)

        for shelf_cfg in planogram_description.shelves:
            shelf_level = shelf_cfg.level
            products_on_shelf = by_shelf.get(shelf_level, [])

            expected = []
            for sp in shelf_cfg.products:
                if sp.product_type in ("fact_tag", "price_tag", "slot"):
                    continue
                nm = self._normalize_product_name((sp.name or sp.product_type) or "unknown")
                expected.append(nm)

            found, promos = [], []
            for p in products_on_shelf:
                if p.product_type in ("fact_tag", "price_tag", "slot", "brand_logo"): # Exclude brand_logo from product counts
                    continue
                nm = self._normalize_product_name(p.product_model or p.product_type)
                found.append(nm)
                if p.product_type == "promotional_graphic":
                    promos.append(p)

            missing = [e for e in expected if e not in found]
            unexpected = [] if shelf_cfg.allow_extra_products else [f for f in found if f not in expected]
            basic_score = (sum(1 for e in expected if e in found) / (len(expected) or 1))

            text_results, text_score, overall_text_ok = [], 1.0, True

            # NEW: Initialize variables for brand compliance
            brand_compliance_result: Optional[BrandComplianceResult] = None
            brand_score = 0.0
            brand_check_ok = True # Assume OK unless mandatory check fails

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

                # NEW: Implement the brand logo check for the header shelf
                brand_reqs = planogram_description.brand or None
                if brand_reqs:
                    expected_brand = planogram_description.brand
                    # Find the detected brand_logo object on this shelf
                    brand_logo_product = next(
                        (p for p in products_on_shelf if p.product_type == 'brand_logo'), None
                    )

                    found_brand = None
                    is_match = False
                    logo_confidence = 0.0

                    if brand_logo_product and brand_logo_product.brand:
                        found_brand = brand_logo_product.brand
                        logo_confidence = brand_logo_product.confidence
                        # Case-insensitive comparison for robustness
                        if expected_brand.lower() in found_brand.lower():
                            is_match = True
                            brand_score = 1.0

                    brand_compliance_result = BrandComplianceResult(
                        expected_brand=expected_brand,
                        found_brand=found_brand,
                        found=is_match,
                        confidence=logo_confidence
                    )

                    # Apply the mandatory rule
                    brand_check_ok = is_match

            elif shelf_level != "header":
                overall_text_ok = True
                text_score = 1.0

            threshold = getattr(
                shelf_cfg, "compliance_threshold", planogram_description.global_compliance_threshold or 0.8
            )

            major_unexpected = [p for p in unexpected if "ink bottle" not in p.lower() and "price tag" not in p.lower()]

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

            # MODIFIED: Combined score calculation with brand weight
            if shelf_level == "header" and endcap:
                weights = {
                    "product": endcap.product_weight,
                    "text": endcap.text_weight,
                    "brand": getattr(endcap, "brand_weight", 0.0) # Use 0 if not defined
                }
                combined_score = (
                    (basic_score * weights["product"]) +
                    (text_score * weights["text"]) +
                    (brand_score * weights["brand"])
                )
            else:
                weights = {"product_compliance": 0.9, "text_compliance": 0.1}
                combined_score = (basic_score * weights["product_compliance"] + text_score * weights["text_compliance"])

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
        shelf_regions, detections = await self.detect_objects_and_shelves(
            image, planogram_description
        )

        self.logger.debug(
            f"Found {len(detections)} objects in {len(shelf_regions)} shelf regions"
        )

        self.logger.notice("Step 2: Identifying objects with LLM...")
        identified_products = await self.identify_objects_with_references(
            image, detections, shelf_regions, self.reference_images
        )

        self.logger.debug(
            f"Identified Products: {identified_products}"
        )

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
