---
type: Wiki Entity
title: FileManagementArgs
id: class:parrot_tools.textfile.FileManagementArgs
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Arguments for file management operations.
---

# FileManagementArgs

Defined in [`parrot_tools.textfile`](../summaries/mod:parrot_tools.textfile.md).

```python
class FileManagementArgs(BaseModel)
```

Arguments for file management operations.

## Methods

- `def validate_operation(cls, v)` — Validate operation type.
- `def validate_content(cls, v, info)` — Ensure content is provided for create/edit operations.
