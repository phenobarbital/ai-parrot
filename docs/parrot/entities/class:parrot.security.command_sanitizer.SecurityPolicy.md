---
type: Wiki Entity
title: SecurityPolicy
id: class:parrot.security.command_sanitizer.SecurityPolicy
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Configurable security policy for command execution.
---

# SecurityPolicy

Defined in [`parrot.security.command_sanitizer`](../summaries/mod:parrot.security.command_sanitizer.md).

```python
class SecurityPolicy
```

Configurable security policy for command execution.

Three preset factory methods are available covering the most common
use cases. For fine-grained control, instantiate directly and set
individual fields.

Attributes:
    level: The broad security level governing default allow/deny behaviour.
    allowed_commands: Commands explicitly permitted. In RESTRICTIVE mode
        only these commands may run. In MODERATE mode these are merged
        with the safe defaults.
    denied_commands: Commands explicitly denied regardless of level.
    command_rules: Per-command argument restrictions keyed by command name.
    sandbox_dir: If set, all path arguments must resolve under this directory.
    max_command_length: Maximum number of characters in a single command.
    max_output_bytes: Maximum stdout bytes collected before truncation.
    max_stderr_bytes: Maximum stderr bytes collected before truncation.
    allow_shell_operators: Allow pipe (|) and output redirect (>, >>).
    allow_chaining: Allow command chaining (;, &&, ||).
    allow_env_expansion: Allow environment variable expansion ($VAR, ${VAR}).
    allow_command_substitution: Allow $(...) and backtick substitution.
    allow_glob: Allow glob patterns (*, ?, [...]).
    denied_patterns: Extra regex patterns applied to every command string.
    audit_log: Log all validation decisions at WARNING level when denied.

Example:
    >>> policy = SecurityPolicy.restrictive(
    ...     allowed_commands={"git", "python3", "ls"},
    ...     sandbox_dir="/home/agent/workspace",
    ... )
    >>> sanitizer = CommandSanitizer(policy)
    >>> result = sanitizer.validate("rm -rf /")
    >>> result.is_denied
    True

## Methods

- `def restrictive(cls, allowed_commands: Optional[Set[str]]=None, sandbox_dir: Optional[str]=None, command_rules: Optional[Dict[str, CommandRule]]=None) -> 'SecurityPolicy'` — Create a restrictive policy — only explicitly allowed commands run.
- `def moderate(cls, allowed_commands: Optional[Set[str]]=None, sandbox_dir: Optional[str]=None) -> 'SecurityPolicy'` — Create a moderate policy — safe defaults plus user-specified commands.
- `def permissive(cls, denied_commands: Optional[Set[str]]=None, sandbox_dir: Optional[str]=None) -> 'SecurityPolicy'` — Create a permissive policy — everything allowed except denied commands.
