---
type: Wiki Entity
title: FileManagerToolArgs
id: class:parrot.tools.filemanager.FileManagerToolArgs
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Arguments schema for FileManagerTool.
relates_to:
- concept: class:parrot.tools.abstract.AbstractToolArgsSchema
  rel: extends
---

# FileManagerToolArgs

Defined in [`parrot.tools.filemanager`](../summaries/mod:parrot.tools.filemanager.md).

```python
class FileManagerToolArgs(AbstractToolArgsSchema)
```

Arguments schema for FileManagerTool.

The operation field determines which file operation to perform.
Each operation requires different additional fields.
