---
type: Wiki Entity
title: MoveFile
id: class:parrot_tools.shell_tool.actions.MoveFile
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Move/rename a file or directory.
---

# MoveFile

Defined in [`parrot_tools.shell_tool.actions`](../summaries/mod:parrot_tools.shell_tool.actions.md).

```python
class MoveFile(BaseAction)
```

Move/rename a file or directory.
- recursive flag is accepted for parity (moving dirs is allowed by default).
- overwrite=True will replace an existing destination.
- make_dirs=True will create the destination parent directory.
