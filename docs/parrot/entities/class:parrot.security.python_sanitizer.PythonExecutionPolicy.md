---
type: Wiki Entity
title: PythonExecutionPolicy
id: class:parrot.security.python_sanitizer.PythonExecutionPolicy
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Policy controlling the ``PythonCodeSanitizer`` allowlist-first gate.
---

# PythonExecutionPolicy

Defined in [`parrot.security.python_sanitizer`](../summaries/mod:parrot.security.python_sanitizer.md).

```python
class PythonExecutionPolicy
```

Policy controlling the ``PythonCodeSanitizer`` allowlist-first gate.

Attributes:
    level: The ``SecurityLevel`` posture (default ``RESTRICTIVE``).
    default_deny: When ``True`` (default), any import / call / name NOT on
        the allowlist is denied. Set to ``False`` only for trusted contexts.
    allowed_imports: Frozenset of module root names that may be imported.
    allowed_builtins: Frozenset of builtin names that may be called.
        Wired into ``_check_name``: when ``default_deny=True`` and this set
        is non-empty, any name not in this allowlist is denied (spec §WS1).
    deny_env_access: Deny all ``os.environ`` / ``os.getenv`` access (default ``True``).
    deny_introspection: Deny ``globals``, ``locals``, ``__class__.__bases__`` etc.
        (default ``True``).
    deny_dynamic_exec: Deny ``eval``, ``exec``, ``compile``, ``__import__``
        (default ``True``).
    deny_data_io: Deny file/network/DB IO (default ``True``).
    isolation: Execution isolation mode (``"in_process"`` — subprocess is a Non-Goal).
    max_output_bytes: Maximum allowed output size in bytes.
