---
type: Wiki Entity
title: OCRBackend
id: class:parrot_loaders.ocr.base.OCRBackend
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Protocol for OCR backends.
---

# OCRBackend

Defined in [`parrot_loaders.ocr.base`](../summaries/mod:parrot_loaders.ocr.base.md).

```python
class OCRBackend(Protocol)
```

Protocol for OCR backends.

All OCR backends must implement this interface. The Protocol uses
structural subtyping (duck typing) so backends do not need to explicitly
inherit from this class.

Example:
    class MyBackend:
        def extract(self, image: Image.Image, language: str = "en") -> List[OCRBlock]:
            ...

## Methods

- `def extract(self, image: Image.Image, language: str='en') -> List[OCRBlock]` — Run OCR on an image and return text blocks with bounding boxes.
