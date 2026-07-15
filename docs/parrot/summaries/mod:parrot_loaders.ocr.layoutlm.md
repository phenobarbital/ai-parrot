---
type: Wiki Summary
title: parrot_loaders.ocr.layoutlm
id: mod:parrot_loaders.ocr.layoutlm
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: LayoutLMv3 semantic layout analyzer for parrot_loaders.
relates_to:
- concept: class:parrot_loaders.ocr.layoutlm.LayoutLMv3Analyzer
  rel: defines
- concept: mod:parrot_loaders.ocr.models
  rel: references
---

# `parrot_loaders.ocr.layoutlm`

LayoutLMv3 semantic layout analyzer for parrot_loaders.

Uses Microsoft's ``layoutlmv3-base`` model to classify OCR tokens into
semantic categories: title, paragraph, table, list, figure, and caption.

All heavy dependencies (``transformers``, ``torch``) are guarded with
try/except both at module level and inside ``__init__``.  If either
dependency is absent the class can still be imported; only instantiation
will raise ``ImportError``.

## Classes

- **`LayoutLMv3Analyzer`** — Semantic layout analyzer using LayoutLMv3 token classification.
