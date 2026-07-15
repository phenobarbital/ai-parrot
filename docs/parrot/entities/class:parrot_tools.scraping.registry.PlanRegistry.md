---
type: Wiki Entity
title: PlanRegistry
id: class:parrot_tools.scraping.registry.PlanRegistry
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Async, disk-backed index mapping URLs to saved ScrapingPlan files.
relates_to:
- concept: class:parrot_tools.scraping.base_registry.BasePlanRegistry
  rel: extends
---

# PlanRegistry

Defined in [`parrot_tools.scraping.registry`](../summaries/mod:parrot_tools.scraping.registry.md).

```python
class PlanRegistry(BasePlanRegistry[ScrapingPlan])
```

Async, disk-backed index mapping URLs to saved ScrapingPlan files.

Thin subclass of ``BasePlanRegistry`` specialised for ``ScrapingPlan``
objects.  Overrides ``register`` to use the ScrapingPlan's own
``created_at`` and ``tags`` fields.

Args:
    plans_dir: Directory where plan files and ``registry.json`` are stored.
        Defaults to ``scraping_plans`` in the current working directory.

## Methods

- `async def register(self, plan: ScrapingPlan, relative_path: str) -> None` — Register a ScrapingPlan in the index and persist to disk.
