---
type: Concept
title: lazy_import()
id: func:parrot._imports.lazy_import
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Import a module lazily, raising a clear error if not installed.
---

# lazy_import

```python
def lazy_import(module_path: str, package_name: str | None=None, extra: str | None=None) -> ModuleType
```

Import a module lazily, raising a clear error if not installed.

Imports ``module_path`` using ``importlib.import_module`` and returns the
module object on success. If the module is not installed, raises an
``ImportError`` with an actionable install instruction.

This function is thread-safe because ``importlib.import_module`` is
thread-safe (it uses the module import lock internally).

Args:
    module_path: Dotted Python module path to import, e.g. ``"weasyprint"``
        or ``"sentence_transformers"``.
    package_name: Human-readable pip package name. If omitted, the first
        segment of ``module_path`` is used. Use this when the pip name
        differs from the module name, e.g. ``package_name="sentence-transformers"``
        for ``module_path="sentence_transformers"``.
    extra: AI-Parrot extras group name. When provided, the error message
        will suggest ``pip install ai-parrot[<extra>]``. When omitted, the
        error message will suggest ``pip install <package_name>`` directly.

Returns:
    The imported module object.

Raises:
    ImportError: If ``module_path`` cannot be imported, with a message that
        includes the install instruction.

Examples:
    >>> import json
    >>> mod = lazy_import("json")
    >>> mod.dumps({"key": "value"})
    '{"key": "value"}'

    >>> lazy_import("weasyprint", extra="pdf")  # if not installed
    ImportError: 'weasyprint' is required but not installed.
                 Install it with: pip install ai-parrot[pdf]
