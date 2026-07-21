---
type: Wiki Entity
title: SecureShellMixin
id: class:parrot_tools.shell_tool.security.SecureShellMixin
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Mixin that adds security validation to ShellTool via composition.
---

# SecureShellMixin

Defined in [`parrot_tools.shell_tool.security`](../summaries/mod:parrot_tools.shell_tool.security.md).

```python
class SecureShellMixin
```

Mixin that adds security validation to ShellTool via composition.

Provides three public methods:

- ``set_security_policy(policy)`` — attach a ``SecurityPolicy``; creates
  a ``CommandSanitizer`` internally.
- ``validate_command(command)`` — return a ``ValidationResult``.
- ``assert_command_safe(command)`` — raise ``CommandSecurityError`` if the
  command is denied or requires review.

Backward-compatible design: if no policy has been set (``_sanitizer`` is
``None``), ``validate_command`` returns ALLOWED for every command, matching
the old no-security behaviour.

Example:
    >>> class MyShell(SecureShellMixin):
    ...     pass
    >>> shell = MyShell()
    >>> shell.set_security_policy(SecurityPolicy.moderate())
    >>> shell.assert_command_safe("rm -rf /")  # raises CommandSecurityError

## Methods

- `def set_security_policy(self, policy: SecurityPolicy) -> None` — Attach a security policy, replacing any previously set policy.
- `def validate_command(self, command: str) -> ValidationResult` — Validate a command string against the active security policy.
- `def assert_command_safe(self, command: str) -> None` — Validate and raise if the command is denied or needs review.
