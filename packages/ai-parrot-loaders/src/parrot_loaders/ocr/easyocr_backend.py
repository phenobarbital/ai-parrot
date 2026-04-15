"""
EasyOCR backend for parrot_loaders.

Wraps the ``easyocr`` library to provide GPU-friendly, multi-language OCR.
EasyOCR returns bounding boxes as four-corner polygons (similar to PaddleOCR),
which are converted to axis-aligned ``(x1, y1, x2, y2)`` rectangles.

Important: the file is named ``easyocr_backend.py`` (not ``easyocr.py``) to
avoid shadowing the ``easyocr`` package itself.
"""
import logging
from typing import List

from PIL import Image

from .models import OCRBlock


class EasyOCRBackend:
    """OCR backend using EasyOCR with optional GPU acceleration.

    EasyOCR natively supports CUDA.  GPU usage is auto-detected from
    ``torch.cuda.is_available()`` and can be overridden by setting
    ``EASYOCR_GPU=0`` in the environment before instantiation.

    A single :class:`easyocr.Reader` instance is kept per backend object;
    readers are expensive to initialise (model download on first use).

    Attributes:
        _reader: The underlying ``easyocr.Reader`` instance.
        _language: The ISO 639-1 language code the reader was initialised with.
    """

    def __init__(self, language: str = "en") -> None:
        """Initialise EasyOCRBackend.

        Args:
            language: ISO 639-1 language code (e.g. ``"en"``).  Passed to
                ``easyocr.Reader`` as a single-element list.

        Raises:
            ImportError: If ``easyocr`` is not installed.
        """
        try:
            import easyocr  # noqa: F401 — guard only
        except ImportError as exc:
            raise ImportError(
                "easyocr is not installed. "
                "Install with: pip install easyocr"
            ) from exc

        try:
            import torch

            gpu = torch.cuda.is_available()
        except ImportError:
            gpu = False

        self.logger = logging.getLogger(__name__)
        self.logger.debug(
            "Initialising EasyOCR reader (language=%s, gpu=%s)", language, gpu
        )

        import easyocr

        self._reader = easyocr.Reader([language], gpu=gpu)
        self._language = language

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract(self, image: Image.Image, language: str = "en") -> List[OCRBlock]:
        """Extract text blocks from *image* using EasyOCR.

        Args:
            image: A PIL/Pillow image to analyse.
            language: ISO 639-1 language code.  Note that the ``Reader``
                was initialised with the language passed to ``__init__``;
                this parameter is accepted for API compatibility but only
                used if it matches the reader's language.

        Returns:
            A list of :class:`OCRBlock` instances, one per EasyOCR detection,
            in the order returned by the reader.
        """
        import numpy as np

        img_array = np.array(image)
        self.logger.debug("Running EasyOCR on image shape=%s", img_array.shape)
        results = self._reader.readtext(img_array)

        blocks: List[OCRBlock] = []
        for bbox_points, text, confidence in results:
            if not text.strip():
                continue
            # bbox_points is a list of four [x, y] corner points
            xs = [pt[0] for pt in bbox_points]
            ys = [pt[1] for pt in bbox_points]
            x1, y1 = int(min(xs)), int(min(ys))
            x2, y2 = int(max(xs)), int(max(ys))

            blocks.append(
                OCRBlock(
                    text=text.strip(),
                    bbox=(x1, y1, x2, y2),
                    confidence=float(confidence),
                    font_size_estimate=float(y2 - y1),
                )
            )

        self.logger.debug("EasyOCR extracted %d blocks", len(blocks))
        return blocks
