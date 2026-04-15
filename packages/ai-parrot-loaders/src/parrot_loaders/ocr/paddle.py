"""
PaddleOCR Backend for ImageLoader.

Wraps the PaddleOCR library behind the OCRBackend protocol.
PaddleOCR provides high-quality text detection + recognition with angle
classification. It is the primary/default OCR backend.

This module is an optional dependency. Import errors are raised with clear
instructions only when the backend is actually instantiated.
"""
import logging
from typing import List

from PIL import Image

from .models import OCRBlock


class PaddleOCRBackend:
    """OCR backend using PaddleOCR.

    Provides high-quality text extraction with bounding boxes. Supports
    angle classification for rotated text and multiple languages.

    The ``paddleocr`` and ``paddlepaddle`` packages must be installed:
        pip install paddleocr paddlepaddle

    Args:
        language: PaddleOCR language code (e.g., "en", "ch", "fr").
            The mapping from ISO codes to PaddleOCR codes is handled internally.

    Raises:
        ImportError: If ``paddleocr`` is not installed.

    Example:
        backend = PaddleOCRBackend(language="en")
        blocks = backend.extract(pil_image)
    """

    # Mapping from common ISO language codes to PaddleOCR language codes.
    LANGUAGE_MAP = {
        "en": "en",
        "english": "en",
        "zh": "ch",
        "chinese": "ch",
        "fr": "fr",
        "french": "fr",
        "de": "german",
        "german": "german",
        "es": "es",
        "spanish": "es",
        "pt": "pt",
        "portuguese": "pt",
        "ja": "japan",
        "japanese": "japan",
        "ko": "korean",
        "korean": "korean",
        "ar": "ar",
        "arabic": "ar",
    }

    def __init__(self, language: str = "en") -> None:
        """Initialize the PaddleOCR backend.

        Args:
            language: Language code for OCR (ISO or PaddleOCR format).

        Raises:
            ImportError: If paddleocr package is not available.
        """
        try:
            from paddleocr import PaddleOCR
        except ImportError as exc:
            raise ImportError(
                "paddleocr is not installed. Install it with: "
                "pip install paddleocr paddlepaddle"
            ) from exc

        # Suppress PaddleOCR's verbose logging.
        logging.getLogger("ppocr").setLevel(logging.WARNING)
        logging.getLogger("ppdet").setLevel(logging.WARNING)
        logging.getLogger("paddle").setLevel(logging.WARNING)

        paddle_lang = self.LANGUAGE_MAP.get(language.lower(), language)
        self._ocr = PaddleOCR(
            lang=paddle_lang,
            use_angle_cls=True,
            show_log=False,
        )
        self._language = language
        self.logger = logging.getLogger(__name__)

    def extract(self, image: Image.Image, language: str = "en") -> List[OCRBlock]:
        """Run PaddleOCR on an image and return text blocks.

        Args:
            image: PIL Image to process.
            language: Language override for this call. Defaults to the
                language specified at construction time.

        Returns:
            List of OCRBlock objects with text, bounding boxes, and
            confidence scores. Blocks with very low confidence (< 0.1)
            are filtered out as noise.
        """
        import numpy as np

        img_array = np.array(image)
        try:
            results = self._ocr.ocr(img_array, cls=True)
        except Exception as exc:
            self.logger.warning("PaddleOCR failed: %s", exc)
            return []

        blocks: List[OCRBlock] = []

        # results is a list of pages; we process the first page only.
        if not results:
            return blocks

        page_results = results[0]
        if not page_results:
            return blocks

        for item in page_results:
            # Each item: [bbox_polygon, (text, confidence)]
            if not item or len(item) < 2:
                continue

            bbox_polygon, (text, confidence) = item

            if not text or not text.strip():
                continue

            if confidence < 0.1:
                continue

            # bbox_polygon is 4 corner points: [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
            # Convert to axis-aligned (x1, y1, x2, y2) bounding box.
            try:
                xs = [pt[0] for pt in bbox_polygon]
                ys = [pt[1] for pt in bbox_polygon]
                x1, y1 = int(min(xs)), int(min(ys))
                x2, y2 = int(max(xs)), int(max(ys))
            except (TypeError, IndexError, ValueError) as exc:
                self.logger.debug("Failed to parse bbox: %s — %s", bbox_polygon, exc)
                continue

            # Font size estimate = bbox height in pixels.
            font_size_estimate = float(y2 - y1)

            blocks.append(
                OCRBlock(
                    text=text.strip(),
                    bbox=(x1, y1, x2, y2),
                    confidence=float(confidence),
                    font_size_estimate=font_size_estimate,
                )
            )

        return blocks
