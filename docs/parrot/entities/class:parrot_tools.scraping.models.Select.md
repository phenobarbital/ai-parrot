---
type: Wiki Entity
title: Select
id: class:parrot_tools.scraping.models.Select
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Select an option from a dropdown/select element.
relates_to:
- concept: class:parrot_tools.scraping.models.BrowserAction
  rel: extends
---

# Select

Defined in [`parrot_tools.scraping.models`](../summaries/mod:parrot_tools.scraping.models.md).

```python
class Select(BrowserAction)
```

Select an option from a dropdown/select element.

## Methods

- `def validate_selection_params(cls, v, info)` — Ensure at least one selection parameter is provided
