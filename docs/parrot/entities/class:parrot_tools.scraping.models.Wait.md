---
type: Wiki Entity
title: Wait
id: class:parrot_tools.scraping.models.Wait
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Wait for a condition to be met.
relates_to:
- concept: class:parrot_tools.scraping.models.BrowserAction
  rel: extends
---

# Wait

Defined in [`parrot_tools.scraping.models`](../summaries/mod:parrot_tools.scraping.models.md).

```python
class Wait(BrowserAction)
```

Wait for a condition to be met.

Accepts ``condition`` (canonical) or ``selector`` (LLM-friendly alias)
— they mean the same thing when ``condition_type='selector'``.
