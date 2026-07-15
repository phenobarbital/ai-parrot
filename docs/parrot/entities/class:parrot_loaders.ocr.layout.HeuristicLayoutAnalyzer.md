---
type: Wiki Entity
title: HeuristicLayoutAnalyzer
id: class:parrot_loaders.ocr.layout.HeuristicLayoutAnalyzer
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Geometry-based layout analyzer that requires no ML model.
---

# HeuristicLayoutAnalyzer

Defined in [`parrot_loaders.ocr.layout`](../summaries/mod:parrot_loaders.ocr.layout.md).

```python
class HeuristicLayoutAnalyzer
```

Geometry-based layout analyzer that requires no ML model.

Args:
    line_threshold: Maximum vertical pixel distance between the
        y-centres of two blocks for them to be placed on the same line.
    table_min_rows: Minimum number of consecutive lines needed to call a
        region a table.
    column_align_tolerance: Maximum horizontal pixel difference between
        the x1 positions of two blocks on different lines for them to be
        considered column-aligned.
    header_font_ratio: Ratio above the median font size that causes a
        block to be classified as a header (default 1.5×).

## Methods

- `def analyze(self, blocks: List[OCRBlock]) -> LayoutResult` — Analyse *blocks* and return a structured :class:`LayoutResult`.
