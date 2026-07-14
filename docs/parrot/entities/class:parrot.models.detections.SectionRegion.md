---
type: Wiki Entity
title: SectionRegion
id: class:parrot.models.detections.SectionRegion
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Normalized x/y ratio boundaries defining a sub-region within a shelf.
---

# SectionRegion

Defined in [`parrot.models.detections`](../summaries/mod:parrot.models.detections.md).

```python
class SectionRegion(BaseModel)
```

Normalized x/y ratio boundaries defining a sub-region within a shelf.

All values must be in the range [0.0, 1.0] and represent fractional
coordinates relative to the shelf bounding box.

Attributes:
    x_start: Left boundary of the section as a fraction of shelf width.
    x_end: Right boundary of the section as a fraction of shelf width.
    y_start: Top boundary of the section as a fraction of shelf height.
    y_end: Bottom boundary of the section as a fraction of shelf height.
