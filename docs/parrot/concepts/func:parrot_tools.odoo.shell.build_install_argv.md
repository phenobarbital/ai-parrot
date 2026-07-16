---
type: Concept
title: build_install_argv()
id: func:parrot_tools.odoo.shell.build_install_argv
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Build the argv list for an install or upgrade call.
---

# build_install_argv

```python
def build_install_argv(bin_path: str, modules: list[str], database: str, upgrade: bool=False) -> list[str]
```

Build the argv list for an install or upgrade call.

Args:
    bin_path: Absolute path to the odoo-bin executable.
    modules: List of module technical names.
    database: Target Odoo database name.
    upgrade: When True, use ``-u`` flag; otherwise ``-i``.

Returns:
    argv list ready for :func:`asyncio.create_subprocess_exec`.

Raises:
    ValueError: When any module name or the database name is invalid.
