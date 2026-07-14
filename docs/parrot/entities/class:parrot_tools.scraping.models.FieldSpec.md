---
type: Wiki Entity
title: FieldSpec
id: class:parrot_tools.scraping.models.FieldSpec
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: One sub-selector for a row-of-fields ``Extract`` step.
---

# FieldSpec

Defined in [`parrot_tools.scraping.models`](../summaries/mod:parrot_tools.scraping.models.md).

```python
class FieldSpec(BaseModel)
```

One sub-selector for a row-of-fields ``Extract`` step.

Applied RELATIVE to each row element matched by the parent Extract's
``selector``. Use this to describe the columns of a repeating block
(e.g. for each plan card: name, price, data, CTA).
