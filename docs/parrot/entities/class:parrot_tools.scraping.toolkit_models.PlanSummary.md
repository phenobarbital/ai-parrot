---
type: Wiki Entity
title: PlanSummary
id: class:parrot_tools.scraping.toolkit_models.PlanSummary
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Slim projection of PlanRegistryEntry for plan listing results.
---

# PlanSummary

Defined in [`parrot_tools.scraping.toolkit_models`](../summaries/mod:parrot_tools.scraping.toolkit_models.md).

```python
class PlanSummary(BaseModel)
```

Slim projection of PlanRegistryEntry for plan listing results.

Contains only the metadata needed for display and filtering,
without the internal file path.

Args:
    name: Plan name.
    version: Plan version string.
    url: Target URL the plan was created for.
    domain: Domain extracted from the URL.
    created_at: When the plan was first created.
    last_used_at: When the plan was last used for scraping.
    use_count: Number of times the plan has been used.
    tags: Categorization tags.

## Methods

- `def from_registry_entry(cls, entry: Any) -> PlanSummary` — Create a PlanSummary from a PlanRegistryEntry.
