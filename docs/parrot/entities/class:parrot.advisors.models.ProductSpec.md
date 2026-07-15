---
type: Wiki Entity
title: ProductSpec
id: class:parrot.advisors.models.ProductSpec
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Complete product specification.
---

# ProductSpec

Defined in [`parrot.advisors.models`](../summaries/mod:parrot.advisors.models.md).

```python
class ProductSpec(BaseModel)
```

Complete product specification.

This is the canonical model for any product in the catalog.
The markdown_content is vectorized; features are used for filtering.

## Methods

- `def get_feature(self, name: str) -> Optional[ProductFeature]` — Get a feature by name.
- `def matches_criteria(self, criteria: Dict[str, Any]) -> bool` — Check if product matches all criteria.
