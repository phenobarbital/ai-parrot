---
type: Wiki Summary
title: parrot_loaders.ocr
id: mod:parrot_loaders.ocr
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: OCR subpackage for parrot_loaders.
relates_to:
- concept: func:parrot_loaders.ocr.get_ocr_backend
  rel: defines
- concept: mod:parrot_loaders
  rel: references
---

# `parrot_loaders.ocr`

OCR subpackage for parrot_loaders.

Provides OCR backend abstraction, data models, and a factory function for
selecting the best available OCR backend at runtime.

Public API:
    OCRBlock: Dataclass for a single text region.
    LayoutLine: Dataclass for a horizontal line of text.
    LayoutResult: Dataclass for complete layout analysis.
    OCRBackend: Protocol that all backends must satisfy.
    get_ocr_backend: Factory to select/instantiate an OCR backend.

Example:
    from parrot_loaders.ocr import OCRBlock, get_ocr_backend

    backend = get_ocr_backend("auto")
    blocks = backend.extract(image, language="en")

## Functions

- `def get_ocr_backend(name: str, language: str='en') -> OCRBackend` — Factory function to instantiate an OCR backend by name.
