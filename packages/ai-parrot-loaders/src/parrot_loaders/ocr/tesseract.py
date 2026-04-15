"""
Tesseract OCR backend for parrot_loaders.

Uses pytesseract to extract text with bounding boxes from images.
Words are grouped into paragraph-level blocks for structured output.
"""
import logging
from typing import Dict, List, Tuple

from PIL import Image

from .models import OCRBlock


class TesseractBackend:
    """OCR backend using Tesseract via pytesseract.

    Groups per-word Tesseract output into paragraph-level :class:`OCRBlock`
    objects.  Each block covers a ``(block_num, par_num)`` group, which
    corresponds to a paragraph boundary as detected by Tesseract's page
    segmentation engine.

    Attributes:
        LANGUAGE_MAP: Mapping from ISO 639-1 two-letter codes to the Tesseract
            language data file names (e.g. ``"en"`` -> ``"eng"``).
    """

    LANGUAGE_MAP: Dict[str, str] = {
        "en": "eng",
        "fr": "fra",
        "de": "deu",
        "es": "spa",
        "pt": "por",
        "zh": "chi_sim",
        "ja": "jpn",
        "ko": "kor",
        "it": "ita",
        "nl": "nld",
        "ru": "rus",
        "ar": "ara",
    }

    def __init__(self, language: str = "en") -> None:
        """Initialise TesseractBackend.

        Args:
            language: Default ISO 639-1 language code (e.g. ``"en"``).
                Mapped to a Tesseract language data file name at extract time.

        Raises:
            ImportError: If the ``tesseract`` binary is not found or
                ``pytesseract`` is not installed.
        """
        try:
            import pytesseract

            pytesseract.get_tesseract_version()
        except Exception as exc:
            raise ImportError(
                "tesseract binary not found or pytesseract not installed. "
                "Install with: apt install tesseract-ocr && pip install pytesseract"
            ) from exc

        self._lang = language
        self.logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract(self, image: Image.Image, language: str = "en") -> List[OCRBlock]:
        """Extract text blocks from *image* using Tesseract.

        Args:
            image: A PIL/Pillow image to analyse.
            language: ISO 639-1 language code used for Tesseract.  Defaults
                to ``"en"`` (mapped to ``"eng"``).

        Returns:
            A list of :class:`OCRBlock` objects, one per paragraph group,
            sorted in approximate reading order (top-to-bottom, then
            left-to-right).
        """
        import pytesseract
        from pytesseract import Output

        lang = self.LANGUAGE_MAP.get(language.lower(), language)
        self.logger.debug("Running Tesseract OCR (lang=%s)", lang)

        data = pytesseract.image_to_data(image, lang=lang, output_type=Output.DICT)

        # Group word-level entries by (block_num, par_num).
        groups: Dict[Tuple[int, int], List[int]] = {}
        for i, text in enumerate(data["text"]):
            if not text.strip():
                continue
            # conf == -1 for layout-only entries (not actual text detections)
            if data["conf"][i] == -1:
                continue
            key = (data["block_num"][i], data["par_num"][i])
            groups.setdefault(key, []).append(i)

        blocks: List[OCRBlock] = []
        for indices in groups.values():
            texts = [data["text"][i].strip() for i in indices if data["text"][i].strip()]
            if not texts:
                continue

            confs = [data["conf"][i] / 100.0 for i in indices]
            lefts = [data["left"][i] for i in indices]
            tops = [data["top"][i] for i in indices]
            rights = [data["left"][i] + data["width"][i] for i in indices]
            bottoms = [data["top"][i] + data["height"][i] for i in indices]

            x1, y1 = min(lefts), min(tops)
            x2, y2 = max(rights), max(bottoms)
            avg_conf = sum(confs) / len(confs)

            blocks.append(
                OCRBlock(
                    text=" ".join(texts),
                    bbox=(x1, y1, x2, y2),
                    confidence=avg_conf,
                    font_size_estimate=float(y2 - y1),
                )
            )

        # Sort roughly top-to-bottom, left-to-right
        blocks.sort(key=lambda b: (b.bbox[1], b.bbox[0]))
        self.logger.debug("Tesseract extracted %d blocks", len(blocks))
        return blocks
