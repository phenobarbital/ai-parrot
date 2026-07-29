---
type: Wiki Entity
title: ProductDimensions
id: class:parrot.advisors.models.ProductDimensions
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Physical dimensions (for space-based filtering).
---

# ProductDimensions

Defined in [`parrot.advisors.models`](../summaries/mod:parrot.advisors.models.md).

```python
class ProductDimensions(BaseModel)
```

Physical dimensions (for space-based filtering).

## Methods

- `def footprint(self) -> float` — Calculate floor space needed.
- `def fits_in(self, available_width: float, available_depth: float) -> bool` — Check if product fits in available space.
