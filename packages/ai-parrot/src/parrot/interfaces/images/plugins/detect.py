from pathlib import Path
from typing import Union
from pydantic import BaseModel
from PIL import Image
from ....clients.google import GoogleGenAIClient
from .classifybase import ClassifyBase


def is_model_class(cls) -> bool:
    return isinstance(cls, type) and issubclass(cls, BaseModel)


DEFAULT_PROMPT = """
Analyze this retail image to identify Epson and competitor products.

TARGET BRANDS: Epson, HP, Canon, Brother, Lexmark, Xerox, Ricoh, Kyocera, Sharp

TASK:
1. Count ALL visible products (boxed and unboxed)
2. Identify each product's brand, type, and model (if visible)
3. Provide approximate location as normalized coordinates (0.0 to 1.0)

IMPORTANT:
- Focus on printers, scanners, ink cartridges, toner, and related products
- Include products that are partially visible
- Use confidence scores (0.0 to 1.0) for each detection
- Provide bounding boxes as [x1, y1, x2, y2] where (0,0) is top-left, (1,1) is bottom-right

Respond with a complete JSON object following the specified schema.
"""  # noqa


class DetectionPlugin(ClassifyBase):
    """
    DetectionPlugin is a plugin for performing image detection.
    Uses Gemini 2.5 multimodal model for image detection tasks.
    """
    column_name: str = "detections"
    section_name: str = "detections"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.section_name = kwargs.get("section_name", self.section_name)

    def _extract_detection_results(self, result) -> dict:
        """
        Extract detection results from AIMessage object and return as dictionary.

        Args:
            result: AIMessage object with structured_output containing ObjectDetectionResult

        Returns:
            dict: Dictionary with 'analysis' and 'detections' keys
        """

        # Check if we have structured output
        print(hasattr(result, 'structured_output'), hasattr(result, 'output'))
        if hasattr(result, 'output') and result.output:
            detection_result = result.output

            # Convert BoundingBox objects to dictionaries
            detections = []
            for bbox in detection_result.detections:
                detection_dict = {
                    "object_id": bbox.object_id,
                    "brand": bbox.brand,
                    "model": bbox.model,
                    "product_type": bbox.product_type,
                    "description": bbox.description,
                    "confidence": bbox.confidence,
                    "bbox": bbox.bbox  # Already a list [x1, y1, x2, y2]
                }
                detections.append(detection_dict)

            # Create the final result dictionary
            detected = False
            if detection_result.total_count > 0:
                detected = True
            r = {
                "analysis": detection_result.analysis,
                "total_count": detection_result.total_count,  # Include this for completeness
                "detected": detected,
                "detections": detections
            }

            return r

        else:
            # Fallback if no structured output
            return {
                "analysis": "No structured output available",
                "total_count": 0,
                "detections": []
            }

    async def analyze(self, image: Union[Path, Image.Image], **kwargs) -> dict:
        """
        Analyze the image and classify it into a retail category.

        :param image: Image Bytes opened with PIL Image.open
        :return: A dictionary containing the classification result.
        """
        row = kwargs.get("row", None)
        detections_column = kwargs.get(self.column_name, None)
        if detections_column is None:
            detections_column = {}
        else:
            # Make a copy to avoid modifying original
            detections_column = detections_column.copy()
        if self.section_name in detections_column:
            del detections_column[self.section_name]

        if getattr(self, 'filter_column', None) and getattr(self, 'filter_by', None):
            filter_value = row[self.filter_column] if self.filter_column in row else None
            # Check if filter value is valid and not NA
            if not self._is_valid_filter_value(filter_value):
                self.logger.info(
                    f"Skipping detection for row {row.name} - filter column '{self.filter_column}' has NA/invalid value"
                )
                return detections_column
            # Now safe to do the comparison
            if filter_value not in self.filter_by:
                self.logger.info(
                    f"Skipping detection for row {row.name} with category {filter_value}"
                )
                return detections_column
        # Open the image
        async with GoogleGenAIClient() as client:
            _result = await client.ask_to_image(
                image=image,
                reference_images=[self.reference_image] if self.reference_image else None,
                prompt=self.prompt,
                structured_output=self._detection_model,
                model=self._model_name
            )
            if _result:
                detections = self._extract_detection_results(_result)
                self.logger.info(f"Successfully detected {detections['total_count']} products")
                self.logger.debug(
                    f"Analysis: {detections['analysis'][:100]}..."
                )
                detections_column[self.section_name] = detections
                row[self.column_name] = detections_column
                # Return the updated detections column
                return detections_column
            else:
                self.logger.error(
                    "The model did not return a valid Detection result."
                )
                return detections_column
