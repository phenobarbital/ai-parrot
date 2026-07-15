---
type: Wiki Entity
title: LayoutResult
id: class:parrot_loaders.ocr.models.LayoutResult
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Complete layout analysis result for a single image.
---

# LayoutResult

Defined in [`parrot_loaders.ocr.models`](../summaries/mod:parrot_loaders.ocr.models.md).

```python
class LayoutResult
```

Complete layout analysis result for a single image.

Attributes:
    lines: All detected text lines, sorted top-to-bottom.
    tables: Detected tables, each represented as a list of rows,
        where each row is a list of cell strings.
    table_line_ranges: For each table, the (start, end) line indices
        (inclusive start, exclusive end) mapping it back to ``lines``.
    columns_detected: Number of visual columns detected (1 = single column).
    avg_confidence: Average OCR confidence across all blocks.
