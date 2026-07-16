---
type: Wiki Entity
title: OdooShellUpgradeInput
id: class:parrot_tools.odoo.shell.OdooShellUpgradeInput
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Input schema for ``odoo_shell_upgrade_module``.
---

# OdooShellUpgradeInput

Defined in [`parrot_tools.odoo.shell`](../summaries/mod:parrot_tools.odoo.shell.md).

```python
class OdooShellUpgradeInput(BaseModel)
```

Input schema for ``odoo_shell_upgrade_module``.

Intentionally omits the ``upgrade`` field — this tool always upgrades.
The LLM cannot accidentally set ``upgrade=False`` on an upgrade tool.

Attributes:
    modules: Technical module names to upgrade.
    database: Target database; defaults to ``ODOO_TEST_DATABASE``.
