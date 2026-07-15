---
type: Wiki Entity
title: IdentificationResponse
id: class:parrot.models.detections.IdentificationResponse
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Response from product identification
---

# IdentificationResponse

Defined in [`parrot.models.detections`](../summaries/mod:parrot.models.detections.md).

```python
class IdentificationResponse(BaseModel)
```

Response from product identification

## Methods

- `def ensure_unique_detection_ids(cls, v: List[IdentifiedProduct]) -> List[IdentifiedProduct]` — Ensure detection_id is unique; duplicate IDs become new negative IDs.
