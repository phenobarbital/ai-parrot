---
type: Wiki Entity
title: ExecResult
id: class:parrot.eval.sandbox.base.ExecResult
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Result of a command executed inside a sandbox.
---

# ExecResult

Defined in [`parrot.eval.sandbox.base`](../summaries/mod:parrot.eval.sandbox.base.md).

```python
class ExecResult(BaseModel)
```

Result of a command executed inside a sandbox.

Attributes:
    exit_code: Process exit code (0 = success).
    stdout: Standard output captured from the command.
    stderr: Standard error captured from the command.
