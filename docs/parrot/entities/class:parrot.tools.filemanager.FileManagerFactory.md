---
type: Wiki Entity
title: FileManagerFactory
id: class:parrot.tools.filemanager.FileManagerFactory
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Factory for creating file managers.
---

# FileManagerFactory

Defined in [`parrot.tools.filemanager`](../summaries/mod:parrot.tools.filemanager.md).

```python
class FileManagerFactory
```

Factory for creating file managers.

Thin delegate over ``navigator.utils.file.FileManagerFactory``.
Maps the historical parrot-side key ``"fs"`` to the upstream
``"local"`` key; forwards all other keys verbatim.

## Methods

- `def create(manager_type: Literal['fs', 'temp', 's3', 'gcs'], **kwargs: Any) -> FileManagerInterface` — Create a file manager instance via the upstream factory.
