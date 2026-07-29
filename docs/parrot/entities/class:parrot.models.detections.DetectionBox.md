---
type: Wiki Entity
title: DetectionBox
id: class:parrot.models.detections.DetectionBox
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Bounding box from object detection
---

# DetectionBox

Defined in [`parrot.models.detections`](../summaries/mod:parrot.models.detections.md).

```python
class DetectionBox(BaseModel)
```

Bounding box from object detection

## Methods

- `def coerce_confidence(cls, v: Any) -> float` — Coerce non-numeric LLM outputs to a safe default confidence.
