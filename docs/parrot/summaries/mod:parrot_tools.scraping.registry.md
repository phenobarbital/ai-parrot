---
type: Wiki Summary
title: parrot_tools.scraping.registry
id: mod:parrot_tools.scraping.registry
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: PlanRegistry — Async, disk-backed index mapping URLs to saved plan files.
relates_to:
- concept: class:parrot_tools.scraping.registry.PlanRegistry
  rel: defines
- concept: mod:parrot_tools.scraping.base_registry
  rel: references
- concept: mod:parrot_tools.scraping.plan
  rel: references
---

# `parrot_tools.scraping.registry`

PlanRegistry — Async, disk-backed index mapping URLs to saved plan files.

Maintains a ``registry.json`` file that maps URL fingerprints to plan file
locations. Provides three-tier lookup: exact fingerprint → path-prefix → domain.
All write mutations are guarded with asyncio.Lock.

Now implemented as a thin subclass of ``BasePlanRegistry[ScrapingPlan]`` —
shared registry logic lives in ``base_registry.py``.

## Classes

- **`PlanRegistry(BasePlanRegistry[ScrapingPlan])`** — Async, disk-backed index mapping URLs to saved ScrapingPlan files.
