---
type: Wiki Entity
title: LayoutLine
id: class:parrot_loaders.ocr.models.LayoutLine
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: A horizontal line of text blocks at approximately the same y-coordinate.
---

# LayoutLine

Defined in [`parrot_loaders.ocr.models`](../summaries/mod:parrot_loaders.ocr.models.md).

```python
class LayoutLine
```

A horizontal line of text blocks at approximately the same y-coordinate.

Attributes:
    blocks: OCR blocks belonging to this line, sorted left-to-right.
    y_center: The vertical center position of this line (in pixels).
    is_header: True if this line was detected as a header (large text or ALL CAPS).
