---
type: Wiki Summary
title: parrot_loaders.ocr.tesseract
id: mod:parrot_loaders.ocr.tesseract
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Tesseract OCR backend for parrot_loaders.
relates_to:
- concept: class:parrot_loaders.ocr.tesseract.TesseractBackend
  rel: defines
- concept: mod:parrot_loaders.ocr.models
  rel: references
---

# `parrot_loaders.ocr.tesseract`

Tesseract OCR backend for parrot_loaders.

Uses pytesseract to extract text with bounding boxes from images.
Words are grouped into paragraph-level blocks for structured output.

## Classes

- **`TesseractBackend`** — OCR backend using Tesseract via pytesseract.
