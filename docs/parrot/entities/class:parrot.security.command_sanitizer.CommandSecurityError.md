---
type: Wiki Entity
title: CommandSecurityError
id: class:parrot.security.command_sanitizer.CommandSecurityError
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Raised when a command fails security validation.
---

# CommandSecurityError

Defined in [`parrot.security.command_sanitizer`](../summaries/mod:parrot.security.command_sanitizer.md).

```python
class CommandSecurityError(Exception)
```

Raised when a command fails security validation.

Attributes:
    result: The ValidationResult that triggered the denial.

Example:
    try:
        shell_tool.assert_command_safe("rm -rf /")
    except CommandSecurityError as exc:
        print(exc.result.reasons)
        print(exc.result.risk_score)
