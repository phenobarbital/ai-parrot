---
type: Wiki Entity
title: Evaluate
id: class:parrot_tools.scraping.models.Evaluate
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Execute JavaScript code in the browser context
relates_to:
- concept: class:parrot_tools.scraping.models.BrowserAction
  rel: extends
---

# Evaluate

Defined in [`parrot_tools.scraping.models`](../summaries/mod:parrot_tools.scraping.models.md).

```python
class Evaluate(BrowserAction)
```

Execute JavaScript code in the browser context

## Methods

- `def validate_script_source(cls, v, info)` — Ensure either script or script_file is provided, but not both
