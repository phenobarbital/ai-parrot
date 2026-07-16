---
type: Wiki Summary
title: parrot.security.python_sanitizer
id: mod:parrot.security.python_sanitizer
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Allowlist-first AST gate for Python code executed in the REPL sandbox.
relates_to:
- concept: class:parrot.security.python_sanitizer.PythonCodeSanitizer
  rel: defines
- concept: class:parrot.security.python_sanitizer.PythonExecutionPolicy
  rel: defines
- concept: func:parrot.security.python_sanitizer.data_analysis_profile
  rel: defines
- concept: func:parrot.security.python_sanitizer.general_profile
  rel: defines
- concept: mod:parrot.security.command_sanitizer
  rel: references
---

# `parrot.security.python_sanitizer`

Allowlist-first AST gate for Python code executed in the REPL sandbox.

Introduced in FEAT-252 (TASK-1614) as WS1 — the primary code containment layer.
An allowlist-first policy decides which import names, builtins, and operations are
permitted.  Categorical denials (env access, introspection, dynamic exec, data IO)
fire **regardless** of the allowlist as a defence-in-depth layer alongside the
existing ``PythonREPLTool._check_ast_security`` denylist.

Usage:
    >>> sanitizer = PythonCodeSanitizer(general_profile())
    >>> result = sanitizer.validate("import os; os.environ")
    >>> result.is_denied
    True
    >>> result = sanitizer.validate("sum([1, 2, 3])")
    >>> result.is_allowed
    True

## Classes

- **`PythonExecutionPolicy`** — Policy controlling the ``PythonCodeSanitizer`` allowlist-first gate.
- **`PythonCodeSanitizer`** — Allowlist-first AST gate for Python code.

## Functions

- `def general_profile() -> PythonExecutionPolicy` — Return the general (tightest) execution policy.
- `def data_analysis_profile() -> PythonExecutionPolicy` — Return the data-analysis execution policy.
