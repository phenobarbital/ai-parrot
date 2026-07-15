---
type: Wiki Entity
title: PlanLike
id: class:parrot_tools.scraping.base_registry.PlanLike
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Protocol that all registrable plan types must satisfy.
---

# PlanLike

Defined in [`parrot_tools.scraping.base_registry`](../summaries/mod:parrot_tools.scraping.base_registry.md).

```python
class PlanLike(Protocol)
```

Protocol that all registrable plan types must satisfy.

Every concrete plan model passed to ``BasePlanRegistry.register()`` must
expose these attributes.  Using a ``Protocol`` removes the need for
``type: ignore`` comments and lets ``mypy`` / ``pyright`` verify callers
at import time.
