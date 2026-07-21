---
type: Wiki Entity
title: ScrapingPlan
id: class:parrot_tools.scraping.plan.ScrapingPlan
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Declarative scraping plan — value object, immutable once saved.
---

# ScrapingPlan

Defined in [`parrot_tools.scraping.plan`](../summaries/mod:parrot_tools.scraping.plan.md).

```python
class ScrapingPlan(BaseModel)
```

Declarative scraping plan — value object, immutable once saved.

Auto-populates `domain`, `name`, and `fingerprint` from the URL
in `model_post_init`.

## Methods

- `def normalized_url(self) -> str` — Strip query params and fragments for stable fingerprinting.
- `def model_post_init(self, __context: Any) -> None` — Auto-populate domain, name, and fingerprint from URL.
