---
type: Wiki Entity
title: OdooShellInstallInput
id: class:parrot_tools.odoo.shell.OdooShellInstallInput
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Input schema for ``odoo_shell_install_module``.
---

# OdooShellInstallInput

Defined in [`parrot_tools.odoo.shell`](../summaries/mod:parrot_tools.odoo.shell.md).

```python
class OdooShellInstallInput(BaseModel)
```

Input schema for ``odoo_shell_install_module``.

Attributes:
    modules: Technical module names to install.
    database: Target database; defaults to ``ODOO_TEST_DATABASE``.
    upgrade: When True, upgrade (``-u``) instead of install (``-i``).
