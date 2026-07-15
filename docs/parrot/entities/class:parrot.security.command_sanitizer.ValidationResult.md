---
type: Wiki Entity
title: ValidationResult
id: class:parrot.security.command_sanitizer.ValidationResult
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Immutable result of command validation.
---

# ValidationResult

Defined in [`parrot.security.command_sanitizer`](../summaries/mod:parrot.security.command_sanitizer.md).

```python
class ValidationResult
```

Immutable result of command validation.

Attributes:
    verdict: Final decision for the command.
    command: The original command string that was validated.
    reasons: Tuple of human-readable reasons for the verdict.
    sanitized_command: Optional cleaned version of the command (reserved for future use).
    risk_score: Aggregate risk score in range [0.0, 1.0].
        0.0 = completely safe, 1.0 = critical danger.

## Methods

- `def is_allowed(self) -> bool` — Return True if the command is allowed to execute.
- `def is_denied(self) -> bool` — Return True if the command was denied.
