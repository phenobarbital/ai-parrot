---
type: Wiki Entity
title: CommandSanitizer
id: class:parrot.security.command_sanitizer.CommandSanitizer
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Multi-layered command sanitizer for shell / agent tool integration.
---

# CommandSanitizer

Defined in [`parrot.security.command_sanitizer`](../summaries/mod:parrot.security.command_sanitizer.md).

```python
class CommandSanitizer
```

Multi-layered command sanitizer for shell / agent tool integration.

Runs a 6-layer validation pipeline to check a command string against the
configured ``SecurityPolicy`` before it reaches the subprocess.

Architecture:
    SecurityPolicy (config) → CommandSanitizer (validator) → consumer

Layers:
    0. Basic sanity (empty, length)
    1. Parse & extract base command (shlex)
    2. Dangerous pattern detection (metacharacters, injection vectors)
    3. Command allow/deny list enforcement by SecurityLevel
    4. Per-command argument restrictions (CommandRule)
    5. Path traversal / sandbox enforcement
    6. Custom denied patterns

Example:
    >>> policy = SecurityPolicy.moderate(sandbox_dir="/home/agent/workspace")
    >>> sanitizer = CommandSanitizer(policy)
    >>> result = sanitizer.validate("rm -rf /")
    >>> result.is_denied
    True
    >>> result = sanitizer.validate("git status")
    >>> result.is_allowed
    True

## Methods

- `def validate(self, command: str) -> ValidationResult` — Validate a command string through all 6 security layers.
- `def validate_batch(self, commands: List[str]) -> List[ValidationResult]` — Validate multiple commands, returning one result per command.
- `def validate_path(self, path: str) -> ValidationResult` — Validate a filesystem path against sandbox and dangerous path patterns.
