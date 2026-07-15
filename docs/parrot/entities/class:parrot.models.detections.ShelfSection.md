---
type: Wiki Entity
title: ShelfSection
id: class:parrot.models.detections.ShelfSection
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: A named sub-section within a shelf, defining a region and expected products.
---

# ShelfSection

Defined in [`parrot.models.detections`](../summaries/mod:parrot.models.detections.md).

```python
class ShelfSection(BaseModel)
```

A named sub-section within a shelf, defining a region and expected products.

Sections allow a single shelf row to be divided into independent detection
zones, each with its own product list.

Attributes:
    id: Unique identifier for this section (e.g. ``"left"``, ``"center"``).
    region: Normalized bounding region within the parent shelf.
    products: List of product names expected in this section.
