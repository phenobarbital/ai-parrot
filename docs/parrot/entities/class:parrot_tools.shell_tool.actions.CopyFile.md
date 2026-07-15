---
type: Wiki Entity
title: CopyFile
id: class:parrot_tools.shell_tool.actions.CopyFile
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Copy a file or directory.
---

# CopyFile

Defined in [`parrot_tools.shell_tool.actions`](../summaries/mod:parrot_tools.shell_tool.actions.md).

```python
class CopyFile(BaseAction)
```

Copy a file or directory.
- If source is a directory, set recursive=True to copy its tree.
- overwrite=True will replace an existing destination.
- make_dirs=True will create the destination parent directory.
