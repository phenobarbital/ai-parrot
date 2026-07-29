---
type: Wiki Summary
title: parrot_tools.shell_tool.security
id: mod:parrot_tools.shell_tool.security
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: ShellTool Security — re-export shim (FEAT-252).
relates_to:
- concept: class:parrot_tools.shell_tool.security.SecureShellMixin
  rel: defines
- concept: mod:parrot.security.command_sanitizer
  rel: references
---

# `parrot_tools.shell_tool.security`

ShellTool Security — re-export shim (FEAT-252).

The generic security engine (``CommandSanitizer`` / ``SecurityPolicy`` /
``SecurityLevel`` / ``ValidationResult`` / ``CommandVerdict`` /
``CommandRule`` / ``CommandSecurityError``) has been relocated into core
``parrot.security.command_sanitizer`` so that ``PythonCodeSanitizer`` and
``OutputScrubber`` can depend on it without creating an upward import.

All public names are re-exported verbatim here so every existing import of
the form ``from parrot_tools.shell_tool.security import ...`` keeps working
without any change at the call-site.

## Classes

- **`SecureShellMixin`** — Mixin that adds security validation to ShellTool via composition.
