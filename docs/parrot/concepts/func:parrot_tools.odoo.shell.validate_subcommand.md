---
type: Concept
title: validate_subcommand()
id: func:parrot_tools.odoo.shell.validate_subcommand
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Validate that a subcommand is on the whitelist.
---

# validate_subcommand

```python
def validate_subcommand(subcommand: str) -> None
```

Validate that a subcommand is on the whitelist.

Args:
    subcommand: The subcommand string to validate.

Raises:
    ValueError: When the subcommand is not whitelisted.
