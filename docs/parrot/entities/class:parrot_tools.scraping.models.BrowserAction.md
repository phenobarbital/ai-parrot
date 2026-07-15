---
type: Wiki Entity
title: BrowserAction
id: class:parrot_tools.scraping.models.BrowserAction
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Base class for all browser actions
---

# BrowserAction

Defined in [`parrot_tools.scraping.models`](../summaries/mod:parrot_tools.scraping.models.md).

```python
class BrowserAction(BaseModel, ABC)
```

Base class for all browser actions

## Methods

- `def get_action_type(self) -> str` — Return the action type identifier used for dispatch.
