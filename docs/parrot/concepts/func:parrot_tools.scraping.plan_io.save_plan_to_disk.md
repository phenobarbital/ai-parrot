---
type: Concept
title: save_plan_to_disk()
id: func:parrot_tools.scraping.plan_io.save_plan_to_disk
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Save a ScrapingPlan to disk following the naming convention.
---

# save_plan_to_disk

```python
async def save_plan_to_disk(plan: ScrapingPlan, plans_dir: Path) -> Path
```

Save a ScrapingPlan to disk following the naming convention.

File layout: {plans_dir}/{domain}/{name}_v{version}_{fingerprint}.json
Domain subdirectories are created automatically.

Args:
    plan: The ScrapingPlan to save.
    plans_dir: Root directory for plan storage.

Returns:
    Path to the saved file.
