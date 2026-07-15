---
type: Wiki Summary
title: parrot_loaders.ocr.easyocr_backend
id: mod:parrot_loaders.ocr.easyocr_backend
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: EasyOCR backend for parrot_loaders.
relates_to:
- concept: class:parrot_loaders.ocr.easyocr_backend.EasyOCRBackend
  rel: defines
- concept: mod:parrot_loaders.ocr.models
  rel: references
---

# `parrot_loaders.ocr.easyocr_backend`

EasyOCR backend for parrot_loaders.

Wraps the ``easyocr`` library to provide GPU-friendly, multi-language OCR.
EasyOCR returns bounding boxes as four-corner polygons (similar to PaddleOCR),
which are converted to axis-aligned ``(x1, y1, x2, y2)`` rectangles.

Important: the file is named ``easyocr_backend.py`` (not ``easyocr.py``) to
avoid shadowing the ``easyocr`` package itself.

## Classes

- **`EasyOCRBackend`** — OCR backend using EasyOCR with optional GPU acceleration.
