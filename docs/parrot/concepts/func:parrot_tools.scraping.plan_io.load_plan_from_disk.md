---
type: Concept
title: load_plan_from_disk()
id: func:parrot_tools.scraping.plan_io.load_plan_from_disk
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Load a ScrapingPlan from a JSON file on disk.
---

# load_plan_from_disk

```python
async def load_plan_from_disk(path: Path) -> ScrapingPlan
```

Load a ScrapingPlan from a JSON file on disk.

Args:
    path: Path to the plan JSON file.

Returns:
    Deserialized ScrapingPlan instance.

Raises:
    FileNotFoundError: If the file does not exist.
