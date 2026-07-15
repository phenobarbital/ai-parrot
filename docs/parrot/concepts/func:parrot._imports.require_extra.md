---
type: Concept
title: require_extra()
id: func:parrot._imports.require_extra
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Verify that all required modules for an extras group are importable.
---

# require_extra

```python
def require_extra(extra: str, *modules: str) -> None
```

Verify that all required modules for an extras group are importable.

Iterates over ``modules`` and calls ``lazy_import`` on each. If any module
is not importable, raises an ``ImportError`` with the install instruction
for the given ``extra``.

Useful as a guard at the top of a class or function that requires a full
extras group, rather than doing per-module lazy imports inside each method.

Args:
    extra: AI-Parrot extras group name, e.g. ``"db"``, ``"pdf"``, ``"ocr"``.
        Used in the error message: ``pip install ai-parrot[<extra>]``.
    *modules: One or more dotted Python module paths to check.

Raises:
    ImportError: If any of the listed modules cannot be imported, with a
        message directing the user to install the extras group.

Examples:
    >>> require_extra("core", "json", "os")  # both installed, no error

    >>> require_extra("db", "json", "nonexistent_xyz")
    ImportError: 'nonexistent_xyz' is required but not installed.
                 Install it with: pip install ai-parrot[db]
