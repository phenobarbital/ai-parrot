---
type: Wiki Entity
title: CommandRule
id: class:parrot.security.command_sanitizer.CommandRule
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Per-command security rule for argument-level restrictions.
---

# CommandRule

Defined in [`parrot.security.command_sanitizer`](../summaries/mod:parrot.security.command_sanitizer.md).

```python
class CommandRule
```

Per-command security rule for argument-level restrictions.

Attributes:
    name: The command this rule applies to (e.g. "curl", "find").
    allowed_args: If set, only these flags/subcommands are permitted.
    denied_args: These flags are always denied regardless of context.
    denied_patterns: Regex patterns applied to the full command string.
        Any match denies the command.
    max_args: Maximum number of arguments (excluding the command itself).
    require_absolute_path: If True, path arguments must be absolute.
    sandbox_paths: If set, path arguments must be under one of these dirs.
        Inherits global sandbox_dir if None.
    allow_pipe: Allow this command to appear in pipe chains.
    allow_redirect: Allow output redirection for this command.
    risk_base: Base risk score contribution (0.0–1.0) added when this
        command is used. Individual violations add on top of this.
