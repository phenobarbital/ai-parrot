---
type: Wiki Entity
title: DeleteFile
id: class:parrot_tools.shell_tool.actions.DeleteFile
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Deletes a file or directory (with optional recursion).
---

# DeleteFile

Defined in [`parrot_tools.shell_tool.actions`](../summaries/mod:parrot_tools.shell_tool.actions.md).

```python
class DeleteFile(BaseAction)
```

Deletes a file or directory (with optional recursion).
Options:
  - recursive: remove directories recursively
  - missing_ok: do not error if path does not exist
