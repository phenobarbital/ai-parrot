---
type: Wiki Summary
title: parrot.security.command_sanitizer
id: mod:parrot.security.command_sanitizer
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Command Sanitizer — Shared Security Engine (FEAT-252).
relates_to:
- concept: class:parrot.security.command_sanitizer.CommandRule
  rel: defines
- concept: class:parrot.security.command_sanitizer.CommandSanitizer
  rel: defines
- concept: class:parrot.security.command_sanitizer.CommandSecurityError
  rel: defines
- concept: class:parrot.security.command_sanitizer.CommandVerdict
  rel: defines
- concept: class:parrot.security.command_sanitizer.SecurityLevel
  rel: defines
- concept: class:parrot.security.command_sanitizer.SecurityPolicy
  rel: defines
- concept: class:parrot.security.command_sanitizer.ValidationResult
  rel: defines
---

# `parrot.security.command_sanitizer`

Command Sanitizer — Shared Security Engine (FEAT-252).

Relocated from ``parrot_tools.shell_tool.security`` into core so that both
``shell_tool`` (via re-export shim) and the new ``PythonCodeSanitizer`` /
``OutputScrubber`` can depend on it without requiring core to import
``parrot_tools``.

Architecture:
    SecurityPolicy (config) → CommandSanitizer (validator) → consumer

Layers (when used via CommandSanitizer.validate):
    0. Basic sanity (empty, length)
    1. Parse & extract base command
    2. Dangerous pattern detection (metacharacters, injection vectors)
    3. Command allow/deny list enforcement by SecurityLevel
    4. Per-command argument restrictions (CommandRule)
    5. Path traversal / sandbox enforcement
    6. Custom denied patterns

Note: ``SecureShellMixin`` is kept in ``parrot_tools.shell_tool.security``
because it is shell-specific.  The generic primitives here are intentionally
stdlib-only (logging, os, re, shlex, dataclasses, enum, pathlib, typing).

## Classes

- **`SecurityLevel(str, Enum)`** — Security policy levels.
- **`CommandVerdict(str, Enum)`** — Result of command validation.
- **`ValidationResult`** — Immutable result of command validation.
- **`CommandRule`** — Per-command security rule for argument-level restrictions.
- **`CommandSecurityError(Exception)`** — Raised when a command fails security validation.
- **`SecurityPolicy`** — Configurable security policy for command execution.
- **`CommandSanitizer`** — Multi-layered command sanitizer for shell / agent tool integration.
