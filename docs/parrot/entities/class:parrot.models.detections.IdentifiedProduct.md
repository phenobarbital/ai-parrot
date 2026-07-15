---
type: Wiki Entity
title: IdentifiedProduct
id: class:parrot.models.detections.IdentifiedProduct
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Product identified by LLM using reference images
---

# IdentifiedProduct

Defined in [`parrot.models.detections`](../summaries/mod:parrot.models.detections.md).

```python
class IdentifiedProduct(BaseModel)
```

Product identified by LLM using reference images

## Methods

- `def validate_confidence(cls, v: Any) -> float` — Ensure confidence is between 0 and 1.
- `def validate_position_on_shelf(cls, v: Any) -> Optional[str]` — Ensure position_on_shelf is one of the accepted values.
- `def set_id_for_llm_found_items(cls, v: Any) -> int` — If detection_id is null, generate a unique negative ID.
- `def convert_list_to_detection_box(cls, v: Any, values: Any) -> Any` — If detection_box is a list [x1,y1,x2,y2], convert it to a DetectionBox object.
- `def ensure_detection_box_fields(cls, v: Optional[DetectionBox], values: Any) -> Optional[DetectionBox]` — Ensure detection_box has class_id/class_name/area to avoid overlay crashes.
- `def coerce_extra(cls, v: Any) -> Dict[str, str]` — Allow LLMs to return a string for extra; coerce to a dict.
