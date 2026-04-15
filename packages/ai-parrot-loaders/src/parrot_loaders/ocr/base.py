"""
OCR Backend Protocol definition.

Defines the structural interface that all OCR backend implementations must
satisfy. Uses Python's Protocol (structural subtyping) so backends don't
need to explicitly inherit from this class.
"""
from typing import List, Protocol, runtime_checkable

from PIL import Image

from .models import OCRBlock


@runtime_checkable
class OCRBackend(Protocol):
    """Protocol for OCR backends.

    All OCR backends must implement this interface. The Protocol uses
    structural subtyping (duck typing) so backends do not need to explicitly
    inherit from this class.

    Example:
        class MyBackend:
            def extract(self, image: Image.Image, language: str = "en") -> List[OCRBlock]:
                ...
    """

    def extract(self, image: Image.Image, language: str = "en") -> List[OCRBlock]:
        """Run OCR on an image and return text blocks with bounding boxes.

        Args:
            image: PIL Image to process.
            language: ISO language code for OCR (e.g., "en", "fr", "de").
                Backend implementations handle language code mapping.

        Returns:
            List of OCRBlock objects, each containing extracted text,
            bounding box coordinates, and confidence score.
        """
        ...
