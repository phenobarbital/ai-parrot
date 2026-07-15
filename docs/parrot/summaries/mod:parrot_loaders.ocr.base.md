---
type: Wiki Summary
title: parrot_loaders.ocr.base
id: mod:parrot_loaders.ocr.base
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: OCR Backend Protocol definition.
relates_to:
- concept: class:parrot_loaders.ocr.base.OCRBackend
  rel: defines
- concept: mod:parrot_loaders.ocr.models
  rel: references
---

# `parrot_loaders.ocr.base`

OCR Backend Protocol definition.

Defines the structural interface that all OCR backend implementations must
satisfy. Uses Python's Protocol (structural subtyping) so backends don't
need to explicitly inherit from this class.

## Classes

- **`OCRBackend(Protocol)`** — Protocol for OCR backends.
