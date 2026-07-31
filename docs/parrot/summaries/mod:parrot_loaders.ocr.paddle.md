---
type: Wiki Summary
title: parrot_loaders.ocr.paddle
id: mod:parrot_loaders.ocr.paddle
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: PaddleOCR Backend for ImageLoader.
relates_to:
- concept: class:parrot_loaders.ocr.paddle.PaddleOCRBackend
  rel: defines
- concept: mod:parrot_loaders.ocr.models
  rel: references
---

# `parrot_loaders.ocr.paddle`

PaddleOCR Backend for ImageLoader.

Wraps the PaddleOCR library behind the OCRBackend protocol.
PaddleOCR provides high-quality text detection + recognition with angle
classification. It is the primary/default OCR backend.

This module is an optional dependency. Import errors are raised with clear
instructions only when the backend is actually instantiated.

## Classes

- **`PaddleOCRBackend`** — OCR backend using PaddleOCR.
