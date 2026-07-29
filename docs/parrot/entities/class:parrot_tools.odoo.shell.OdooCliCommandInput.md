---
type: Wiki Entity
title: OdooCliCommandInput
id: class:parrot_tools.odoo.shell.OdooCliCommandInput
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Input schema for ``odoo_cli_command``.
---

# OdooCliCommandInput

Defined in [`parrot_tools.odoo.shell`](../summaries/mod:parrot_tools.odoo.shell.md).

```python
class OdooCliCommandInput(BaseModel)
```

Input schema for ``odoo_cli_command``.

Attributes:
    subcommand: A whitelisted odoo-cli/odoo-bin subcommand.
    args: Additional positional arguments for the subcommand.
    database: Target database; defaults to ``ODOO_TEST_DATABASE``.
