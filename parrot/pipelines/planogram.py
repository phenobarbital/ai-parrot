"""
3-Step Planogram Compliance Pipeline
Step 1: Object Detection (YOLO/ResNet)
Step 2: LLM Object Identification with Reference Images
Step 3: Planogram Comparison and Compliance Verification
"""
from typing import List, Dict, Any, Optional, Union, Tuple
import re
import traceback
from pathlib import Path
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageFilter
import numpy as np
from pydantic import BaseModel, Field
import cv2
import torch
from .abstract import AbstractPipeline
from ..models.detections import (
    DetectionBox,
    ShelfRegion,
    IdentifiedProduct,
    PlanogramDescription
)
from ..models.compliance import ComplianceResult, ComplianceStatus


"""
Generic shape and boundary detection without product classification
YOLO detects shapes/boxes, LLM identifies what they are
"""
from typing import List, Dict, Any, Optional, Union, Tuple
from pathlib import Path
from PIL import Image
import numpy as np
import cv2
from parrot.models.detections import DetectionBox, ShelfRegion


class IdentificationResponse(BaseModel):
    """Response model for product identification"""
    identified_products: List[IdentifiedProduct] = Field(
        alias="detections",
        description="List of identified products from the image"
    )

class ImprovedRetailDetector:
    """
    Enhanced detector with image preprocessing and retail-specific focus
    """

    def __init__(self, detection_model_name: str = "yolov8n"):
        self.detection_model_name = detection_model_name
        self.detection_model = None
        self._load_detection_model()

    def _load_detection_model(self):
        """Load YOLO model"""
        try:
            from ultralytics import YOLO
            self.detection_model = YOLO(self.detection_model_name)
            print(f"Loaded {self.detection_model_name} for enhanced detection")
        except ImportError:
            print("ultralytics not installed")
            self.detection_model = None
        except Exception as e:
            print(f"Failed to load YOLO model: {e}")
            self.detection_model = None

    def preprocess_image_for_detection(
        self, image: Union[str, Path, Image.Image]
    ) -> Tuple[Image.Image, np.ndarray]:
        """
        Enhance image for better object detection
        """

        if isinstance(image, (str, Path)):
            pil_image = Image.open(image)
        else:
            pil_image = image

        # Convert to RGB if needed
        if pil_image.mode != 'RGB':
            pil_image = pil_image.convert('RGB')

        print("Applying image enhancements for better detection...")

        # 1. Increase contrast to make objects stand out
        enhancer = ImageEnhance.Contrast(pil_image)
        enhanced = enhancer.enhance(1.4)  # 40% more contrast

        # 2. Increase brightness to handle dim lighting
        enhancer = ImageEnhance.Brightness(enhanced)
        enhanced = enhancer.enhance(1.2)  # 20% brighter

        # 3. Increase sharpness to make edges clearer
        enhancer = ImageEnhance.Sharpness(enhanced)
        enhanced = enhancer.enhance(1.5)  # 50% sharper

        # 4. Apply slight color saturation to distinguish products
        enhancer = ImageEnhance.Color(enhanced)
        enhanced = enhancer.enhance(1.1)  # 10% more saturated

        # 5. Apply edge enhancement filter
        enhanced = enhanced.filter(ImageFilter.EDGE_ENHANCE)

        # Convert to numpy for YOLO
        img_array = np.array(enhanced)

        return enhanced, img_array

    def detect_retail_products(
        self,
        image: Union[str, Path, Image.Image],
        confidence_threshold: float = 0.5
    ) -> List[DetectionBox]:
        """
        Enhanced retail product detection with preprocessing
        """

        # Preprocess image
        enhanced_pil, img_array = self.preprocess_image_for_detection(image)

        all_detections: List[DetectionBox] = []

        # 1) main YOLO proposals (big stuff)
        yolo_detections = self._enhanced_yolo_detection(img_array, confidence_threshold)
        all_detections.extend(yolo_detections)

        # 2) retail regions (rule-based anchors)
        retail_detections = self._detect_retail_regions(img_array, confidence_threshold)
        all_detections.extend(retail_detections)

        # 3) large rectangular products (contour pass)
        product_detections = self._detect_large_products(img_array, confidence_threshold)
        all_detections.extend(product_detections)

        # 4) SECOND YOLO PASS: small price/fact tags
        small_tags = self._yolo_small_tag_detection(img_array)
        all_detections.extend(small_tags)

        # 5) merge (keep your current strategy) THEN shrink to reduce overlap
        final_detections = self._intelligent_merge(all_detections, confidence_threshold)
        final_detections = self._shrink_detections(final_detections)

        print(f"Enhanced detection found {len(final_detections)} retail products")
        for i, det in enumerate(final_detections):
            print(f"  {i+1}: {det.class_name} at ({det.x1},{det.y1},{det.x2},{det.y2}) conf={det.confidence:.2f}")

        return final_detections

    def _enhanced_yolo_detection(self, img_array: np.ndarray, confidence_threshold: float) -> List[DetectionBox]:
        """Enhanced YOLO detection focused on larger objects"""
        detections = []

        if self.detection_model is None:
            return detections

        try:
            # Run YOLO with adjusted parameters
            results = self.detection_model(
                img_array,
                conf=0.05,  # Very low confidence to catch everything
                iou=0.3,    # Lower IoU for better separation
                imgsz=640   # Standard size
            )

            if hasattr(results[0], 'boxes') and results[0].boxes is not None:
                boxes = results[0].boxes.xyxy.cpu().numpy()
                confidences = results[0].boxes.conf.cpu().numpy()

                height, width = img_array.shape[:2]
                min_area = width * height * 0.005  # Minimum 0.5% of image area

                for i in range(len(boxes)):
                    x1, y1, x2, y2 = boxes[i]
                    conf = float(confidences[i])
                    area = (x2-x1) * (y2-y1)

                    # Focus on larger objects (likely products, not small tags)
                    if area >= min_area:
                        # Classify based on size and position
                        product_class = self._classify_retail_object(x1, y1, x2, y2, area, img_array.shape)

                        detection = DetectionBox(
                            x1=int(x1), y1=int(y1), x2=int(x2), y2=int(y2),
                            confidence=conf,
                            class_id=self._get_retail_class_id(product_class),
                            class_name=product_class,
                            area=int(area)
                        )
                        detections.append(detection)

            print(f"Enhanced YOLO found {len(detections)} significant objects")

        except Exception as e:
            print(f"Enhanced YOLO detection failed: {e}")

        return detections

    def _detect_retail_regions(self, img_array: np.ndarray, confidence_threshold: float) -> List[DetectionBox]:
        """Detect specific retail product regions"""
        height, width = img_array.shape[:2]
        detections = []

        # Define expected product regions based on typical endcap layout
        product_regions = [
            # Top shelf - 3 printer positions
            {"x1": 0.05, "y1": 0.25, "x2": 0.35, "y2": 0.6, "type": "printer", "priority": "high"},
            {"x1": 0.35, "y1": 0.25, "x2": 0.65, "y2": 0.6, "type": "printer", "priority": "high"},
            {"x1": 0.65, "y1": 0.25, "x2": 0.95, "y2": 0.6, "type": "printer", "priority": "high"},

            # Bottom shelf - 3 box positions
            {"x1": 0.05, "y1": 0.65, "x2": 0.35, "y2": 0.95, "type": "product_box", "priority": "high"},
            {"x1": 0.35, "y1": 0.65, "x2": 0.65, "y2": 0.95, "type": "product_box", "priority": "high"},
            {"x1": 0.65, "y1": 0.65, "x2": 0.95, "y2": 0.95, "type": "product_box", "priority": "high"},

            # Header region
            {"x1": 0.1, "y1": 0.02, "x2": 0.9, "y2": 0.2, "type": "promotional_graphic", "priority": "medium"},
        ]

        for region in product_regions:
            x1 = int(width * region["x1"])
            y1 = int(height * region["y1"])
            x2 = int(width * region["x2"])
            y2 = int(height * region["y2"])

            # Extract region and analyze content
            if y2 > y1 and x2 > x1:
                region_img = img_array[y1:y2, x1:x2]

                # Check for significant content using multiple methods
                has_content = self._analyze_region_content(region_img)

                if has_content:
                    # Adjust confidence based on priority and content quality
                    base_confidence = 0.8 if region["priority"] == "high" else 0.6
                    confidence = base_confidence * has_content

                    if confidence >= confidence_threshold:
                        detection = DetectionBox(
                            x1=x1, y1=y1, x2=x2, y2=y2,
                            confidence=confidence,
                            class_id=self._get_retail_class_id(region["type"]),
                            class_name=region["type"],
                            area=(x2-x1) * (y2-y1)
                        )
                        detections.append(detection)

        print(f"Retail region detection found {len(detections)} expected product areas")
        return detections

    def _detect_large_products(self, img_array: np.ndarray, confidence_threshold: float) -> List[DetectionBox]:
        """Detect large rectangular objects that could be printers or boxes"""
        detections = []

        try:
            # Convert to grayscale for contour detection
            gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)

            # Apply Gaussian blur to reduce noise
            blurred = cv2.GaussianBlur(gray, (5, 5), 0)

            # Apply threshold to get binary image
            _, thresh = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

            # Find contours
            contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            height, width = img_array.shape[:2]
            min_area = width * height * 0.01  # Minimum 1% of image
            max_area = width * height * 0.3   # Maximum 30% of image

            for contour in contours:
                # Get bounding rectangle
                x, y, w, h = cv2.boundingRect(contour)
                area = w * h

                # Filter by size and aspect ratio
                aspect_ratio = w / h if h > 0 else 0

                if (min_area <= area <= max_area and
                    0.3 <= aspect_ratio <= 3.0 and  # Reasonable aspect ratios
                    w > 80 and h > 60):  # Minimum dimensions

                    # Calculate confidence based on shape quality
                    contour_area = cv2.contourArea(contour)
                    rect_area = w * h
                    shape_quality = contour_area / rect_area if rect_area > 0 else 0

                    confidence = min(0.7, shape_quality)

                    if confidence >= confidence_threshold:
                        # Classify based on position and size
                        product_type = self._classify_by_position_and_size(
                            x, y, x+w, y+h, area, img_array.shape
                        )

                        detection = DetectionBox(
                            x1=x, y1=y, x2=x+w, y2=y+h,
                            confidence=confidence,
                            class_id=self._get_retail_class_id(product_type),
                            class_name=product_type,
                            area=area
                        )
                        detections.append(detection)

            print(f"Large object detection found {len(detections)} potential products")

        except Exception as e:
            print(f"Large product detection failed: {e}")

        return detections

    def _analyze_region_content(self, region_img: np.ndarray) -> float:
        """Analyze if a region contains significant content (0.0 to 1.0)"""
        if region_img.size == 0:
            return 0.0

        # Convert to grayscale
        gray = np.mean(region_img, axis=2) if len(region_img.shape) == 3 else region_img

        # Calculate variance (higher variance = more content)
        variance = np.var(gray)
        variance_score = min(1.0, variance / 2000)

        # Calculate edge density
        try:
            edges = cv2.Canny(gray.astype(np.uint8), 50, 150)
            edge_density = np.sum(edges > 0) / edges.size
            edge_score = min(1.0, edge_density * 10)
        except:
            edge_score = variance_score

        # Calculate color variation
        if len(region_img.shape) == 3:
            color_std = np.std(region_img, axis=(0, 1))
            color_score = min(1.0, np.mean(color_std) / 50)
        else:
            color_score = variance_score

        # Combined score
        content_score = (variance_score * 0.4 + edge_score * 0.4 + color_score * 0.2)
        return content_score

    def _classify_retail_object(
        self, x1: float, y1: float, x2: float, y2: float,
        area: float, img_shape: Tuple[int, int]
    ) -> str:
        """Classify object based on position and size in retail context"""

        height, width = img_shape[:2]
        y_ratio = y1 / height
        relative_area = area / (width * height)
        aspect_ratio = (x2 - x1) / (y2 - y1) if (y2 - y1) > 0 else 1.0

        # Header area (promotional graphics)
        if y_ratio < 0.25:
            return "promotional_graphic"

        # Top shelf area (printers)
        elif 0.25 <= y_ratio < 0.6:
            if relative_area > 0.02:  # Large enough for printer
                return "printer"
            else:
                return "fact_tag"

        # Bottom shelf area (product boxes)
        elif y_ratio >= 0.65:
            if relative_area > 0.015:  # Large enough for box
                return "product_box"
            else:
                return "fact_tag"

        # Middle area
        else:
            if relative_area < 0.005:
                return "fact_tag"
            else:
                return "ink_bottle"

    def _classify_by_position_and_size(
        self, x1: float, y1: float, x2: float, y2: float,
        area: float, img_shape: Tuple[int, int]
    ) -> str:
        """Alternative classification method"""
        height, width = img_shape[:2]
        y_center = (y1 + y2) / 2
        y_ratio = y_center / height

        if y_ratio < 0.3:
            return "promotional_graphic"
        elif y_ratio < 0.6:
            return "printer"
        else:
            return "product_box"

    def _get_retail_class_id(self, class_name: str) -> int:
        """Get class ID for retail products"""
        mapping = {
            "printer": 100,
            "product_box": 101,
            "fact_tag": 102,
            "promotional_graphic": 103,
            "ink_bottle": 104,
            "unknown": 199
        }
        return mapping.get(class_name, 199)

    def _intelligent_merge(self, detections: List[DetectionBox], confidence_threshold: float) -> List[DetectionBox]:
        """Per-class filtering + simple NMS, then shrink to reduce shelf overlap."""
        if not detections:
            return []

        # --- per-class thresholds (let tiny tags survive) ---
        per_conf = {
            "printer": max(0.45, confidence_threshold),
            "product_box": max(0.45, confidence_threshold),
            "promotional_graphic": 0.35,
            "fact_tag": 0.18,
            "ink_bottle": 0.30,
            "unknown": 0.40,
        }
        filtered = [d for d in detections if d.confidence >= per_conf.get(d.class_name, confidence_threshold)]

        if not filtered:
            return []

        # --- sort by conf then area ---
        sorted_dets = sorted(filtered, key=lambda x: (x.confidence, x.area), reverse=True)

        # --- class-aware IoU ---
        per_iou = {
            "printer": 0.35,
            "product_box": 0.35,
            "promotional_graphic": 0.50,
            "fact_tag": 0.20,     # allow tags to sit near bigger boxes/printers
            "ink_bottle": 0.30,
            "unknown": 0.30,
        }

        merged: List[DetectionBox] = []
        for d in sorted_dets:
            keep = True
            for m in merged:
                # lower IoU when classes differ to avoid wiping out tags near printers
                iou_thresh = per_iou.get(d.class_name, 0.30)
                if m.class_name != d.class_name:
                    iou_thresh = min(0.20, iou_thresh)
                if self._calculate_iou(d, m) > iou_thresh:
                    keep = False
                    break
            if keep:
                merged.append(d)

        # --- ensure expected coverage unchanged (your existing log) ---
        has_top_products = any(d.class_name == "printer" for d in merged)
        has_bottom_products = any(d.class_name == "product_box" for d in merged)
        has_header = any(d.class_name == "promotional_graphic" for d in merged)
        print(f"Coverage check - Top: {has_top_products}, Bottom: {has_bottom_products}, Header: {has_header}")

        # --- ALWAYS shrink before returning ---
        merged = self._shrink_detections(merged)

        # optional: quick debug to verify shrinking visually
        for d in merged:
            if d.class_name in ("printer", "product_box"):
                print(f"shrink -> {d.class_name}: ({d.x1},{d.y1})-({d.x2},{d.y2}) area={d.area}")

        return merged

    def _ensure_product_coverage(self, detections: List[DetectionBox]) -> List[DetectionBox]:
        """Ensure we detect products in expected areas"""

        # Check for gaps in expected product areas
        has_top_products = any(d.class_name == "printer" for d in detections)
        has_bottom_products = any(d.class_name == "product_box" for d in detections)
        has_header = any(d.class_name == "promotional_graphic" for d in detections)

        print(f"Coverage check - Top: {has_top_products}, Bottom: {has_bottom_products}, Header: {has_header}")

        return detections

    def _shrink_box(self, d: DetectionBox, pct: float = 0.06) -> DetectionBox:
        """Shrink a box by pct around its center to reduce shelf overlap."""
        cx = (d.x1 + d.x2) * 0.5
        cy = (d.y1 + d.y2) * 0.5
        w  = max(1.0, (d.x2 - d.x1) * (1.0 - pct))
        h  = max(1.0, (d.y2 - d.y1) * (1.0 - pct))
        x1 = int(cx - w * 0.5)
        y1 = int(cy - h * 0.5)
        x2 = int(cx + w * 0.5)
        y2 = int(cy + h * 0.5)
        # Ensure valid box
        if x2 <= x1: x2 = x1 + 1
        if y2 <= y1: y2 = y1 + 1
        area = int((x2 - x1) * (y2 - y1))

        # Pydantic: use copy(update=...) instead of positional ctor
        return d.model_copy(
            update={"x1": x1, "y1": y1, "x2": x2, "y2": y2, "area": area}
        )


    def _shrink_detections(self, dets: List[DetectionBox]) -> List[DetectionBox]:
        """
        Per-class shrink to avoid cross-shelf bleeding:
        - printers & product boxes: shrink more
        - header promo: slight shrink
        - fact tags: keep as-is (they're already tiny)
        """
        per_class = {
            "printer": 0.08,
            "product_box": 0.08,
            "promotional_graphic": 0.04,
            "fact_tag": 0.00,
            "ink_bottle": 0.06,
            "unknown": 0.06,
        }
        out = []
        for d in dets:
            pct = per_class.get(d.class_name, 0.06)
            out.append(self._shrink_box(d, pct) if pct > 0 else d)
        return out

    def _yolo_small_tag_detection(
        self,
        img_array: np.ndarray,
        price_band: Optional[Tuple[int, int]] = None,   # (y1, y2) of the shelf edge/price strip
        conf: float = 0.03,
        iou: float = 0.20,
        imgsz: int = 1280,
    ) -> List[DetectionBox]:
        """
        YOLO as a proposal generator for tiny shelf-edge tags.
        We compute our own geometry-based confidence so results clear per-class thresholds.
        """
        dets: List[DetectionBox] = []
        if self.detection_model is None:
            return dets

        try:
            r = self.detection_model(img_array, conf=conf, iou=iou, imgsz=imgsz, max_det=600, verbose=False)[0]
            if not hasattr(r, "boxes") or r.boxes is None:
                return dets

            boxes = r.boxes.xyxy.cpu().numpy()
            base_confs = r.boxes.conf.cpu().numpy()
            H, W = img_array.shape[:2]
            img_area = float(W * H)

            # default band: where shelves usually live
            y1_band, y2_band = (int(0.45 * H), int(0.78 * H))
            if price_band is not None:
                y1_band, y2_band = price_band

            for (x1, y1, x2, y2), bconf in zip(boxes, base_confs):
                w = max(1.0, x2 - x1); h = max(1.0, y2 - y1)
                area = w * h; rel = area / img_area
                ar = w / h
                y_center = 0.5 * (y1 + y2)

                # price/fact-tag geometry + band constraint
                if not (y1_band <= y_center <= y2_band):
                    continue
                if not (0.00025 <= rel <= 0.006):
                    continue
                if not (1.15 <= ar <= 6.5):
                    continue

                # geometry-based score so these pass merge thresholds
                # (favor typical tag size/aspect)
                ar_score  = max(0.0, 1.0 - abs(np.log(ar / 3.0)))      # best when ar≈3
                size_score = max(0.0, 1.0 - abs(rel - 0.002) / 0.002)  # best when rel≈0.002
                geo = 0.45 + 0.3 * min(1.0, ar_score) + 0.25 * min(1.0, size_score)

                dets.append(
                    DetectionBox(
                        x1=int(x1), y1=int(y1), x2=int(x2), y2=int(y2),
                        confidence=float(max(bconf, geo)),   # <-- boost with our score
                        class_id=self._get_retail_class_id("fact_tag"),
                        class_name="fact_tag",
                        area=int(area),
                    )
                )
        except Exception as e:
            print(f"YOLO small-tag pass failed: {e}")

        return dets

    def _calculate_iou(self, box1: DetectionBox, box2: DetectionBox) -> float:
        """Calculate IoU between two boxes"""
        x1 = max(box1.x1, box2.x1)
        y1 = max(box1.y1, box2.y1)
        x2 = min(box1.x2, box2.x2)
        y2 = min(box1.y2, box2.y2)

        if x2 <= x1 or y2 <= y1:
            return 0.0

        intersection = (x2 - x1) * (y2 - y1)
        union = box1.area + box2.area - intersection

        return intersection / union if union > 0 else 0.0
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
        super().__init__(
            llm=llm,
            llm_provider=llm_provider,
            llm_model=llm_model,
            **kwargs
        )
        # Initialize the generic shape detector
        self.shape_detector = ImprovedRetailDetector(detection_model)
        self.logger.debug(
            f"Initialized ImprovedRetailDetector with {detection_model}"
        )

    def detect_objects_and_shelves(
        self,
        image: Union[str, Path, Image.Image],
        confidence_threshold: float = 0.5
    ) -> Tuple[List[ShelfRegion], List[DetectionBox]]:
        """
        Step 1: Use GenericShapeDetector to find shapes and boundaries
        """

        self.logger.debug(
            "Step 1: Detecting generic shapes and boundaries..."
        )

        # Use the GenericShapeDetector
        detections = self.shape_detector.detect_retail_products(
            image,
            confidence_threshold
        )

        # Convert to PIL image for shelf organization
        pil_image = Image.open(image) if isinstance(image, (str, Path)) else image
        shelf_regions = self._organize_into_shelves(detections, pil_image.size)

        try:
            tag_dets = self._recover_price_tags(pil_image, shelf_regions)
            if tag_dets:
                detections = list(detections) + tag_dets
                # reuse detector's merge to de-dup
                if hasattr(self.shape_detector, "_intelligent_merge"):
                    detections = self.shape_detector._intelligent_merge(
                        detections,
                        max(0.25, confidence_threshold * 0.8)
                    )
                # shelves might shift slightly with the new boxes
                shelf_regions = self._organize_into_shelves(detections, pil_image.size)
                self.logger.debug(
                    f"Recovered {len(tag_dets)} fact tags on shelf edges"
                )
        except Exception as e:
            self.logger.warning(
                f"Tag recovery failed: {e}"
            )

        self.logger.debug(
            f"Found {len(detections)} objects in {len(shelf_regions)} shelf regions"
        )
        return shelf_regions, detections

    def _recover_price_tags(
        self,
        image: Union[str, Path, Image.Image],
        shelf_regions: List[ShelfRegion],
        *,
        min_width: int = 40,
        max_width: int = 280,
        min_height: int = 14,
        max_height: int = 100,
        iou_suppress: float = 0.3,
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
                        class_name="fact_tag",
                        area=int(rect_area),
                    )
                )

        # Light NMS to avoid duplicates
        def iou(a: DetectionBox, b: DetectionBox) -> float:
            ix1, iy1 = max(a.x1, b.x1), max(a.y1, b.y1)
            ix2, iy2 = min(a.x2, b.x2), min(a.y2, b.y2)
            if ix2 <= ix1 or iy2 <= iy1: return 0.0
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
        """Organize detections into shelf regions based on Y coordinates only"""

        width, height = image_size
        shelf_regions = []

        # Group by Y position - don't assume object types, just position
        header_objects = [d for d in detections if d.y1 < height * 0.2]
        top_objects = [d for d in detections if height * 0.15 <= d.y1 < height * 0.55]
        middle_objects = [d for d in detections if height * 0.45 <= d.y1 < height * 0.7]
        bottom_objects = [d for d in detections if d.y1 >= height * 0.65]

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

        # Create annotated image showing detection boxes
        annotated_image = self._create_annotated_image(image, detections)

        # Build identification prompt (without structured output request)
        prompt = self._build_identification_prompt(detections, shelf_regions)

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
                    identified_products = await client.image_identification(
                        image=image,
                        detections=detections,
                        shelf_regions=shelf_regions,
                        reference_images=reference_images,
                        temperature=0.0,
                        ocr_hints=True
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
                            if product.detection_id and 1 <= product.detection_id <= len(detections):
                                det_idx = product.detection_id - 1  # Convert to 0-based index
                                product.detection_box = detections[det_idx]
                                valid_products.append(product)
                                self.logger.debug(f"Linked {product.product_type} {product.product_model} (ID: {product.detection_id}) to detection box")
                            else:
                                self.logger.warning(f"Product has invalid detection_id: {product.detection_id}")

                        self.logger.debug(f"Successfully linked {len(valid_products)} out of {len(identified_products)} products")
                        return valid_products

                    else:
                        self.logger.error(f"Expected IdentificationResponse, got: {type(identification_response)}")
                        return self._create_simple_fallbacks(detections, shelf_regions)

                else:
                    self.logger.warning("No structured output received")
                    return self._create_simple_fallbacks(detections, shelf_regions)

            except Exception as e:
                self.logger.error(f"Error in structured identification: {e}")
                import traceback
                traceback.print_exc()
                return self._create_simple_fallbacks(detections, shelf_regions)

    def _create_annotated_image(
        self,
        image: Union[str, Path, Image.Image],
        detections: List[DetectionBox]
    ) -> Image.Image:
        """Create an annotated image with detection boxes and IDs"""

        if isinstance(image, (str, Path)):
            pil_image = Image.open(image).copy()
        else:
            pil_image = image.copy()

        draw = ImageDraw.Draw(pil_image)

        for i, detection in enumerate(detections):
            # Draw bounding box
            draw.rectangle(
                [(detection.x1, detection.y1), (detection.x2, detection.y2)],
                outline="red", width=2
            )

            # Add detection ID and confidence
            label = f"ID:{i+1} ({detection.confidence:.2f})"
            draw.text((detection.x1, detection.y1 - 20), label, fill="red")

        return pil_image

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

For each detection (ID 1-{len(detections)}), provide:
- detection_id: The exact ID number from the red bounding box (1-{len(detections)})
- product_type: printer, product_box, fact_tag, promotional_graphic, or ink_bottle
- product_model: Specific model if identifiable (ET-2980, ET-3950, ET-4950)
- confidence: Your confidence (0.0-1.0)
- visual_features: List of visual features
- reference_match: Which reference image matches (or "none")
- shelf_location: header, top, middle, or bottom
- position_on_shelf: left, center, or right

Example format:
{{
  "detections": [
    {{
      "detection_id": 1,
      "product_type": "promotional_graphic",
      "product_model": "Epson EcoTank Advertisement",
      "confidence": 0.95,
      "visual_features": ["large banner", "Epson branding"],
      "reference_match": "none",
      "shelf_location": "header",
      "position_on_shelf": "right",
      "brand": "Epson",
      "advertisement_type": "backlit_graphic"
    }}
  ]
}}

REFERENCE IMAGES show Epson printer models - compare visual design, control panels, ink systems.

CLASSIFICATION RULES FOR ADS
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
        """
        Step 3: Compare identified products against expected planogram

        Args:
            identified_products: Products identified in Step 2
            planogram_description: Expected planogram layout

        Returns:
            Compliance results per shelf level
        """

        results = []

        # Group identified products by shelf level
        products_by_shelf = {}
        for product in identified_products:
            shelf = product.shelf_location
            if shelf not in products_by_shelf:
                products_by_shelf[shelf] = []
            products_by_shelf[shelf].append(product)

        # Check each shelf level
        for shelf_level, expected_products in planogram_description.shelves.items():
            found_products = []
            if shelf_level in products_by_shelf:
                found_products = [
                    self._normalize_product_name(p.product_model or p.product_type)
                    for p in products_by_shelf[shelf_level]
                ]

            # Normalize expected product names
            expected_normalized = [self._normalize_product_name(p) for p in expected_products]
            found_normalized = found_products

            # Calculate compliance
            missing = [p for p in expected_normalized if p not in found_normalized]
            unexpected = [p for p in found_normalized if p not in expected_normalized]

            compliance_score = len(
                [p for p in expected_normalized if p in found_normalized]
            ) / len(expected_normalized) if expected_normalized else 1.0

            # Determine compliance status
            if compliance_score == 1.0 and not unexpected:
                status = ComplianceStatus.COMPLIANT
            elif compliance_score == 0.0:
                status = ComplianceStatus.MISSING
            else:
                status = ComplianceStatus.NON_COMPLIANT

            result = ComplianceResult(
                shelf_level=shelf_level,
                expected_products=expected_products,
                found_products=found_products,
                missing_products=missing,
                unexpected_products=unexpected,
                compliance_status=status,
                compliance_score=compliance_score
            )

            results.append(result)

        return results

    def _normalize_product_name(self, product_name: str) -> str:
        """Normalize product names for comparison"""
        if not product_name:
            return "unknown"

        name = product_name.lower().strip()

        # Map various representations to standard names
        mapping = {
            "et-2980": "et_2980",
            "et2980": "et_2980",
            "et-3950": "et_3950",
            "et3950": "et_3950",
            "et-4950": "et_4950",
            "et4950": "et_4950",
            "printer": "device",
            "fact tag": "fact_tag",
            "price tag": "fact_tag",
            "graphic": "sign",
            "backlit": "sign",
            "promotional_graphic": "backlit_graphic",
            "epson ecotank advertisement": "backlit_graphic",
            "epson eco tank advertisement": "promotional_graphic",
            "graphic": "backlit_graphic",
            "backlit": "backlit_graphic",
        }

        for key, value in mapping.items():
            if key in name:
                return value

        return name

    # Complete Pipeline
    async def run(
        self,
        image: Union[str, Path, Image.Image],
        reference_images: List[Union[str, Path, Image.Image]],
        planogram_description: PlanogramDescription,
        confidence_threshold: float = 0.5,
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
            image, confidence_threshold
        )

        self.logger.debug(
            f"Found {len(detections)} objects in {len(shelf_regions)} shelf regions"
        )

        self.logger.info("Step 2: Identifying objects with LLM...")
        identified_products = await self.identify_objects_with_references(
            image, detections, shelf_regions, reference_images
        )

        print('==== ')
        print(identified_products)

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
