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
    PlanogramDescription,
    TextRequirement,
    PromotionalRequirement,
)
from ..models.compliance import (
    ComplianceResult,
    ComplianceStatus,
    TextComplianceResult,
    TextMatcher,
)

class IdentificationResponse(BaseModel):
    """Response model for product identification"""
    identified_products: List[IdentifiedProduct] = Field(
        alias="detections",
        description="List of identified products from the image"
    )

class RetailDetector:
    """
    Enhanced detector with improved price tag detection and reduced false positives
    """

    def __init__(self, detection_model_name: str = "yolov8n"):
        self.detection_model_name = detection_model_name
        self.detection_model = None
        self._load_detection_model()

        # Enhanced filtering parameters for price tags
        self.price_tag_config = {
            # More restrictive size constraints
            "min_width": 40,        # Increased from 34
            "max_width": 200,       # Decreased from 220
            "min_height": 18,       # Increased from 12
            "max_height": 55,       # Decreased from 60
            "min_aspect_ratio": 1.5, # More restrictive (wider tags)
            "max_aspect_ratio": 8.0, # Less extreme ratios

            # Content validation thresholds
            "min_confidence": 0.4,   # Higher minimum confidence
            "text_score_threshold": 0.3,  # Minimum text likelihood
            "intensity_threshold": 120,   # Minimum brightness for price tags

            # OCR validation
            "require_price_pattern": True,  # Must contain price-like text
            "min_ocr_confidence": 0.6,     # Minimum OCR confidence
        }

    def _load_detection_model(self):
        """Load YOLO model with enhanced error handling"""
        try:
            from ultralytics import YOLO

            model_name = self.detection_model_name.lower()
            if not model_name.endswith('.pt'):
                model_name = f"{model_name}.pt"
            self.detection_model = YOLO(model_name)
            print(f"Loaded {model_name} for enhanced detection")
        except ImportError:
            print("ultralytics not installed")
            self.detection_model = None
        except Exception as e:
            print(f"Failed to load YOLO model: {e}")
            self.detection_model = None

    def preprocess_image_for_detection(
        self, image: Union[str, Path, Image.Image]
    ) -> Tuple[Image.Image, np.ndarray]:
        """Enhance image for better object detection"""
        if isinstance(image, (str, Path)):
            pil_image = Image.open(image)
        else:
            pil_image = image

        if pil_image.mode != 'RGB':
            pil_image = pil_image.convert('RGB')

        # 1. Increase contrast to make objects stand out
        enhancer = ImageEnhance.Contrast(pil_image)
        enhanced = enhancer.enhance(1.4)

        # 2. Increase brightness to handle dim lighting
        enhancer = ImageEnhance.Brightness(enhanced)
        enhanced = enhancer.enhance(1.2)

        # 3. Increase sharpness to make edges clearer
        enhancer = ImageEnhance.Sharpness(enhanced)
        enhanced = enhancer.enhance(1.5)

        # 4. Apply slight color saturation to distinguish products
        enhancer = ImageEnhance.Color(enhanced)
        enhanced = enhancer.enhance(1.1)

        # 5. Apply edge enhancement filter
        enhanced = enhanced.filter(ImageFilter.EDGE_ENHANCE)

        # Convert to numpy for YOLO
        img_array = np.array(enhanced)

        return enhanced, img_array

    def _is_valid_price_tag_size(self, w: int, h: int) -> bool:
        """Enhanced size validation for price tags with stricter constraints"""
        config = self.price_tag_config

        # Basic size constraints
        if not (config["min_width"] <= w <= config["max_width"]):
            return False
        if not (config["min_height"] <= h <= config["max_height"]):
            return False

        # Aspect ratio constraint (price tags are typically wide)
        aspect_ratio = w / h
        if not (config["min_aspect_ratio"] <= aspect_ratio <= config["max_aspect_ratio"]):
            return False

        return True

    def _validate_price_tag_content_enhanced(self, tag_region: np.ndarray) -> Tuple[bool, float]:
        """
        Enhanced content validation with stricter criteria
        Returns: (is_valid, confidence_score)
        """
        if tag_region.size == 0:
            return False, 0.0

        config = self.price_tag_config

        # Convert to grayscale if needed
        if len(tag_region.shape) == 3:
            gray_tag = cv2.cvtColor(tag_region, cv2.COLOR_RGB2GRAY)
        else:
            gray_tag = tag_region

        # 1. Brightness check - price tags are typically light colored
        mean_intensity = np.mean(gray_tag)
        if mean_intensity < config["intensity_threshold"]:
            return False, 0.0

        # 2. Text likelihood check
        text_score = self._calculate_text_likelihood_enhanced(gray_tag)
        if text_score < config["text_score_threshold"]:
            return False, 0.0

        # 3. OCR validation for price patterns
        ocr_confidence = 0.0
        if config["require_price_pattern"]:
            has_price, ocr_confidence = self._validate_price_content_ocr(tag_region)
            if not has_price or ocr_confidence < config["min_ocr_confidence"]:
                return False, 0.0

        # Calculate overall confidence
        intensity_score = min(1.0, mean_intensity / 255.0)
        overall_confidence = (text_score * 0.4 + intensity_score * 0.3 + ocr_confidence * 0.3)

        return True, overall_confidence

    def _calculate_text_likelihood_enhanced(self, gray_region: np.ndarray) -> float:
        """Enhanced text likelihood calculation with better edge detection"""
        if gray_region.size == 0:
            return 0.0

        # 1. Edge density analysis
        edges = cv2.Canny(gray_region, 30, 100)
        edge_density = np.sum(edges > 0) / edges.size

        # 2. Horizontal vs vertical edge analysis (text has more horizontal edges)
        sobelx = cv2.Sobel(gray_region, cv2.CV_64F, 1, 0, ksize=3)
        sobely = cv2.Sobel(gray_region, cv2.CV_64F, 0, 1, ksize=3)

        h_edges = np.sum(np.abs(sobelx))
        v_edges = np.sum(np.abs(sobely))

        if h_edges + v_edges > 0:
            horizontal_ratio = h_edges / (h_edges + v_edges)
        else:
            horizontal_ratio = 0.0

        # 3. Texture analysis
        variance = np.var(gray_region)
        texture_score = min(1.0, variance / 800)

        # 4. Line structure analysis (look for horizontal text lines)
        horizontal_profile = np.mean(gray_region, axis=1)
        profile_variance = np.var(horizontal_profile)
        line_score = min(1.0, profile_variance / 300)

        # Combine scores with emphasis on horizontal structure
        text_likelihood = (
            edge_density * 0.3 +
            horizontal_ratio * 0.4 +
            texture_score * 0.2 +
            line_score * 0.1
        )

        return min(1.0, text_likelihood)

    def _validate_price_content_ocr(self, tag_region: np.ndarray) -> Tuple[bool, float]:
        """
        Enhanced OCR validation specifically for price content
        Returns: (has_price_pattern, confidence)
        """
        try:
            import pytesseract

            # Convert to grayscale if needed
            if len(tag_region.shape) == 3:
                gray = cv2.cvtColor(tag_region, cv2.COLOR_RGB2GRAY)
            else:
                gray = tag_region

            # Enhance for OCR
            # Resize for better OCR
            height, width = gray.shape
            if height < 40 or width < 100:
                scale_factor = max(40/height, 100/width, 2.0)
                new_height = int(height * scale_factor)
                new_width = int(width * scale_factor)
                gray = cv2.resize(gray, (new_width, new_height), interpolation=cv2.INTER_CUBIC)

            # Apply CLAHE for better contrast
            clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8,8))
            enhanced = clahe.apply(gray)

            # Threshold for better text detection
            _, thresh = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

            # OCR with configuration optimized for price tags
            custom_config = r'--oem 3 --psm 8 -c tessedit_char_whitelist=0123456789.$€£¢¥₹₽'
            ocr_result = pytesseract.image_to_data(
                thresh,
                config=custom_config,
                output_type=pytesseract.Output.DICT
            )

            # Extract text and confidence
            text_parts = []
            confidences = []

            for i, conf in enumerate(ocr_result['conf']):
                if int(conf) > 30:  # Only consider high-confidence text
                    text = ocr_result['text'][i].strip()
                    if text:
                        text_parts.append(text)
                        confidences.append(int(conf))

            full_text = ' '.join(text_parts)
            avg_confidence = np.mean(confidences) / 100.0 if confidences else 0.0

            # Look for price patterns
            price_patterns = [
                r'\$\s*\d{1,4}(?:[.,]\d{2})?',  # $XX.XX
                r'€\s*\d{1,4}(?:[.,]\d{2})?',   # €XX.XX
                r'£\s*\d{1,4}(?:[.,]\d{2})?',   # £XX.XX
                r'\d{1,4}(?:[.,]\d{2})?\s*\$',  # XX.XX$
                r'\d{1,4}(?:[.,]\d{2})?',       # Just numbers
            ]

            has_price = any(re.search(pattern, full_text) for pattern in price_patterns)

            # Additional validation - check for minimum number of digits
            digit_count = sum(c.isdigit() for c in full_text)
            has_sufficient_digits = digit_count >= 2

            return has_price and has_sufficient_digits, avg_confidence

        except ImportError:
            # Fallback without OCR - use pattern matching on image features
            return self._fallback_price_detection(tag_region)
        except Exception as e:
            print(f"OCR validation failed: {e}")
            return False, 0.0

    def _fallback_price_detection(self, tag_region: np.ndarray) -> Tuple[bool, float]:
        """Fallback price detection without OCR"""
        if len(tag_region.shape) == 3:
            gray = cv2.cvtColor(tag_region, cv2.COLOR_RGB2GRAY)
        else:
            gray = tag_region

        # Look for digit-like patterns using template matching or contour analysis
        # This is a simplified fallback
        text_score = self._calculate_text_likelihood_enhanced(gray)
        intensity_ok = np.mean(gray) > 140

        return text_score > 0.5 and intensity_ok, text_score * 0.7

    def _has_price_amount(self, roi_rgb: np.ndarray, min_score_noocr: float = 0.7) -> bool:
        """
        Enhanced price amount detection with stricter validation
        """
        try:
            import pytesseract

            # Convert and enhance
            gray = cv2.cvtColor(roi_rgb, cv2.COLOR_RGB2GRAY)

            # More aggressive enhancement for small price tags
            gray = cv2.resize(gray, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)

            # Apply CLAHE for better contrast
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
            enhanced = clahe.apply(gray)

            # Threshold
            _, thresh = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

            # OCR with strict whitelist
            config = "--oem 3 --psm 8 -c tessedit_char_whitelist=$€£¢¥₹₽0123456789.,"
            text = pytesseract.image_to_string(thresh, config=config).strip()

            # More strict price pattern matching
            price_patterns = [
                r'[\$€£¢¥₹₽]\s*\d{1,4}(?:[.,]\d{2})?',
                r'\d{1,4}(?:[.,]\d{2})?\s*[\$€£¢¥₹₽]',
                r'\d{2,4}(?:[.,]\d{2})?'  # At least 2 digits for price
            ]

            has_price = any(re.search(pattern, text) for pattern in price_patterns)
            digit_count = sum(c.isdigit() for c in text)

            return has_price and digit_count >= 2

        except ImportError:
            # Fallback without OCR - much stricter requirements
            score = self._calculate_text_likelihood_enhanced(
                cv2.cvtColor(roi_rgb, cv2.COLOR_RGB2GRAY)
            )
            return score >= min_score_noocr

    def detect_retail_products(
        self,
        image: Union[str, Path, Image.Image],
        confidence_threshold: float = 0.5
    ) -> List[DetectionBox]:
        """Enhanced retail product detection with improved price tag filtering"""

        # Preprocess image
        enhanced_pil, img_array = self.preprocess_image_for_detection(image)

        all_detections: List[DetectionBox] = []

        # 1) Main YOLO detection (for larger objects)
        yolo_detections = self._enhanced_yolo_detection(img_array, confidence_threshold)
        all_detections.extend(yolo_detections)

        # 2) Retail regions (rule-based anchors)
        retail_detections = self._detect_retail_regions(img_array, confidence_threshold)
        all_detections.extend(retail_detections)

        # 3) Large rectangular products
        product_detections = self._detect_large_products(img_array, confidence_threshold)
        all_detections.extend(product_detections)

        # 4) IMPROVED: Enhanced price tag detection with stricter validation
        price_tags = self._detect_price_tags_enhanced_strict(img_array)
        all_detections.extend(price_tags)

        # 5) Second YOLO pass for small tags (with enhanced filtering)
        small_tags = self._yolo_small_tag_detection_enhanced(img_array)
        all_detections.extend(small_tags)

        # 6) Enhanced merging with better NMS
        final_detections = self._intelligent_merge_enhanced(all_detections, confidence_threshold)
        final_detections = self._shrink_detections(final_detections)

        print(f"Enhanced detection found {len(final_detections)} retail products")
        for i, det in enumerate(final_detections):
            w, h = det.x2 - det.x1, det.y2 - det.y1
            print(f"  {i+1}: {det.class_name} at ({det.x1},{det.y1},{det.x2},{det.y2}) "
                  f"size=({w}x{h}) conf={det.confidence:.2f}")

        return final_detections

    def _detect_price_tags_enhanced_strict(self, img_array: np.ndarray) -> List[DetectionBox]:
        """
        Enhanced price tag detection with much stricter validation
        """
        height, width = img_array.shape[:2]
        detections = []

        # Focus on specific shelf edge regions only
        shelf_edges = [
            {"y1": int(0.50 * height), "y2": int(0.65 * height), "name": "top_shelf_edge"},
            {"y1": int(0.70 * height), "y2": int(0.82 * height), "name": "middle_shelf_edge"},
            {"y1": int(0.87 * height), "y2": int(0.97 * height), "name": "bottom_shelf_edge"},
        ]

        for edge in shelf_edges:
            y1, y2 = edge["y1"], edge["y2"]
            if y2 <= y1:
                continue

            # Extract shelf edge strip
            edge_strip = img_array[y1:y2, :]
            gray_strip = cv2.cvtColor(edge_strip, cv2.COLOR_RGB2GRAY)

            # Enhanced preprocessing for price tag detection
            # 1. CLAHE for better local contrast
            clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8,8))
            enhanced = clahe.apply(gray_strip)

            # 2. Focus on light regions (price tags are typically white/light)
            # Use a higher threshold to focus on lighter regions
            _, light_regions = cv2.threshold(enhanced, 160, 255, cv2.THRESH_BINARY)

            # 3. Morphological operations to connect text regions
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 3))
            connected = cv2.morphologyEx(light_regions, cv2.MORPH_CLOSE, kernel)

            # 4. Find contours
            contours, _ = cv2.findContours(connected, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            for contour in contours:
                x, y, w, h = cv2.boundingRect(contour)

                # Apply strict size filtering
                if not self._is_valid_price_tag_size(w, h):
                    continue

                # Extract tag region for validation
                tag_region = edge_strip[y:y+h, x:x+w]

                # Enhanced content validation
                is_valid, confidence = self._validate_price_tag_content_enhanced(tag_region)

                if not is_valid:
                    continue

                # Additional geometric validation
                contour_area = cv2.contourArea(contour)
                bbox_area = w * h
                rectangularity = contour_area / bbox_area if bbox_area > 0 else 0

                if rectangularity < 0.6:  # Must be reasonably rectangular
                    continue

                # Adjust confidence based on rectangularity and position
                position_bonus = 0.1 if edge["name"] in ["top_shelf_edge", "bottom_shelf_edge"] else 0
                final_confidence = min(0.95, confidence + position_bonus * rectangularity)

                if final_confidence >= self.price_tag_config["min_confidence"]:
                    detection = DetectionBox(
                        x1=x, y1=y1+y, x2=x+w, y2=y1+y+h,
                        confidence=final_confidence,
                        class_id=self._get_retail_class_id("price_tag"),
                        class_name="price_tag",
                        area=w*h
                    )
                    detections.append(detection)

        print(f"Strict price tag detection found {len(detections)} price tags")
        return detections

    def _yolo_small_tag_detection_enhanced(self, img_array: np.ndarray) -> List[DetectionBox]:
        """
        Enhanced YOLO small tag detection with stricter filtering
        """
        dets: List[DetectionBox] = []
        if self.detection_model is None:
            return dets

        try:
            results = self.detection_model(
                img_array,
                conf=0.02,  # Very low to catch small objects
                iou=0.15,   # Lower IoU for small objects
                imgsz=1280,  # Higher resolution for small objects
                max_det=300,  # Fewer detections to focus on quality
                verbose=False
            )[0]

            if not hasattr(results, "boxes") or results.boxes is None:
                return dets

            boxes = results.boxes.xyxy.cpu().numpy()
            base_confs = results.boxes.conf.cpu().numpy()
            H, W = img_array.shape[:2]
            img_area = float(W * H)

            # More focused band for price tags
            y1_band, y2_band = (int(0.45*H), int(0.98*H))

            for (x1, y1, x2, y2), bconf in zip(boxes, base_confs):
                w = max(1.0, x2 - x1)
                h = max(1.0, y2 - y1)
                area = w * h
                rel_area = area / img_area
                aspect_ratio = w / h
                y_center = 0.5 * (y1 + y2)

                # Stricter geometric constraints
                if not (y1_band <= y_center <= y2_band):
                    continue
                if not (0.0002 <= rel_area <= 0.006):  # Tighter area range
                    continue
                if not (2.0 <= aspect_ratio <= 6.0):   # Tighter aspect ratio
                    continue

                # Additional size validation
                if not self._is_valid_price_tag_size(int(w), int(h)):
                    continue

                # Content validation for small YOLO detections
                roi = img_array[int(y1):int(y2), int(x1):int(x2)]
                if roi.size > 0:
                    is_valid, content_conf = self._validate_price_tag_content_enhanced(roi)
                    if not is_valid:
                        continue

                    # Use content confidence instead of just geometric score
                    final_confidence = max(bconf, content_conf * 0.8)
                else:
                    final_confidence = bconf

                if final_confidence >= 0.4:
                    dets.append(
                        DetectionBox(
                            x1=int(x1), y1=int(y1), x2=int(x2), y2=int(y2),
                            confidence=float(final_confidence),
                            class_id=self._get_retail_class_id("price_tag"),
                            class_name="price_tag",
                            area=int(area),
                        )
                    )
        except Exception as e:
            print(f"Enhanced YOLO small-tag detection failed: {e}")

        return dets

    def _intelligent_merge_enhanced(self, detections: List[DetectionBox], confidence_threshold: float) -> List[DetectionBox]:
        """
        Enhanced merging with better price tag handling and false positive reduction
        """
        if not detections:
            return []

        # Enhanced per-class confidence thresholds
        per_conf = {
            "printer": max(0.45, confidence_threshold),
            "product_box": max(0.45, confidence_threshold),
            "promotional_graphic": 0.35,
            "price_tag": 0.5,  # Significantly higher threshold for price tags
            "ink_bottle": 0.30,
            "unknown": 0.40,
        }

        # Filter by enhanced confidence thresholds
        filtered = [d for d in detections if d.confidence >= per_conf.get(d.class_name, confidence_threshold)]

        if not filtered:
            return []

        # Sort by confidence and area
        sorted_dets = sorted(filtered, key=lambda x: (x.confidence, x.area), reverse=True)

        # Enhanced IoU thresholds with stricter price tag merging
        per_iou = {
            "printer": 0.3,
            "product_box": 0.3,
            "promotional_graphic": 0.4,
            "price_tag": 0.2,  # Higher IoU threshold to prevent overlapping tags
            "ink_bottle": 0.25,
            "unknown": 0.3,
        }

        merged = []
        for d in sorted_dets:
            keep = True
            for m in merged:
                iou_thresh = per_iou.get(d.class_name, 0.3)

                # Special handling for price tags vs other objects
                if d.class_name == "price_tag" and m.class_name != "price_tag":
                    # Check if price tag overlaps significantly with larger objects
                    if self._calculate_iou(d, m) > 0.15:
                        keep = False
                        break
                elif m.class_name == "price_tag" and d.class_name != "price_tag":
                    # Larger objects take precedence over price tags if they overlap
                    if self._calculate_iou(d, m) > 0.15:
                        # Remove the existing price tag and add the larger object
                        merged = [x for x in merged if x != m]
                elif d.class_name == m.class_name:
                    # Same class merging
                    if self._calculate_iou(d, m) > iou_thresh:
                        keep = False
                        break

            if keep:
                merged.append(d)

        # Final validation pass for price tags
        validated_merged = []
        for detection in merged:
            if detection.class_name == "price_tag":
                # Double-check price tag validity
                w, h = detection.x2 - detection.x1, detection.y2 - detection.y1
                if self._is_valid_price_tag_size(w, h) and detection.confidence >= 0.5:
                    validated_merged.append(detection)
            else:
                validated_merged.append(detection)

        return validated_merged

    # Keep all existing methods that are working well
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

    # Keep existing methods that work well
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
            bilat = cv2.bilateralFilter(gray, 7, 50, 50)
            edges = cv2.Canny(bilat, 40, 120)
            closed = cv2.morphologyEx(
                edges,
                cv2.MORPH_CLOSE,
                cv2.getStructuringElement(cv2.MORPH_RECT, (9, 7)),
                iterations=2
            )
            contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            height, width = img_array.shape[:2]
            min_area = width * height * 0.005  # Minimum 0.5% of image
            max_area = width * height * 0.35   # Maximum 35% of image

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
        y_center = (y1 + y2) * 0.5
        y_ratio = y_center / height
        relative_area = area / (width * height)
        aspect_ratio = (x2 - x1) / max(1.0, (y2 - y1))

        # Header (promo)
        if y_ratio < 0.22:
            return "promotional_graphic"

        # Top shelf (printers)
        elif y_ratio < 0.58:
            return "printer" if relative_area > 0.015 else "price_tag"

        # Middle/Bottom shelves (boxes)
        else:
            return "product_box" if relative_area > 0.008 else "price_tag"

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
        elif y_ratio < 0.58:
            return "printer"
        else:
            return "product_box"

    def _get_retail_class_id(self, class_name: str) -> int:
        """Get class ID for retail products"""
        mapping = {
            "printer": 100,
            "product_box": 101,
            "fact_tag": 102,      # Keep for backward compatibility
            "price_tag": 102,     # Same ID as fact_tag
            "promotional_graphic": 103,
            "ink_bottle": 104,
            "unknown": 199
        }
        return mapping.get(class_name, 199)

    def _shrink_detections(self, dets: List[DetectionBox]) -> List[DetectionBox]:
        """
        Per-class shrink to avoid cross-shelf bleeding
        """
        per_class = {
            "printer": 0.08,
            "product_box": 0.08,
            "promotional_graphic": 0.04,
            "fact_tag": 0.00,     # Keep for backward compatibility
            "price_tag": 0.00,    # Don't shrink price tags (they're already small)
            "ink_bottle": 0.06,
            "unknown": 0.06,
        }
        out = []
        for d in dets:
            pct = per_class.get(d.class_name, 0.06)
            out.append(self._shrink_box(d, pct) if pct > 0 else d)
        return out

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

        return d.model_copy(
            update={"x1": x1, "y1": y1, "x2": x2, "y2": y2, "area": area}
        )

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

    # Additional helper methods for compatibility
    def create_mser(self, delta=5, min_area=200, max_area=5000):
        """OpenCV-version-safe MSER factory."""
        try:
            # Some builds accept only _delta as kwarg
            mser = cv2.MSER_create(_delta=delta)
            if hasattr(mser, "setMinArea"): mser.setMinArea(int(min_area))
            if hasattr(mser, "setMaxArea"): mser.setMaxArea(int(max_area))
            return mser
        except TypeError:
            # Older builds: positionals
            try:
                return cv2.MSER_create(int(delta), int(min_area), int(max_area))
            except TypeError:
                # Fallback: create default and set via setters
                mser = cv2.MSER_create()
                if hasattr(mser, "setDelta"):    mser.setDelta(int(delta))
                if hasattr(mser, "setMinArea"):  mser.setMinArea(int(min_area))
                if hasattr(mser, "setMaxArea"):  mser.setMaxArea(int(max_area))
                return mser

    def _calculate_text_likelihood(self, region: np.ndarray) -> float:
        """Legacy method for backward compatibility"""
        return self._calculate_text_likelihood_enhanced(region)

    def _detect_price_tags_enhanced(self, img_array: np.ndarray) -> List[DetectionBox]:
        """Legacy method name for backward compatibility"""
        return self._detect_price_tags_enhanced_strict(img_array)

    def _yolo_small_tag_detection(
        self,
        img_array: np.ndarray,
        price_band: Optional[Tuple[int, int]] = None,
        conf: float = 0.03,
        iou: float = 0.20,
        imgsz: int = 1280
    ) -> List[DetectionBox]:
        """Legacy method for backward compatibility"""
        return self._yolo_small_tag_detection_enhanced(img_array)

    def _intelligent_merge(
        self,
        detections: List[DetectionBox],
        confidence_threshold: float
    ) -> List[DetectionBox]:
        """Legacy method for backward compatibility"""
        return self._intelligent_merge_enhanced(detections, confidence_threshold)

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
        self.shape_detector = RetailDetector(detection_model)
        self.logger.debug(
            f"Initialized RetailDetector with {detection_model}"
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
                    extra_refs = [annotated_image] + (reference_images or [])
                    identified_products = await client.image_identification(
                        image=image,
                        prompt=prompt,
                        detections=detections,
                        shelf_regions=shelf_regions,
                        reference_images=extra_refs,
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

IMPORTANT NAMING RULES:
1. For printer devices: Use model name only (e.g., "ET-2980", "ET-3950", "ET-4950")
2. For product boxes: Use model name + " box" (e.g., "ET-2980 box", "ET-3950 box", "ET-4950 box")
3. For promotional graphics: Use descriptive name (e.g., "Epson EcoTank Advertisement")
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
        """
        FIXED: Step 3: Compare identified products against expected planogram
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
            promotional_products = []

            # FIX: Process products in the current shelf level correctly
            if shelf_level in products_by_shelf:
                for product in products_by_shelf[shelf_level]:
                    if product.product_type == "promotional_graphic":
                        promotional_products.append(product)
                        # FIX: Also add promotional products to found_products for counting
                        found_products.append(
                            self._normalize_product_name(product.product_model or "promotional_graphic")
                        )
                    elif product.product_type not in ['fact_tag', 'price_tag']:
                        # Only count non-tag products
                        product_name = self._normalize_product_name(
                            product.product_model or product.product_type
                        )
                        found_products.append(product_name)

            # Normalize expected product names
            expected_normalized = [
                self._normalize_product_name(p) for p in expected_products
            ]

            # Debug logging
            print(f"\nShelf Level: {shelf_level}")
            print(f"Expected (raw): {expected_products}")
            print(f"Expected (normalized): {expected_normalized}")
            print(f"Found products: {[p.product_model or p.product_type for p in products_by_shelf.get(shelf_level, []) if p.product_type not in ['fact_tag', 'price_tag']]}")
            print(f"Found (normalized): {found_products}")
            print(f"Promotional products found: {len(promotional_products)}")

            # Calculate compliance
            missing = [p for p in expected_normalized if p not in found_products]
            unexpected = [p for p in found_products if p not in expected_normalized]

            basic_compliance_score = (
                len([p for p in expected_normalized if p in found_products]) / len(expected_normalized)
                if expected_normalized else 1.0
            )

            # Initialize text compliance variables with defaults
            text_compliance_results = []
            text_compliance_score = 1.0
            overall_text_compliant = True

            # FIX: Check if promotional_requirements exists and has the shelf_level
            if (hasattr(planogram_description, 'promotional_requirements') and
                planogram_description.promotional_requirements and
                shelf_level in planogram_description.promotional_requirements):

                promo_requirements = planogram_description.promotional_requirements[shelf_level]

                for requirement in promo_requirements:
                    # Find matching promotional products
                    matching_promos = [
                        p for p in promotional_products
                        if (not requirement.brand or p.brand == requirement.brand) and
                        (not requirement.advertisement_type or p.advertisement_type == requirement.advertisement_type)
                    ]

                    if not matching_promos:
                        # No promotional graphic found
                        for text_req in requirement.required_texts:
                            text_compliance_results.append(
                                TextComplianceResult(
                                    required_text=text_req.required_text,
                                    found=False,
                                    matched_features=[],
                                    confidence=0.0,
                                    match_type=text_req.match_type
                                )
                            )
                        overall_text_compliant = False
                        continue

                    # Check text requirements for each matching promotional product
                    for text_req in requirement.required_texts:
                        # Combine visual features from all matching promotional products
                        all_visual_features = []
                        for promo in matching_promos:
                            if promo.visual_features:
                                all_visual_features.extend(promo.visual_features)

                        # Check against combined features
                        result = TextMatcher.check_text_match(
                            required_text=text_req.required_text,
                            visual_features=all_visual_features,
                            match_type=text_req.match_type,
                            case_sensitive=text_req.case_sensitive,
                            confidence_threshold=text_req.confidence_threshold
                        )
                        text_compliance_results.append(result)

                        if not result.found:
                            overall_text_compliant = False

            # Calculate overall text compliance score
            if text_compliance_results:
                text_compliance_score = sum(
                    r.confidence for r in text_compliance_results if r.found
                ) / len(text_compliance_results)

            # Get compliance threshold for this shelf
            compliance_threshold = 0.8
            if hasattr(planogram_description, 'compliance_thresholds'):
                compliance_threshold = planogram_description.compliance_thresholds.get(shelf_level, 0.8)

            # Determine overall compliance status using string values (FIX for enum issue)
            if basic_compliance_score >= compliance_threshold and not unexpected and overall_text_compliant:
                status = ComplianceStatus.COMPLIANT
            elif basic_compliance_score == 0.0:
                status = ComplianceStatus.MISSING
            else:
                status = ComplianceStatus.NON_COMPLIANT

            # Combine scores (weighted: 70% product compliance, 30% text compliance)
            combined_score = (basic_compliance_score * 0.7) + (text_compliance_score * 0.3)

            # FIX: Always provide valid values instead of None
            result = ComplianceResult(
                shelf_level=shelf_level,
                expected_products=expected_products,
                found_products=found_products,
                missing_products=missing,
                unexpected_products=unexpected,
                compliance_status=status,  # Use string value to avoid enum error
                compliance_score=combined_score,
                text_compliance_results=text_compliance_results,  # Always provide list (never None)
                text_compliance_score=text_compliance_score,      # Always provide float (never None)
                overall_text_compliant=overall_text_compliant     # Always provide bool (never None)
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

    def create_planogram_description(
        self,
        brand: str = "Epson",
        category: str = "Printers",
        aisle: str = "Electronics",
        shelves: Optional[Dict[str, List[str]]] = None,
        add_text_requirements: bool = True,
        compliance_thresholds: Optional[Dict[str, float]] = None
    ) -> PlanogramDescription:
        """
        Create a planogram description with optional text requirements

        Args:
            brand: Brand name (e.g., "Epson")
            category: Product category (e.g., "Printers")
            aisle: Store aisle location
            shelves: Dict of shelf_level -> list of expected products
            add_text_requirements: Whether to add promotional text requirements
            compliance_thresholds: Custom compliance thresholds per shelf

        Returns:
            PlanogramDescription object ready for compliance checking
        """

        # Default shelves if not provided
        if shelves is None:
            shelves = {
                "header": ["Epson EcoTank Advertisement"],
                "top": ["ET-2980", "ET-3950", "ET-4950"],
                "middle": ["ET-2980 box", "ET-3950 box", "ET-4950 box"]
            }

        # Default compliance thresholds
        if compliance_thresholds is None:
            compliance_thresholds = {
                "header": 0.9,
                "top": 0.8,
                "middle": 0.8,
                "bottom": 0.8
            }

        promotional_requirements = {}

        if add_text_requirements:
            # Text requirements for promotional graphics
            goodbye_cartridges_req = TextRequirement(
                required_text="Goodbye Cartridges",
                match_type="contains",
                case_sensitive=False
            )

            hello_savings_req = TextRequirement(
                required_text="Hello Savings",
                match_type="contains",
                case_sensitive=False
            )

            epson_logo_req = TextRequirement(
                required_text="Epson",
                match_type="contains",
                case_sensitive=False
            )

            # Promotional requirement for header
            header_promo_req = PromotionalRequirement(
                product_type="promotional_graphic",
                brand=brand,
                advertisement_type="backlit_graphic",
                required_texts=[goodbye_cartridges_req, hello_savings_req, epson_logo_req],
                allow_additional_text=True
            )

            # Add promotional requirements for header if it exists
            if "header" in shelves:
                promotional_requirements["header"] = [header_promo_req]

        return PlanogramDescription(
            shelves=shelves,
            brand=brand,
            category=category,
            aisle=aisle,
            promotional_requirements=promotional_requirements,
            compliance_thresholds=compliance_thresholds
        )
