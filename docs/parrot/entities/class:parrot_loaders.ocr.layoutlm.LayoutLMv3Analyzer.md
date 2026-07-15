---
type: Wiki Entity
title: LayoutLMv3Analyzer
id: class:parrot_loaders.ocr.layoutlm.LayoutLMv3Analyzer
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Semantic layout analyzer using LayoutLMv3 token classification.
---

# LayoutLMv3Analyzer

Defined in [`parrot_loaders.ocr.layoutlm`](../summaries/mod:parrot_loaders.ocr.layoutlm.md).

```python
class LayoutLMv3Analyzer
```

Semantic layout analyzer using LayoutLMv3 token classification.

Loads ``microsoft/layoutlmv3-base`` with ``apply_ocr=False`` (we supply
our own OCR results) and classifies each word token into one of the
semantic label categories defined in :attr:`LABEL_MAP`.

All model-related imports are deferred to ``__init__`` so the class is
importable even when ``transformers`` / ``torch`` are not installed.

Attributes:
    LABEL_MAP: Mapping from integer prediction index to semantic label
        string.

## Methods

- `def analyze(self, blocks: List[OCRBlock], image: Image.Image) -> LayoutResult` — Classify OCR blocks into semantic regions using LayoutLMv3.
