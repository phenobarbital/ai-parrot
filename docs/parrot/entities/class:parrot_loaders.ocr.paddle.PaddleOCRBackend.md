---
type: Wiki Entity
title: PaddleOCRBackend
id: class:parrot_loaders.ocr.paddle.PaddleOCRBackend
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: OCR backend using PaddleOCR.
---

# PaddleOCRBackend

Defined in [`parrot_loaders.ocr.paddle`](../summaries/mod:parrot_loaders.ocr.paddle.md).

```python
class PaddleOCRBackend
```

OCR backend using PaddleOCR.

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

## Methods

- `def extract(self, image: Image.Image, language: str='en') -> List[OCRBlock]` — Run PaddleOCR on an image and return text blocks.
