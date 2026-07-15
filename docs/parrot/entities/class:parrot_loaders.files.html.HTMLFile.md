---
type: Wiki Entity
title: HTMLFile
id: class:parrot_loaders.files.html.HTMLFile
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: A class to handle HTML files asynchronously.
relates_to:
- concept: class:parrot_loaders.files.text.TextFile
  rel: extends
---

# HTMLFile

Defined in [`parrot_loaders.files.html`](../summaries/mod:parrot_loaders.files.html.md).

```python
class HTMLFile(TextFile)
```

A class to handle HTML files asynchronously.

## Methods

- `async def read(self) -> str` — Asynchronously read the content of the html file.
