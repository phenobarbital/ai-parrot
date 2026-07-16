---
type: Wiki Entity
title: BoundingBox
id: class:parrot.models.detections.BoundingBox
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Normalized bounding box coordinates
---

# BoundingBox

Defined in [`parrot.models.detections`](../summaries/mod:parrot.models.detections.md).

```python
class BoundingBox(BaseModel)
```

Normalized bounding box coordinates

## Methods

- `def get_coordinates(self) -> tuple[float, float, float, float]` — Return bounding box as (x1, y1, x2, y2)
- `def get_pixel_coordinates(self, width: int, height: int) -> tuple[int, int, int, int]` — Return bounding box as (x1, y1, x2, y2) absolute integer pixels.
