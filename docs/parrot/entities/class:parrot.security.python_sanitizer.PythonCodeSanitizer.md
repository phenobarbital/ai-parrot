---
type: Wiki Entity
title: PythonCodeSanitizer
id: class:parrot.security.python_sanitizer.PythonCodeSanitizer
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Allowlist-first AST gate for Python code.
---

# PythonCodeSanitizer

Defined in [`parrot.security.python_sanitizer`](../summaries/mod:parrot.security.python_sanitizer.md).

```python
class PythonCodeSanitizer
```

Allowlist-first AST gate for Python code.

Walks the AST of ``code`` and checks each import statement, name reference,
and function call against the active ``PythonExecutionPolicy``.

Categorical denials (env / introspection / dynamic-exec / data-IO) fire
regardless of the allowlist, providing a belt-and-suspenders defence on top
of the existing ``PythonREPLTool._check_ast_security`` denylist.

Example:
    >>> sanitizer = PythonCodeSanitizer(general_profile())
    >>> sanitizer.validate("import os").is_denied
    True
    >>> sanitizer.validate("sum([1, 2, 3])").is_allowed
    True

## Methods

- `def validate(self, code: str) -> ValidationResult` — Validate *code* against the active policy.
