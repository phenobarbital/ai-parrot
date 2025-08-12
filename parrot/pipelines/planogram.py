"""
3-Step Planogram Compliance Pipeline
Step 1: Object Detection (YOLO/ResNet)
Step 2: LLM Object Identification with Reference Images
Step 3: Planogram Comparison and Compliance Verification
"""
from typing import List, Dict, Any, Optional, Union, Tuple
import traceback
from pathlib import Path
from datetime import datetime
from PIL import Image, ImageDraw
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


class GenericShapeDetector:
    """
    Detects shapes with basic classification (box, card, region) and confidence filtering
    """

    def __init__(self, detection_model_name: str = "yolov8n"):
        self.detection_model_name = detection_model_name
        self.detection_model = None
        self._load_detection_model()

    def _load_detection_model(self):
        """Load YOLO model for generic object detection"""
        try:
            from ultralytics import YOLO
            self.detection_model = YOLO(self.detection_model_name)
            print(f"Loaded {self.detection_model_name} for shape detection")
        except ImportError:
            print("ultralytics not installed. Using alternative detection methods.")
            self.detection_model = None
        except Exception as e:
            print(f"Failed to load YOLO model: {e}")
            self.detection_model = None

    def detect_all_shapes_and_boxes(
        self,
        image: Union[str, Path, Image.Image],
        confidence_threshold: float = 0.5
    ) -> List[DetectionBox]:
        """
        Detect shapes with basic classification and confidence filtering
        """

        if isinstance(image, (str, Path)):
            pil_image = Image.open(image)
        else:
            pil_image = image

        img_array = np.array(pil_image)
        all_detections = []

        # Method 1: YOLO for any detectable objects
        yolo_detections = self._yolo_detect_with_basic_classification(img_array, confidence_threshold)
        all_detections.extend(yolo_detections)

        # Method 2: Computer vision edge/contour detection
        cv_detections = self._cv_detect_shapes_classified(img_array, confidence_threshold)
        all_detections.extend(cv_detections)

        # Method 3: Grid-based region detection (only if we found very few objects)
        if len(all_detections) < 5:
            grid_detections = self._grid_detect_classified_regions(img_array, confidence_threshold)
            all_detections.extend(grid_detections)

        # Filter by confidence threshold and remove overlaps
        filtered_detections = self._filter_and_merge_detections(all_detections, confidence_threshold)

        print(f"Shape detection found {len(filtered_detections)} objects (after filtering conf >= {confidence_threshold})")
        for i, det in enumerate(filtered_detections):
            print(f"  {i+1}: {det.class_name} at ({det.x1},{det.y1},{det.x2},{det.y2}) conf={det.confidence:.2f}")

        return filtered_detections

    def _yolo_detect_with_basic_classification(self, img_array: np.ndarray, confidence_threshold: float) -> List[DetectionBox]:
        """Use YOLO with basic shape classification"""
        detections = []

        if self.detection_model is None:
            return detections

        try:
            # Run YOLO with lower confidence to catch more objects
            results = self.detection_model(img_array, conf=max(0.1, confidence_threshold * 0.3))

            if hasattr(results[0], 'boxes') and results[0].boxes is not None:
                boxes = results[0].boxes.xyxy.cpu().numpy()
                confidences = results[0].boxes.conf.cpu().numpy()

                for i in range(len(boxes)):
                    x1, y1, x2, y2 = boxes[i]
                    conf = float(confidences[i])
                    area = (x2-x1) * (y2-y1)

                    # Basic shape classification based on dimensions and position
                    shape_class = self._classify_shape_by_geometry(
                        x1, y1, x2, y2, area, img_array.shape
                    )

                    detection = DetectionBox(
                        x1=int(x1), y1=int(y1), x2=int(x2), y2=int(y2),
                        confidence=conf,
                        class_id=self._get_class_id(shape_class),
                        class_name=shape_class,
                        area=int(area)
                    )
                    detections.append(detection)

            print(f"YOLO detected {len(detections)} objects (before confidence filtering)")

        except Exception as e:
            print(f"YOLO detection failed: {e}")

        return detections

    def _cv_detect_shapes_classified(self, img_array: np.ndarray, confidence_threshold: float) -> List[DetectionBox]:
        """Use computer vision with basic shape classification"""
        detections = []

        try:
            import cv2

            # Convert to grayscale
            gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)

            # Apply edge detection
            edges = cv2.Canny(gray, 50, 150)

            # Find contours
            contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            for contour in contours:
                # Get bounding rectangle
                x, y, w, h = cv2.boundingRect(contour)
                area = w * h

                # Filter by reasonable size
                if area > 1000 and w > 30 and h > 30:

                    # Calculate confidence based on contour quality
                    contour_area = cv2.contourArea(contour)
                    rect_area = w * h
                    base_confidence = min(0.8, contour_area / rect_area) if rect_area > 0 else 0.4

                    # Classify shape based on geometry
                    shape_class = self._classify_shape_by_geometry(
                        x, y, x+w, y+h, area, img_array.shape
                    )

                    detection = DetectionBox(
                        x1=x, y1=y, x2=x+w, y2=y+h,
                        confidence=base_confidence,
                        class_id=self._get_class_id(shape_class),
                        class_name=shape_class,
                        area=area
                    )
                    detections.append(detection)

            print(f"CV edge detection found {len(detections)} shapes (before filtering)")

        except Exception as e:
            print(f"CV shape detection failed: {e}")

        return detections

    def _grid_detect_classified_regions(self, img_array: np.ndarray, confidence_threshold: float) -> List[DetectionBox]:
        """Grid-based detection with shape classification"""
        height, width = img_array.shape[:2]
        detections = []

        # Define regions with expected shape types
        regions = [
            # Header region - likely banner/graphic
            {"x1": 0.05, "y1": 0.02, "x2": 0.95, "y2": 0.18, "type": "banner"},

            # Top shelf regions - likely rectangular boxes/devices
            {"x1": 0.02, "y1": 0.15, "x2": 0.32, "y2": 0.55, "type": "box"},
            {"x1": 0.35, "y1": 0.15, "x2": 0.65, "y2": 0.55, "type": "box"},
            {"x1": 0.68, "y1": 0.15, "x2": 0.98, "y2": 0.55, "type": "box"},

            # Middle shelf regions - likely small cards/tags
            {"x1": 0.08, "y1": 0.50, "x2": 0.25, "y2": 0.65, "type": "card"},
            {"x1": 0.40, "y1": 0.50, "x2": 0.60, "y2": 0.65, "type": "card"},
            {"x1": 0.75, "y1": 0.50, "x2": 0.92, "y2": 0.65, "type": "card"},

            # Bottom shelf regions - likely boxes
            {"x1": 0.02, "y1": 0.65, "x2": 0.32, "y2": 0.95, "type": "box"},
            {"x1": 0.35, "y1": 0.65, "x2": 0.65, "y2": 0.95, "type": "box"},
            {"x1": 0.68, "y1": 0.65, "x2": 0.98, "y2": 0.95, "type": "box"},
        ]

        for region in regions:
            x1 = int(width * region["x1"])
            y1 = int(height * region["y1"])
            x2 = int(width * region["x2"])
            y2 = int(height * region["y2"])

            # Check if this region has sufficient content
            if y2 > y1 and x2 > x1:
                region_img = img_array[y1:y2, x1:x2]
                if region_img.size > 0:
                    gray_region = np.mean(region_img, axis=2) if len(region_img.shape) == 3 else region_img
                    variance = np.var(gray_region)

                    # Only create detection if there's significant content
                    if variance > 800:  # Higher threshold for grid regions
                        confidence = min(0.6, variance / 3000)  # Lower base confidence for grid

                        detection = DetectionBox(
                            x1=x1, y1=y1, x2=x2, y2=y2,
                            confidence=confidence,
                            class_id=self._get_class_id(region["type"]),
                            class_name=region["type"],
                            area=(x2-x1) * (y2-y1)
                        )
                        detections.append(detection)

        print(f"Grid detection found {len(detections)} classified regions")
        return detections

    def _classify_shape_by_geometry(self, x1: float, y1: float, x2: float, y2: float,
                                   area: float, img_shape: Tuple[int, int]) -> str:
        """Classify shape based on geometric properties"""

        width = x2 - x1
        height = y2 - y1
        aspect_ratio = width / height if height > 0 else 1.0
        img_height, img_width = img_shape[:2]

        # Relative position in image
        y_ratio = y1 / img_height
        x_ratio = x1 / img_width

        # Size categories
        relative_area = area / (img_width * img_height)

        # Classification logic
        if y_ratio < 0.2:  # Top of image
            if relative_area > 0.15:
                return "banner"  # Large horizontal element at top
            else:
                return "element"  # Smaller top elements

        elif aspect_ratio > 3.0:  # Very wide
            return "banner"

        elif aspect_ratio < 0.3:  # Very tall
            return "column"

        elif relative_area < 0.01:  # Very small
            return "tag"

        elif 0.7 <= aspect_ratio <= 1.4:  # Square-ish
            if relative_area > 0.05:
                return "box"  # Large square = box/device
            else:
                return "card"  # Small square = card/tag

        elif aspect_ratio > 1.4:  # Rectangular (wider)
            if relative_area > 0.03:
                return "box"  # Large rectangle = box
            else:
                return "card"  # Small rectangle = card

        else:  # Default
            return "object"

    def _get_class_id(self, class_name: str) -> int:
        """Get numeric class ID for shape type"""
        class_mapping = {
            "box": 100,
            "card": 101,
            "banner": 102,
            "tag": 103,
            "element": 104,
            "column": 105,
            "object": 199
        }
        return class_mapping.get(class_name, 199)

    def _filter_and_merge_detections(self, detections: List[DetectionBox],
                                   confidence_threshold: float) -> List[DetectionBox]:
        """Filter by confidence and merge overlapping detections"""

        # Step 1: Filter by confidence threshold
        filtered = [d for d in detections if d.confidence >= confidence_threshold]
        print(f"After confidence filtering (>= {confidence_threshold}): {len(filtered)} objects")

        if not filtered:
            return []

        # Step 2: Sort by confidence (highest first)
        sorted_detections = sorted(filtered, key=lambda x: x.confidence, reverse=True)

        # Step 3: Remove overlapping detections
        merged = []
        for detection in sorted_detections:
            overlaps = False
            for existing in merged:
                if self._calculate_iou(detection, existing) > 0.3:  # 30% overlap threshold
                    overlaps = True
                    break

            if not overlaps:
                merged.append(detection)

        print(f"After overlap removal: {len(merged)} final objects")
        return merged

    def _calculate_iou(self, box1: DetectionBox, box2: DetectionBox) -> float:
        """Calculate Intersection over Union (IoU) between two boxes"""
        # Calculate intersection
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
        self.shape_detector = GenericShapeDetector(detection_model)
        self.logger.debug(
            f"Initialized GenericShapeDetector with {detection_model}"
        )

    def detect_objects_and_shelves(
        self,
        image: Union[str, Path, Image.Image],
        confidence_threshold: float = 0.5
    ) -> Tuple[List[ShelfRegion], List[DetectionBox]]:
        """
        Step 1: Use GenericShapeDetector to find shapes and boundaries
        """

        self.logger.debug("Step 1: Detecting generic shapes and boundaries...")

        # Use the GenericShapeDetector
        detections = self.shape_detector.detect_all_shapes_and_boxes(
            image,
            confidence_threshold
        )

        # Convert to PIL image for shelf organization
        if isinstance(image, (str, Path)):
            pil_image = Image.open(image)
        else:
            pil_image = image

        # Organize detections into shelf regions based on Y coordinates
        shelf_regions = self._organize_into_shelves(detections, pil_image.size)

        self.logger.debug(f"Found {len(detections)} objects in {len(shelf_regions)} shelf regions")


        # Log shelf regions
        # print('Shelf Regions Detected: ', shelf_regions)
        # print('Detections : ', detections)
        return shelf_regions, detections

    def _organize_into_shelves(self, detections: List[DetectionBox], image_size: Tuple[int, int]) -> List[ShelfRegion]:
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
                        model=self.llm_model or "gpt-4o-mini",
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
      "position_on_shelf": "right"
    }}
  ]
}}

REFERENCE IMAGES show Epson printer models - compare visual design, control panels, ink systems.

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
            "backlit": "sign"
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
        confidence_threshold: float = 0.5
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

        return {
            "step1_detections": detections,
            "step1_shelf_regions": shelf_regions,
            "step2_identified_products": identified_products,
            "step3_compliance_results": compliance_results,
            "overall_compliance_score": total_score,
            "overall_compliant": overall_compliant,
            "analysis_timestamp": datetime.now()
        }
