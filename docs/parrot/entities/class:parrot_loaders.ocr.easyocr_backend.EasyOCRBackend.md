---
type: Wiki Entity
title: EasyOCRBackend
id: class:parrot_loaders.ocr.easyocr_backend.EasyOCRBackend
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: OCR backend using EasyOCR with optional GPU acceleration.
---

# EasyOCRBackend

Defined in [`parrot_loaders.ocr.easyocr_backend`](../summaries/mod:parrot_loaders.ocr.easyocr_backend.md).

```python
class EasyOCRBackend
```

OCR backend using EasyOCR with optional GPU acceleration.

EasyOCR natively supports CUDA.  GPU usage is auto-detected from
``torch.cuda.is_available()`` and can be overridden by setting
``EASYOCR_GPU=0`` in the environment before instantiation.

A single :class:`easyocr.Reader` instance is kept per backend object;
readers are expensive to initialise (model download on first use).

Attributes:
    _reader: The underlying ``easyocr.Reader`` instance.
    _language: The ISO 639-1 language code the reader was initialised with.

## Methods

- `def extract(self, image: Image.Image, language: str='en') -> List[OCRBlock]` — Extract text blocks from *image* using EasyOCR.
