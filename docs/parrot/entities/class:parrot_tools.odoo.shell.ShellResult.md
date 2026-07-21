---
type: Wiki Entity
title: ShellResult
id: class:parrot_tools.odoo.shell.ShellResult
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Typed result envelope for odoo-bin / odoo-cli subprocess calls.
---

# ShellResult

Defined in [`parrot_tools.odoo.shell`](../summaries/mod:parrot_tools.odoo.shell.md).

```python
class ShellResult(BaseModel)
```

Typed result envelope for odoo-bin / odoo-cli subprocess calls.

Always constructed internally — never from user-supplied data.

Attributes:
    success: True when the process exited with return-code 0.
    returncode: The raw OS exit code.
    stdout: Captured standard output (truncated to 8 KiB).
    stderr: Captured standard error (truncated to 4 KiB).
    argv: The argv list that was executed (for auditability).
    message: Human-readable summary for the agent.
