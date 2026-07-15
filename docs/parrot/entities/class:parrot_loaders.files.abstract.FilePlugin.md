---
type: Wiki Entity
title: FilePlugin
id: class:parrot_loaders.files.abstract.FilePlugin
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: FilePlugin is a base class for Open Files.
---

# FilePlugin

Defined in [`parrot_loaders.files.abstract`](../summaries/mod:parrot_loaders.files.abstract.md).

```python
class FilePlugin(ABC)
```

FilePlugin is a base class for Open Files.
It provides a common interface for all opening all kind of iles.
Subclasses should implement the `open` method to define
the specific file processing logic.

## Methods

- `async def read(self)` — Return the content of the file, need to be implemented in the subclass.
