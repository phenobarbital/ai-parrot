"""
Tesseract OCR backend for parrot_loaders.

Uses pytesseract to extract text with bounding boxes from images.
Words are grouped into paragraph-level blocks for structured output.
"""
import logging
import statistics
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

        # Detect column boundaries by analysing x-gaps between words on
        # each line.  Words separated by a large horizontal gap belong to
        # different table cells / columns.
        line_groups: Dict[Tuple[int, int, int], List[int]] = {}
        for i, text in enumerate(data["text"]):
            if not text.strip():
                continue
            if data["conf"][i] == -1:
                continue
            key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
            line_groups.setdefault(key, []).append(i)

        # Compute a gap threshold: the median word gap across all lines.
        all_gaps: List[float] = []
        for indices in line_groups.values():
            sorted_idx = sorted(indices, key=lambda k: data["left"][k])
            for a, b in zip(sorted_idx, sorted_idx[1:]):
                gap = data["left"][b] - (data["left"][a] + data["width"][a])
                if gap > 0:
                    all_gaps.append(gap)

        if all_gaps:
            median_gap = statistics.median(all_gaps)
            # A gap larger than 3× the median separates columns/cells.
            col_gap_threshold = max(median_gap * 3.0, 30.0)
        else:
            col_gap_threshold = 30.0

        blocks: List[OCRBlock] = []
        for indices in line_groups.values():
            sorted_idx = sorted(indices, key=lambda k: data["left"][k])
            # Split this line into cell groups at large gaps
            cell_groups: List[List[int]] = [[sorted_idx[0]]]
            for prev, cur in zip(sorted_idx, sorted_idx[1:]):
                gap = data["left"][cur] - (data["left"][prev] + data["width"][prev])
                if gap >= col_gap_threshold:
                    cell_groups.append([cur])
                else:
                    cell_groups[-1].append(cur)

            for cell_idx in cell_groups:
                texts = [
                    data["text"][i].strip()
                    for i in cell_idx
                    if data["text"][i].strip()
                ]
                if not texts:
                    continue

                confs = [data["conf"][i] / 100.0 for i in cell_idx]
                lefts = [data["left"][i] for i in cell_idx]
                tops = [data["top"][i] for i in cell_idx]
                rights = [data["left"][i] + data["width"][i] for i in cell_idx]
                bottoms = [data["top"][i] + data["height"][i] for i in cell_idx]

                x1, y1 = min(lefts), min(tops)
                x2, y2 = max(rights), max(bottoms)
                avg_conf = sum(confs) / len(confs)

                # Use median word height as font size estimate (more
                # accurate than cell bbox height for table layouts).
                word_heights = [data["height"][i] for i in cell_idx]
                font_est = float(
                    statistics.median(word_heights) if word_heights else (y2 - y1)
                )

                blocks.append(
                    OCRBlock(
                        text=" ".join(texts),
                        bbox=(x1, y1, x2, y2),
                        confidence=avg_conf,
                        font_size_estimate=font_est,
                    )
                )

        # Sort roughly top-to-bottom, left-to-right
        blocks.sort(key=lambda b: (b.bbox[1], b.bbox[0]))
        self.logger.debug("Tesseract extracted %d blocks", len(blocks))
        return blocks
