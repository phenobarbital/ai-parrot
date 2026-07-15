---
type: Wiki Entity
title: OCRBlock
id: class:parrot_loaders.ocr.models.OCRBlock
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: A single text region detected by OCR.
---

# OCRBlock

Defined in [`parrot_loaders.ocr.models`](../summaries/mod:parrot_loaders.ocr.models.md).

```python
class OCRBlock
```

A single text region detected by OCR.

Attributes:
    text: The extracted text content.
    bbox: Bounding box as (x1, y1, x2, y2) pixel coordinates (top-left to bottom-right).
    confidence: OCR confidence score, ranging from 0.0 to 1.0.
    font_size_estimate: Estimated relative font size (in pixels), used for
        header detection. Derived from bbox height. None if not available.
