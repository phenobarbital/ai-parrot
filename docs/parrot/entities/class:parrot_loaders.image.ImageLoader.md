---
type: Wiki Entity
title: ImageLoader
id: class:parrot_loaders.image.ImageLoader
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: OCR-based image loader with layout-aware text extraction.
relates_to:
- concept: class:parrot.loaders.abstract.AbstractLoader
  rel: extends
---

# ImageLoader

Defined in [`parrot_loaders.image`](../summaries/mod:parrot_loaders.image.md).

```python
class ImageLoader(AbstractLoader)
```

OCR-based image loader with layout-aware text extraction.

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
