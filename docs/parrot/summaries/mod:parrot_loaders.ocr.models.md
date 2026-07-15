---
type: Wiki Summary
title: parrot_loaders.ocr.models
id: mod:parrot_loaders.ocr.models
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: OCR data models for the ImageLoader feature.
relates_to:
- concept: class:parrot_loaders.ocr.models.LayoutLine
  rel: defines
- concept: class:parrot_loaders.ocr.models.LayoutResult
  rel: defines
- concept: class:parrot_loaders.ocr.models.OCRBlock
  rel: defines
---

# `parrot_loaders.ocr.models`

OCR data models for the ImageLoader feature.

These dataclasses are internal data transfer objects used across all OCR
backends and layout analyzers. They are intentionally plain dataclasses
(not Pydantic models) for maximum performance and minimal overhead.

## Classes

- **`OCRBlock`** — A single text region detected by OCR.
- **`LayoutLine`** — A horizontal line of text blocks at approximately the same y-coordinate.
- **`LayoutResult`** — Complete layout analysis result for a single image.
