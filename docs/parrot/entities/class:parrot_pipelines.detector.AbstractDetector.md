---
type: Wiki Entity
title: AbstractDetector
id: class:parrot_pipelines.detector.AbstractDetector
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Abstract base class for all detectors.
---

# AbstractDetector

Defined in [`parrot_pipelines.detector`](../summaries/mod:parrot_pipelines.detector.md).

```python
class AbstractDetector(ABC)
```

Abstract base class for all detectors.

## Methods

- `async def detect(self, image: Any, image_array: Any, **kwargs: Any) -> Tuple[Any, List[Any]]` — Abstract method for detecting objects in an image.
