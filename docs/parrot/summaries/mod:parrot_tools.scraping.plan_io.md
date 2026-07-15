---
type: Wiki Summary
title: parrot_tools.scraping.plan_io
id: mod:parrot_tools.scraping.plan_io
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Plan File I/O Helpers.
relates_to:
- concept: func:parrot_tools.scraping.plan_io.load_plan_from_disk
  rel: defines
- concept: func:parrot_tools.scraping.plan_io.save_plan_to_disk
  rel: defines
- concept: mod:parrot_tools.scraping.plan
  rel: references
---

# `parrot_tools.scraping.plan_io`

Plan File I/O Helpers.

Async functions to save and load ScrapingPlan instances to/from disk,
following the {plans_dir}/{domain}/{name}_v{version}_{fingerprint}.json layout.

## Functions

- `async def save_plan_to_disk(plan: ScrapingPlan, plans_dir: Path) -> Path` — Save a ScrapingPlan to disk following the naming convention.
- `async def load_plan_from_disk(path: Path) -> ScrapingPlan` — Load a ScrapingPlan from a JSON file on disk.
