---
type: Wiki Summary
title: parrot.advisors.models
id: mod:parrot.advisors.models
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Module parrot.advisors.models
relates_to:
- concept: class:parrot.advisors.models.FeatureType
  rel: defines
- concept: class:parrot.advisors.models.ProductDimensions
  rel: defines
- concept: class:parrot.advisors.models.ProductFeature
  rel: defines
- concept: class:parrot.advisors.models.ProductSpec
  rel: defines
---

# `parrot.advisors.models`

## Classes

- **`FeatureType(str, Enum)`** — Types of product features for filtering logic.
- **`ProductFeature(BaseModel)`** — A single product feature/specification.
- **`ProductDimensions(BaseModel)`** — Physical dimensions (for space-based filtering).
- **`ProductSpec(BaseModel)`** — Complete product specification.
