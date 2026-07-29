---
type: Wiki Summary
title: parrot_loaders.image
id: mod:parrot_loaders.image
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'ImageLoader: OCR-based image loader with layout-aware text extraction.'
relates_to:
- concept: class:parrot_loaders.image.ImageLoader
  rel: defines
- concept: mod:parrot.loaders.abstract
  rel: references
- concept: mod:parrot.stores.models
  rel: references
- concept: mod:parrot_loaders.ocr
  rel: references
- concept: mod:parrot_loaders.ocr.layout
  rel: references
- concept: mod:parrot_loaders.ocr.layoutlm
  rel: references
- concept: mod:parrot_loaders.ocr.models
  rel: references
---

# `parrot_loaders.image`

ImageLoader: OCR-based image loader with layout-aware text extraction.

Orchestrates the full pipeline: open image → OCR → confidence filter →
layout analysis → markdown → :class:`Document`.

Uses :func:`asyncio.to_thread` for all blocking OCR / model inference calls
so it integrates safely with the async-first AI-Parrot framework.

## Classes

- **`ImageLoader(AbstractLoader)`** — OCR-based image loader with layout-aware text extraction.
