---
type: Wiki Entity
title: Screenshot
id: class:parrot_tools.scraping.models.Screenshot
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Take a screenshot of the page or a specific element
relates_to:
- concept: class:parrot_tools.scraping.models.BrowserAction
  rel: extends
---

# Screenshot

Defined in [`parrot_tools.scraping.models`](../summaries/mod:parrot_tools.scraping.models.md).

```python
class Screenshot(BrowserAction)
```

Take a screenshot of the page or a specific element

## Methods

- `def get_filename(self) -> str` — Generate a filename for the screenshot
