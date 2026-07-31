---
type: Wiki Entity
title: TesseractBackend
id: class:parrot_loaders.ocr.tesseract.TesseractBackend
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: OCR backend using Tesseract via pytesseract.
---

# TesseractBackend

Defined in [`parrot_loaders.ocr.tesseract`](../summaries/mod:parrot_loaders.ocr.tesseract.md).

```python
class TesseractBackend
```

OCR backend using Tesseract via pytesseract.

Groups per-word Tesseract output into paragraph-level :class:`OCRBlock`
objects.  Each block covers a ``(block_num, par_num)`` group, which
corresponds to a paragraph boundary as detected by Tesseract's page
segmentation engine.

Attributes:
    LANGUAGE_MAP: Mapping from ISO 639-1 two-letter codes to the Tesseract
        language data file names (e.g. ``"en"`` -> ``"eng"``).

## Methods

- `def extract(self, image: Image.Image, language: str='en') -> List[OCRBlock]` — Extract text blocks from *image* using Tesseract.
