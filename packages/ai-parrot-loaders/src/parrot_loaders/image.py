"""
ImageLoader: OCR-based image loader with layout-aware text extraction.

Orchestrates the full pipeline: open image → OCR → confidence filter →
layout analysis → markdown → :class:`Document`.

Uses :func:`asyncio.to_thread` for all blocking OCR / model inference calls
so it integrates safely with the async-first AI-Parrot framework.
"""
import asyncio
import logging
from pathlib import Path, PurePath
from typing import Callable, List, Optional, Union

from parrot.loaders.abstract import AbstractLoader
from parrot.stores.models import Document
from PIL import Image

from parrot_loaders.ocr import get_ocr_backend
from parrot_loaders.ocr.layout import HeuristicLayoutAnalyzer, render_markdown
from parrot_loaders.ocr.models import OCRBlock


class ImageLoader(AbstractLoader):
    """OCR-based image loader with layout-aware text extraction.

    Extracts text from images using an OCR backend (PaddleOCR, Tesseract, or
    EasyOCR) and structures the output with a layout analyser.  The result
    is rendered as Markdown and wrapped in a :class:`Document`.

    Args:
        source: Path or list of paths to image files.
        ocr_backend: Backend identifier — ``"auto"``, ``"paddleocr"``,
            ``"tesseract"``, or ``"easyocr"``.
        layout_model: Layout analyser to use.  ``None`` (default) selects the
            heuristic analyser; ``"layoutlmv3"`` selects the transformer model.
        language: ISO 639-1 language code for OCR.
        detect_tables: Whether table detection is enabled (informational; the
            heuristic analyser always detects tables when possible).
        detect_headers: Whether header detection is enabled (informational).
        min_confidence: Minimum OCR confidence threshold (0–1).  Blocks below
            this value are discarded before layout analysis.
        dpi: Target DPI for image loading (informational; Pillow auto-detects).
        **kwargs: Additional keyword arguments forwarded to :class:`AbstractLoader`.

    Attributes:
        extensions: Supported file extensions.
    """

    extensions: List[str] = [
        ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff", ".tif"
    ]

    def __init__(
        self,
        source: Optional[Union[str, Path, List[Union[str, Path]]]] = None,
        *,
        ocr_backend: str = "auto",
        layout_model: Optional[str] = None,
        language: str = "en",
        detect_tables: bool = True,
        detect_headers: bool = True,
        min_confidence: float = 0.5,
        dpi: int = 300,
        tokenizer: Union[str, Callable] = None,
        text_splitter: Union[str, Callable] = None,
        **kwargs,
    ) -> None:
        # Allow callers (e.g. ParrotLoader) to override source_type; fall back to "image_ocr".
        kwargs.setdefault("source_type", "image_ocr")
        super().__init__(
            source,
            tokenizer=tokenizer,
            text_splitter=text_splitter,
            **kwargs,
        )

        self.logger = logging.getLogger(__name__)

        # Suppress verbose DEBUG output from image/OCR libraries
        logging.getLogger("PIL").setLevel(logging.INFO)
        logging.getLogger("pytesseract").setLevel(logging.INFO)

        self._ocr_backend_name = ocr_backend
        self._layout_model = layout_model
        self._language = language
        self._detect_tables = detect_tables
        self._detect_headers = detect_headers
        self._min_confidence = min_confidence
        self._dpi = dpi

        # Instantiate OCR backend (lazy import handled inside get_ocr_backend)
        self._backend = get_ocr_backend(ocr_backend, language=language)

        # Instantiate layout analyser
        if layout_model == "layoutlmv3":
            from parrot_loaders.ocr.layoutlm import LayoutLMv3Analyzer

            self._analyzer = LayoutLMv3Analyzer()
        else:
            self._analyzer = HeuristicLayoutAnalyzer()

    # ------------------------------------------------------------------
    # AbstractLoader interface
    # ------------------------------------------------------------------

    async def _load(
        self, source: Union[str, PurePath], **kwargs
    ) -> List[Document]:
        """Load an image file and return OCR-extracted :class:`Document` objects.

        Args:
            source: Path to a single image file.
            **kwargs: Unused; accepted for API compatibility.

        Returns:
            A list containing a single :class:`Document` with the
            layout-aware Markdown as ``page_content`` and rich metadata.
        """
        path = Path(str(source))
        self.logger.info("ImageLoader processing: %s", path.name)

        # Open image with Pillow
        try:
            image = Image.open(str(path)).convert("RGB")
        except Exception as exc:
            self.logger.error("Cannot open image %s: %s", path, exc)
            return []

        # Run OCR in a thread pool (CPU-bound / blocking)
        try:
            blocks: List[OCRBlock] = await asyncio.to_thread(
                self._backend.extract, image, self._language
            )
        except Exception as exc:
            self.logger.error("OCR failed on %s: %s", path.name, exc)
            return []

        # Filter low-confidence blocks
        blocks = [b for b in blocks if b.confidence >= self._min_confidence]
        self.logger.debug(
            "%d blocks retained after confidence filter (min=%.2f)",
            len(blocks),
            self._min_confidence,
        )

        # Layout analysis
        try:
            if self._layout_model == "layoutlmv3":
                layout = await asyncio.to_thread(
                    self._analyzer.analyze, blocks, image
                )
            else:
                layout = self._analyzer.analyze(blocks)
        except Exception as exc:
            self.logger.error("Layout analysis failed on %s: %s", path.name, exc)
            return []

        # Render Markdown
        md_text = render_markdown(layout)

        # Build metadata — language is canonical (goes to document_meta);
        # all other fields are non-canonical extras at top level.
        meta = self.create_metadata(
            path=path,
            doctype=getattr(self, "doctype", "image"),
            source_type=getattr(self, "source_type", "image_ocr"),
            language=self._language,
            ocr_backend=self._backend.__class__.__name__,
            layout_model=self._layout_model or "heuristic",
            avg_confidence=layout.avg_confidence,
            image_dimensions=(image.width, image.height),
            table_count=len(layout.tables),
        )

        return [self.create_document(content=md_text, path=path, metadata=meta)]
