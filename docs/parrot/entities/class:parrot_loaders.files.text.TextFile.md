---
type: Wiki Entity
title: TextFile
id: class:parrot_loaders.files.text.TextFile
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: A class to handle text files asynchronously.
relates_to:
- concept: class:parrot_loaders.files.abstract.FilePlugin
  rel: extends
---

# TextFile

Defined in [`parrot_loaders.files.text`](../summaries/mod:parrot_loaders.files.text.md).

```python
class TextFile(FilePlugin)
```

A class to handle text files asynchronously.

## Methods

- `async def open(self)` — Asynchronously open the text file.
- `async def close(self)` — Asynchronously close the text file.
- `async def read(self) -> str` — Asynchronously read the content of the text file.
